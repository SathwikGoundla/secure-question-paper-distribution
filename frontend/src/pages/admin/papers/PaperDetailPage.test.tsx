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
});

const statusResponse = jsonResponse(200, {
  paper_id: PAPER_ID,
  lock_status: "released",
  last_integrity_check_result: null,
});

const meResponse = jsonResponse(200, { username: "admin1", role: "Admin" });

describe("PaperDetailPage — Phase 6F revoke authorization", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the revoke section once the paper loads", async () => {
    const fetchMock = routedFetchMock({
      "/auth/me": () => meResponse,
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

    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/schedule"));
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
