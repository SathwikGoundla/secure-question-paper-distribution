import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { PaperDetailPage } from "./PaperDetailPage";
import { renderWithProviders, jsonResponse, routedFetchMock, seedAuthenticatedSession } from "../../../test/testUtils";

/**
 * Phase 6F — tests the new "Revoke an examination centre's
 * authorization" section this phase added to PaperDetailPage (the
 * frontend counterpart of the new POST /papers/{paper_id}/revoke
 * backend endpoint). The pre-existing authorize form on this same
 * page had no test coverage before Phase 6F either; backfilling that
 * is out of this phase's scope (see PROJECT_STATE.md's Phase 6F
 * section) — these tests cover only the NEW behaviour this phase
 * introduced.
 */

const PAPER_ID = "11111111-1111-1111-1111-111111111111";
const CENTRE_ID = "22222222-2222-2222-2222-222222222222";

function renderPaperDetail(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  seedAuthenticatedSession();
  return renderWithProviders(
    <Routes>
      <Route path="/admin/papers/:paperId" element={<PaperDetailPage />} />
    </Routes>,
    { route: `/admin/papers/${PAPER_ID}` },
  );
}

const metadataResponse = jsonResponse(200, {
  paper_id: PAPER_ID,
  subject: "Sample Subject",
  status: "released",
  sha256_hash: "a".repeat(64),
  release_timestamp: "2026-01-01T00:00:00Z",
  created_at: "2025-12-01T00:00:00Z",
  lock_status: "released",
});

const statusResponse = jsonResponse(200, {
  paper_id: PAPER_ID,
  lock_status: "released",
  last_integrity_check_result: null,
});

const meResponse = jsonResponse(200, { username: "admin1", role: "Admin" });

// Phase 6H: the page also requests GET /papers/{id}/schedule-history. The mock router matches by
// URL substring, so this route must precede "/schedule" and "/papers/{id}" in each route table.
const emptyHistoryResponse = jsonResponse(200, { items: [], total: 0, page: 1, page_size: 100 });

describe("PaperDetailPage — Phase 6F revoke authorization", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the revoke section once the paper loads", async () => {
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () => emptyHistoryResponse,
      "/status": () => statusResponse,
      [`/papers/${PAPER_ID}`]: () => metadataResponse,
    });
    renderPaperDetail(fetchMock);

    expect(
      await screen.findByRole("heading", { name: /revoke an examination centre's authorization/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revoke authorization/i })).toBeInTheDocument();
  });

  it("shows a validation error and does not call the API when the centre ID is empty", async () => {
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () => emptyHistoryResponse,
      "/status": () => statusResponse,
      [`/papers/${PAPER_ID}`]: () => metadataResponse,
    });
    renderPaperDetail(fetchMock);

    await screen.findByRole("button", { name: /revoke authorization/i });
    const callsBefore = fetchMock.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: /revoke authorization/i }));

    expect(await screen.findByText(/enter the examination centre's id/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBe(callsBefore); // no new request fired
  });

  it("shows a success message on a successful revoke and clears the input", async () => {
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () => emptyHistoryResponse,
      "/status": () => statusResponse,
      "/revoke": () =>
        jsonResponse(200, {
          authorization_id: "33333333-3333-3333-3333-333333333333",
          paper_id: PAPER_ID,
          centre_id: CENTRE_ID,
          authorized_at: "2025-12-01T00:00:00Z",
        }),
      [`/papers/${PAPER_ID}`]: () => metadataResponse,
    });
    renderPaperDetail(fetchMock);

    const input = await screen.findByLabelText(/examination centre id/i);
    await userEvent.type(input, CENTRE_ID);
    await userEvent.click(screen.getByRole("button", { name: /revoke authorization/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/authorization for this paper has been revoked/i);
    await waitFor(() => expect(input).toHaveValue(""));

    // The success message alone is not proof the backend was actually
    // asked to revoke anything — assert the real request was made,
    // with the right method, path, and body.
    const revokeCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/revoke"));
    expect(revokeCall).toBeDefined();
    const [revokeUrl, revokeInit] = revokeCall as [string, RequestInit];
    expect(String(revokeUrl)).toContain(`/papers/${PAPER_ID}/revoke`);
    expect(revokeInit.method).toBe("POST");
    expect(JSON.parse(String(revokeInit.body))).toEqual({ centre_id: CENTRE_ID });
  });

  it("displays the backend's error message when revoke fails", async () => {
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () => emptyHistoryResponse,
      "/status": () => statusResponse,
      "/revoke": () =>
        jsonResponse(400, {
          error: { message: "This centre is not currently authorized for this paper.", status_code: 400 },
        }),
      [`/papers/${PAPER_ID}`]: () => metadataResponse,
    });
    renderPaperDetail(fetchMock);

    const input = await screen.findByLabelText(/examination centre id/i);
    await userEvent.type(input, CENTRE_ID);
    await userEvent.click(screen.getByRole("button", { name: /revoke authorization/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This centre is not currently authorized for this paper.",
    );
  });
});


describe("PaperDetailPage — Phase 6G release scheduling", () => {
  const lockedStatus = jsonResponse(200, {
    paper_id: PAPER_ID,
    status: "registered",
    release_timestamp: "2099-01-01T00:00:00Z",
    lock_status: "locked",
  });

  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows the server-reported Locked state and the reschedule form for a locked paper", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => emptyHistoryResponse,
        "/status": () => lockedStatus,
        [`/papers/${PAPER_ID}`]: () => metadataResponse,
      }),
    );

    expect(await screen.findByRole("button", { name: /reschedule release/i })).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeInTheDocument();
  });

  it("hides the form and explains why for an already released paper", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => emptyHistoryResponse,
        "/status": () => statusResponse, // lock_status: "released"
        [`/papers/${PAPER_ID}`]: () => metadataResponse,
      }),
    );

    expect(await screen.findByText(/already been released, so its release time can no longer be changed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reschedule release/i })).not.toBeInTheDocument();
    expect(screen.getByText("Released")).toBeInTheDocument();
  });

  it("validates an empty value without sending a request", async () => {
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () => emptyHistoryResponse,
      "/status": () => lockedStatus,
      [`/papers/${PAPER_ID}`]: () => metadataResponse,
    });
    renderPaperDetail(fetchMock);

    await userEvent.click(await screen.findByRole("button", { name: /reschedule release/i }));

    expect(await screen.findByText(/choose the new release date and time/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "PATCH")).toBe(false);
  });

  it("sends an explicit UTC instant and shows the server's response", async () => {
    const local = "2099-06-15T10:30";
    const expectedIso = new Date(local).toISOString();
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () => emptyHistoryResponse,
      "/status": () => lockedStatus,
      "/schedule": () =>
        jsonResponse(200, { paper_id: PAPER_ID, release_timestamp: expectedIso, lock_status: "locked" }),
      [`/papers/${PAPER_ID}`]: () => metadataResponse,
    });
    renderPaperDetail(fetchMock);

    const input = await screen.findByLabelText(/new release time/i);
    fireEvent.change(input, { target: { value: local } });
    await userEvent.click(screen.getByRole("button", { name: /reschedule release/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/release time updated/i);

    const call = fetchMock.mock.calls.find(
      ([url, i]) => String(url).includes("/schedule") && (i as RequestInit)?.method === "PATCH",
    );
    expect(call).toBeDefined();
    const [url, init] = call as [string, RequestInit];
    expect(String(url)).toContain(`/papers/${PAPER_ID}/schedule`);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ release_timestamp: expectedIso });
    expect(expectedIso.endsWith("Z")).toBe(true); // explicit timezone, never a naive string
  });

  it("displays the backend's message when the reschedule is rejected", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => emptyHistoryResponse,
        "/status": () => lockedStatus,
        "/schedule": () =>
          jsonResponse(400, { error: { message: "The new release time must be in the future.", status_code: 400 } }),
        [`/papers/${PAPER_ID}`]: () => metadataResponse,
      }),
    );

    const input = await screen.findByLabelText(/new release time/i);
    fireEvent.change(input, { target: { value: "2000-01-01T00:00" } });
    await userEvent.click(screen.getByRole("button", { name: /reschedule release/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The new release time must be in the future.");
  });
});


describe("PaperDetailPage — Phase 6H lifecycle labels and schedule history", () => {
  const lockedStatus = () =>
    jsonResponse(200, {
      paper_id: PAPER_ID,
      status: "registered",
      release_timestamp: "2099-01-01T00:00:00Z",
      lock_status: "locked",
    });
  const lockedMetadata = () =>
    jsonResponse(200, {
      paper_id: PAPER_ID,
      subject: "Sample Subject",
      status: "registered",
      sha256_hash: "a".repeat(64),
      release_timestamp: "2099-01-01T00:00:00Z",
      created_at: "2025-12-01T00:00:00Z",
      lock_status: "locked",
    });
  const historyEntry = (id: string, who: string, prev: string, next: string) => ({
    history_id: id,
    paper_id: PAPER_ID,
    action: "RESCHEDULED",
    previous_release_timestamp: prev,
    new_release_timestamp: next,
    actor_id: "33333333-3333-3333-3333-333333333333",
    actor_username: who,
    created_at: "2026-02-01T10:00:00Z",
  });

  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("separates registration status from the server-reported release state", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => emptyHistoryResponse,
        "/status": lockedStatus,
        [`/papers/${PAPER_ID}`]: lockedMetadata,
      }),
    );

    expect(await screen.findByText("Registration status")).toBeInTheDocument();
    expect(screen.getByText("registered")).toBeInTheDocument();
    expect(screen.getByText("Release state")).toBeInTheDocument();
    expect(screen.getByText("Locked")).toBeInTheDocument();
    // The wording must not suggest that anyone has opened the paper.
    expect(screen.getByText(/not that any centre has opened the paper/i)).toBeInTheDocument();
  });

  it("follows the server, not the browser clock, when they disagree", async () => {
    // Release time is long past by the browser's clock, yet the server says the paper is locked.
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => emptyHistoryResponse,
        "/status": () =>
          jsonResponse(200, {
            paper_id: PAPER_ID,
            status: "registered",
            release_timestamp: "2000-01-01T00:00:00Z",
            lock_status: "locked",
          }),
        [`/papers/${PAPER_ID}`]: () =>
          jsonResponse(200, {
            paper_id: PAPER_ID,
            subject: "Sample Subject",
            status: "registered",
            sha256_hash: "a".repeat(64),
            release_timestamp: "2000-01-01T00:00:00Z",
            created_at: "2025-12-01T00:00:00Z",
            lock_status: "locked",
          }),
      }),
    );

    expect(await screen.findByText("Locked")).toBeInTheDocument();
    expect(screen.queryByText("Released")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reschedule release/i })).toBeInTheDocument();
  });

  it("shows an empty state when the release time was never changed", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => emptyHistoryResponse,
        "/status": lockedStatus,
        [`/papers/${PAPER_ID}`]: lockedMetadata,
      }),
    );
    expect(await screen.findByText(/release time has not been changed since this paper was registered/i)).toBeInTheDocument();
  });

  it("lists previous and new release times, who changed them, in the order the server returned", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () =>
          jsonResponse(200, {
            items: [
              historyEntry("h1", "first.admin", "2099-01-01T00:00:00Z", "2099-02-01T00:00:00Z"),
              historyEntry("h2", "second.admin", "2099-02-01T00:00:00Z", "2099-03-01T00:00:00Z"),
            ],
            total: 2,
            page: 1,
            page_size: 100,
          }),
        "/status": lockedStatus,
        [`/papers/${PAPER_ID}`]: lockedMetadata,
      }),
    );

    const heading = await screen.findByRole("heading", { name: /release schedule history/i });
    const table = await screen.findByRole("table");
    expect(heading).toBeInTheDocument();
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("first.admin");
    expect(rows[1]).toHaveTextContent("second.admin");
    // Four timestamp-ish cells per row: changed-at, previous, new (plus the actor cell).
    expect(rows[0].querySelectorAll("td")).toHaveLength(4);
    expect(rows[0].querySelectorAll("td")[2].getAttribute("title")).toBe("2099-01-01T00:00:00Z");
    expect(rows[0].querySelectorAll("td")[3].getAttribute("title")).toBe("2099-02-01T00:00:00Z");
  });

  it("shows a history error without hiding the paper or its controls", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () =>
          jsonResponse(500, { error: { message: "History unavailable right now.", status_code: 500 } }),
        "/status": lockedStatus,
        [`/papers/${PAPER_ID}`]: lockedMetadata,
      }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Registration status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reschedule release/i })).toBeInTheDocument();
  });

  it("tolerates a malformed history payload", async () => {
    renderPaperDetail(
      routedFetchMock({
        "/auth/me": () => meResponse,
        "/schedule-history": () => jsonResponse(200, { unexpected: true }),
        "/status": lockedStatus,
        [`/papers/${PAPER_ID}`]: lockedMetadata,
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/unable to load the release schedule history/i);
    expect(screen.getByRole("button", { name: /reschedule release/i })).toBeInTheDocument();
  });

  it("re-fetches the history from the server after a successful reschedule (no stale or optimistic rows)", async () => {
    const local = "2099-06-15T10:30";
    const expectedIso = new Date(local).toISOString();
    let rescheduled = false;
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
      "/schedule-history": () =>
        jsonResponse(200, {
          items: rescheduled ? [historyEntry("h1", "admin1", "2099-01-01T00:00:00Z", expectedIso)] : [],
          total: rescheduled ? 1 : 0,
          page: 1,
          page_size: 100,
        }),
      "/schedule": () => {
        rescheduled = true;
        return jsonResponse(200, { paper_id: PAPER_ID, release_timestamp: expectedIso, lock_status: "locked" });
      },
      "/status": lockedStatus,
      [`/papers/${PAPER_ID}`]: lockedMetadata,
    });
    renderPaperDetail(fetchMock);

    await screen.findByText(/release time has not been changed/i);
    fireEvent.change(await screen.findByLabelText(/new release time/i), { target: { value: local } });
    await userEvent.click(screen.getByRole("button", { name: /reschedule release/i }));

    const table = await screen.findByRole("table");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(screen.queryByText(/release time has not been changed/i)).not.toBeInTheDocument();
    const historyCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes("/schedule-history"));
    expect(historyCalls.length).toBeGreaterThanOrEqual(2); // initial load + refetch after the PATCH
  });
});
