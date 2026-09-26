import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, jsonResponse, seedAuthenticatedSession, routedFetchMock } from "../../test/testUtils";
import { AppRoutes } from "../../routes/AppRoutes";

const ADMIN_ME = jsonResponse(200, { user_id: "u1", username: "admin1", role: "Admin", centre_id: null });
const AUDITOR_ME = jsonResponse(200, { user_id: "u2", username: "auditor1", role: "Auditor", centre_id: null });
const CENTRE_ME = jsonResponse(200, { user_id: "u3", username: "centre1", role: "Examination Centre", centre_id: "c1" });

describe("Admin Portal — access control and shell", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the Admin dashboard for an authenticated Admin", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => ADMIN_ME,
        "/admin/dashboard/summary": () => jsonResponse(501, { detail: "Not implemented yet." }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin" });

    expect(await screen.findByRole("heading", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByText(/admin1/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^question papers$/i })).toBeInTheDocument();
  });

  it("does not show the Question Papers / Exam Centres nav links to an Auditor", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": () => AUDITOR_ME }));
    renderWithProviders(<AppRoutes />, { route: "/admin" });

    await screen.findByRole("heading", { name: /dashboard/i });
    expect(screen.queryByRole("link", { name: /^question papers$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^exam centres$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /audit logs/i })).toBeInTheDocument();
  });

  it("redirects a non-admin role (Examination Centre) away from /admin/papers", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": () => CENTRE_ME }));
    renderWithProviders(<AppRoutes />, { route: "/admin/papers" });

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /question papers/i })).not.toBeInTheDocument(),
    );
  });

  it("redirects an unauthenticated user hitting /admin to /login", async () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithProviders(<AppRoutes />, { route: "/admin" });

    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });
});

describe("Admin Portal — Question Papers", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows the empty state when no papers have been seen this session", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": () => ADMIN_ME }));
    renderWithProviders(<AppRoutes />, { route: "/admin/papers" });

    expect(await screen.findByText(/no question papers found/i)).toBeInTheDocument();
  });

  it("looks up a paper by ID and navigates to its detail page", async () => {
    seedAuthenticatedSession();
    const metadata = {
      paper_id: "11111111-1111-1111-1111-111111111111",
      subject: "Data Structures",
      status: "registered",
      sha256_hash: "abc123",
      release_timestamp: "2026-09-01T09:00:00Z",
      created_at: "2026-08-01T09:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => ADMIN_ME,
        "/papers/11111111-1111-1111-1111-111111111111/status": () =>
          jsonResponse(200, { paper_id: metadata.paper_id, status: metadata.status, release_timestamp: metadata.release_timestamp }),
        "/papers/11111111-1111-1111-1111-111111111111": () => jsonResponse(200, metadata),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin/papers" });

    await screen.findByLabelText(/look up a paper by id/i);
    await userEvent.type(screen.getByLabelText(/look up a paper by id/i), metadata.paper_id);
    await userEvent.click(screen.getByRole("button", { name: /^look up$/i }));

    expect(await screen.findByRole("heading", { name: /data structures/i })).toBeInTheDocument();
    expect(screen.getByText(/abc123/)).toBeInTheDocument();
  });

  it("shows a not-found error for an unknown paper ID", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => ADMIN_ME,
        "/papers/does-not-exist": () =>
          jsonResponse(404, { error: { message: "The requested resource could not be found.", status_code: 404 } }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin/papers" });

    await userEvent.type(await screen.findByLabelText(/look up a paper by id/i), "does-not-exist");
    await userEvent.click(screen.getByRole("button", { name: /^look up$/i }));

    expect(await screen.findByText(/could not be found/i)).toBeInTheDocument();
  });
});

describe("Admin Portal — Paper Upload", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the upload form", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": () => ADMIN_ME }));
    renderWithProviders(<AppRoutes />, { route: "/admin/papers/upload" });

    expect(await screen.findByLabelText(/subject/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/scheduled release/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /register paper/i })).toBeInTheDocument();
  });

  it("shows a validation error when required fields are missing", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": () => ADMIN_ME }));
    renderWithProviders(<AppRoutes />, { route: "/admin/papers/upload" });

    await userEvent.click(await screen.findByRole("button", { name: /register paper/i }));
    expect(await screen.findByText(/are all required/i)).toBeInTheDocument();
  });

  it("shows an authentication-error message on a 401 response", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => ADMIN_ME,
        "/papers/register": () =>
          jsonResponse(401, { error: { message: "Your session has expired.", status_code: 401 } }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin/papers/upload" });

    await userEvent.type(await screen.findByLabelText(/subject/i), "Operating Systems");
    const dtInput = screen.getByLabelText(/scheduled release/i);
    await userEvent.type(dtInput, "2026-12-01T09:00");
    const fileInput = screen.getByLabelText(/question paper file/i) as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "paper.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);

    await userEvent.click(screen.getByRole("button", { name: /register paper/i }));
    expect(await screen.findByText(/session has expired/i)).toBeInTheDocument();
  });
});

describe("Admin Portal — Exam Centres / Audit Logs / Security Events", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("documents the Exam Centres backend limitation without a fake form", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal("fetch", routedFetchMock({ "/auth/me": () => ADMIN_ME }));
    renderWithProviders(<AppRoutes />, { route: "/admin/exam-centres" });

    expect(await screen.findByText(/not yet available/i)).toBeInTheDocument();
  });

  it("surfaces the backend's real 501 message on the Audit Logs page", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => ADMIN_ME,
        "/audit/logs": () =>
          jsonResponse(501, { detail: "Not implemented yet — planned for the audit/monitoring implementation phase." }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin/audit-logs" });

    expect(
      await screen.findByText(/planned for the audit\/monitoring implementation phase/i),
    ).toBeInTheDocument();
  });

  it("shows a generic error banner on the Security Events page for a non-501 failure", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => ADMIN_ME,
        "/monitoring/security-events": () =>
          jsonResponse(500, { error: { message: "An internal server error occurred.", status_code: 500 } }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin/security-events" });

    expect(await screen.findByText(/internal server error/i)).toBeInTheDocument();
  });

  it("Auditor can reach Audit Logs and Security Events", async () => {
    seedAuthenticatedSession();
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => AUDITOR_ME,
        "/audit/logs": () => jsonResponse(501, { detail: "Not implemented yet." }),
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/admin/audit-logs" });

    expect(await screen.findByRole("heading", { name: /audit logs/i })).toBeInTheDocument();
  });
});
