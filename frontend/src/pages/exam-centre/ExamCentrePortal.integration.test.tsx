import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { screen, waitFor, render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import {
  renderWithProviders,
  jsonResponse,
  pdfResponse,
  seedAuthenticatedSession,
  routedFetchMock,
} from "../../test/testUtils";
import { AppRoutes } from "../../routes/AppRoutes";
import { AppHeader } from "../../components/layout/AppHeader";
import { AuthProvider } from "../../contexts/AuthContext";

const CENTRE_ME = () => jsonResponse(200, { user_id: "u3", username: "centre1", role: "Examination Centre", centre_id: "c1" });
const ADMIN_ME = () => jsonResponse(200, { user_id: "u1", username: "admin1", role: "Admin", centre_id: null });
const AUDITOR_ME = () => jsonResponse(200, { user_id: "u2", username: "auditor1", role: "Auditor", centre_id: null });

const PAST = "2020-01-01T09:00:00Z";
const FUTURE = "2099-01-01T09:00:00Z";

function paper(id: string, subject: string, release: string) {
  return {
    lock_status: release === PAST ? "released" : "locked",
    paper_id: id,
    subject,
    status: "registered",
    sha256_hash: `hash-${id}`,
    release_timestamp: release,
    created_at: "2026-01-01T00:00:00Z",
    ledger_tx_reference: null,
  };
}

function errorBody(status: number, message: string) {
  return jsonResponse(status, { error: { message, status_code: status } });
}

/** Routes for one paper's detail page. `retrieve` is swappable per test. */
function detailRoutes(release: string, retrieve: () => Response, id = "p1") {
  const p = paper(id, "Data Structures", release);
  return {
    "/auth/me": CENTRE_ME,
    [`/papers/${id}/retrieve`]: retrieve,
    [`/papers/${id}/status`]: () =>
      jsonResponse(200, { paper_id: id, status: p.status, release_timestamp: release, lock_status: p.lock_status }),
    [`/papers/${id}`]: () =>
      jsonResponse(200, {
        paper_id: id,
        subject: p.subject,
        status: p.status,
        sha256_hash: p.sha256_hash,
        release_timestamp: release,
        created_at: p.created_at,
        lock_status: p.lock_status,
      }),
  };
}

let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
  createObjectURL = vi.fn(() => "blob:mock-paper-1");
  revokeObjectURL = vi.fn();
  URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Exam Centre Portal — authentication and RBAC", () => {
  it("lets an authenticated Examination Centre reach the portal", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers?": () => jsonResponse(200, { items: [], total: 0, page: 1, page_size: 100 }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });

    expect(await screen.findByRole("heading", { name: /examination centre portal/i })).toBeInTheDocument();
    expect(screen.getByText(/centre1/)).toBeInTheDocument();
  });

  it("redirects an unauthenticated user to /login", async () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });

  it("sends an Examination Centre away from Admin routes and makes no admin API calls", async () => {
    seedAuthenticatedSession();
    const fetchMock = routedFetchMock({ "/auth/me": CENTRE_ME });
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<AppRoutes />, { route: "/admin" });

    expect(await screen.findByRole("heading", { name: /access denied/i })).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/admin/") || u.includes("/audit/") || u.includes("/monitoring/"))).toBe(false);
  });

  it("sends an Admin away from the Exam Centre portal", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": ADMIN_ME }));
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });
    expect(await screen.findByRole("heading", { name: /access denied/i })).toBeInTheDocument();
  });

  it("sends an Auditor away from the Exam Centre portal", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": AUDITOR_ME }));
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });
    expect(await screen.findByRole("heading", { name: /access denied/i })).toBeInTheDocument();
  });

  it("still lets Admin and Auditor reach the admin area", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": AUDITOR_ME,
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin" });
    expect(await screen.findByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
  });

  it("logs out via the header, clears the stored token and returns to login", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/logout": () => jsonResponse(200, { detail: "Logged out." }),
        "/auth/me": CENTRE_ME,
        "/papers?": () => jsonResponse(200, { items: [], total: 0, page: 1, page_size: 100 }),
      }),
    );
    render(
      <MemoryRouter initialEntries={["/exam-centre"]}>
        <AuthProvider>
          <AppHeader />
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>,
    );

    await userEvent.click(await screen.findByRole("button", { name: /log out/i }));
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(sessionStorage.getItem("qpaper_access_token")).toBeNull();
  });
});

describe("Exam Centre Portal — paper list", () => {
  it("shows only the papers the backend returns, with real metadata and summary", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers?": () =>
          jsonResponse(200, {
            items: [paper("p1", "Data Structures", PAST), paper("p2", "Operating Systems", FUTURE)],
            total: 2,
            page: 1,
            page_size: 100,
          }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });

    expect(await screen.findByText("Data Structures")).toBeInTheDocument();
    expect(screen.getByText("Operating Systems")).toBeInTheDocument();
    expect(screen.getAllByText("Authorized")).toHaveLength(2);
    expect(screen.queryByText(/some other paper/i)).not.toBeInTheDocument();
    // Summary values derived from the two returned rows.
    expect(screen.getByRole("heading", { name: /^authorized papers$/i }).parentElement).toHaveTextContent("2");
    expect(screen.getByRole("heading", { name: /^release state: released$/i }).parentElement).toHaveTextContent("1");
    expect(screen.getByRole("heading", { name: /^release state: locked$/i }).parentElement).toHaveTextContent("1");
    expect(screen.getAllByRole("link", { name: /view details/i })).toHaveLength(2);
  });

  it("takes locked/released from the server's lock_status, not from the device clock (Phase 6H)", async () => {
    seedAuthenticatedSession();
    // Timestamps deliberately contradict the server's answer: the PAST-dated paper is reported
    // "locked" and the far-future one "released". The UI must follow the server.
    const contradictory = [
      { ...paper("p1", "Server Says Locked", PAST), lock_status: "locked" },
      { ...paper("p2", "Server Says Released", FUTURE), lock_status: "released" },
      { ...paper("p3", "Also Released", FUTURE), lock_status: "released" },
    ];
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers?": () => jsonResponse(200, { items: contradictory, total: 3, page: 1, page_size: 100 }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });

    await screen.findByText("Server Says Locked");
    expect(screen.getByRole("heading", { name: /^release state: released$/i }).parentElement).toHaveTextContent("2");
    expect(screen.getByRole("heading", { name: /^release state: locked$/i }).parentElement).toHaveTextContent("1");
    expect(screen.getAllByText("Released")).toHaveLength(2);
    expect(screen.getAllByText("Locked")).toHaveLength(1);
    // Registration status stays a separate column and is not reworded as a release state.
    expect(screen.getAllByText("registered")).toHaveLength(3);
  });

  it("shows an empty state when no paper is authorized", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers?": () => jsonResponse(200, { items: [], total: 0, page: 1, page_size: 100 }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });
    expect(await screen.findByText(/no question papers have been authorized/i)).toBeInTheDocument();
  });

  it("does not invent the locked/released split when not every paper was fetched", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers?": () =>
          jsonResponse(200, { items: [paper("p1", "Data Structures", PAST)], total: 250, page: 1, page_size: 100 }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });
    await screen.findByText("Data Structures");
    expect(screen.queryByRole("heading", { name: /release time reached/i })).not.toBeInTheDocument();
  });

  it("shows a safe fixed message (not the backend's internal text) on a 503", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers?": () => errorBody(503, "connection to server at 10.0.0.5 failed FABRIC_VERIFICATION_MODE"),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre" });
    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/FABRIC_VERIFICATION_MODE|10\.0\.0\.5/)).not.toBeInTheDocument();
  });
});

describe("Exam Centre Portal — paper detail", () => {
  it("shows metadata, status and the retrieve action", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock(detailRoutes(PAST, () => pdfResponse())));
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    expect(await screen.findByRole("heading", { name: /data structures/i })).toBeInTheDocument();
    expect(screen.getByText("p1")).toBeInTheDocument();
    expect(screen.getByText("hash-p1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retrieve question paper/i })).toBeEnabled();
  });

  it("does not expose a paper the centre is not authorized for (403 on metadata)", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers/other/status": () => errorBody(403, "You are not authorized to access this paper."),
        "/papers/other": () => errorBody(403, "You are not authorized to access this paper."),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/other" });

    expect(await screen.findByText("You are not authorized to access this question paper.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retrieve/i })).not.toBeInTheDocument();
  });

  it("handles 404 for an unknown paper", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": CENTRE_ME,
        "/papers/missing/status": () => errorBody(404, "The requested resource was not found."),
        "/papers/missing": () => errorBody(404, "The requested resource was not found."),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/missing" });
    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });
});

describe("Exam Centre Portal — time-lock", () => {
  it("shows an informational countdown and a locked message when the backend refuses pre-release retrieval", async () => {
    seedAuthenticatedSession();
    const fetchMock = routedFetchMock(
      detailRoutes(FUTURE, () => errorBody(403, "This paper is not yet available.")),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    expect(await screen.findByText(/scheduled release in/i)).toBeInTheDocument();
    // The countdown does NOT decide access: the retrieve button is still offered.
    await userEvent.click(screen.getByRole("button", { name: /retrieve question paper/i }));

    expect(await screen.findByText("Question paper is locked until the scheduled release time.")).toBeInTheDocument();
    expect(screen.queryByText(/open question paper/i)).not.toBeInTheDocument();
    // Cooldown prevents aggressive retrying.
    expect(screen.getByRole("button", { name: /try again in \d+s/i })).toBeDisabled();
    const retrieveCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes("/retrieve"));
    expect(retrieveCalls).toHaveLength(1);
  });

  it("offers the released paper only after the backend returns it", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock(detailRoutes(PAST, () => pdfResponse())));
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));

    const open = await screen.findByRole("link", { name: /open question paper/i });
    expect(open).toHaveAttribute("href", "blob:mock-paper-1");
    expect(open).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByRole("link", { name: /download pdf/i })).toHaveAttribute("download", "question-paper-Data_Structures.pdf");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
  });
});

describe("Exam Centre Portal — retrieval failures", () => {
  it("shows a security message on an integrity failure and never treats it as success", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock(detailRoutes(PAST, () => errorBody(409, "This paper failed integrity verification and cannot be released."))),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));

    expect(await screen.findByText("Security verification failed. The question paper was not released.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /open question paper/i })).not.toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("shows the unauthorized message on a 403 that is not the time-lock", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock(detailRoutes(PAST, () => errorBody(403, "You are not authorized to access this paper."))),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));
    expect(await screen.findByText("You are not authorized to access this question paper.")).toBeInTheDocument();
  });

  it("hides backend-internal wording on a 503 during release", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock(
        detailRoutes(PAST, () =>
          errorBody(503, "Blockchain-backed integrity verification is currently unavailable and FABRIC_VERIFICATION_MODE=strict requires it"),
        ),
      ),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));
    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/FABRIC_VERIFICATION_MODE/)).not.toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("rejects a 200 response that is not a PDF instead of offering it as a file", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock(detailRoutes(PAST, () => pdfResponse("text/html"))));
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("link", { name: /open question paper/i })).not.toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("clears the session and returns to login with a message on a 401", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock(detailRoutes(PAST, () => errorBody(401, "Session expired. Please log in again."))),
    );
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));

    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(await screen.findByText(/your session has expired/i)).toBeInTheDocument();
    expect(sessionStorage.getItem("qpaper_access_token")).toBeNull();
  });
});

describe("Exam Centre Portal — released file handling", () => {
  it("revokes the object URL when the file is discarded", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock(detailRoutes(PAST, () => pdfResponse())));
    renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));
    await screen.findByRole("link", { name: /open question paper/i });
    await userEvent.click(screen.getByRole("button", { name: /discard from browser/i }));

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-paper-1");
    expect(screen.queryByRole("link", { name: /open question paper/i })).not.toBeInTheDocument();
  });

  it("revokes the object URL when leaving the page, and never persists the PDF", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock(detailRoutes(PAST, () => pdfResponse())));
    const { unmount } = renderWithProviders(<AppRoutes />, { route: "/exam-centre/papers/p1" });

    await userEvent.click(await screen.findByRole("button", { name: /retrieve question paper/i }));
    await screen.findByRole("link", { name: /open question paper/i });

    // Only the session token may be in browser storage.
    expect(Object.keys(sessionStorage)).toEqual(["qpaper_access_token"]);
    expect(localStorage.length).toBe(0);

    unmount();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-paper-1"));
  });
});
