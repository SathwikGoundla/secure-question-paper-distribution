import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen } from "@testing-library/react";
import { Routes, Route } from "react-router-dom";
import { PapersPage } from "./PapersPage";
import { renderWithProviders, jsonResponse, routedFetchMock, seedAuthenticatedSession } from "../../../test/testUtils";

/**
 * Phase 6H — the admin paper list shows registration status and the
 * server-computed release state as two separate columns.
 */
describe("PapersPage — Phase 6H release state column", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows registration status and the server's lock_status separately, ignoring the browser clock", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => jsonResponse(200, { username: "admin1", role: "Admin" }),
        "/papers?": () =>
          jsonResponse(200, {
            items: [
              {
                paper_id: "p-locked",
                subject: "Contradictory timestamp, server says locked",
                status: "registered",
                sha256_hash: "a".repeat(64),
                release_timestamp: "2000-01-01T00:00:00Z", // past by any browser clock
                created_at: "2025-12-01T00:00:00Z",
                ledger_tx_reference: null,
                lock_status: "locked",
              },
              {
                paper_id: "p-released",
                subject: "Contradictory timestamp, server says released",
                status: "registered",
                sha256_hash: "b".repeat(64),
                release_timestamp: "2099-01-01T00:00:00Z", // future by any browser clock
                created_at: "2025-12-02T00:00:00Z",
                ledger_tx_reference: null,
                lock_status: "released",
              },
            ],
            total: 2,
            page: 1,
            page_size: 100,
          }),
      }),
    );
    seedAuthenticatedSession();
    renderWithProviders(
      <Routes>
        <Route path="/admin/papers" element={<PapersPage />} />
      </Routes>,
      { route: "/admin/papers" },
    );

    await screen.findByText(/server says locked/i);
    expect(screen.getByRole("columnheader", { name: "Registration status" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Release state" })).toBeInTheDocument();

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("registered");
    expect(rows[0]).toHaveTextContent("Locked");
    expect(rows[1]).toHaveTextContent("registered");
    expect(rows[1]).toHaveTextContent("Released");
  });
});
