import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecuritySettingsPage } from "./SecuritySettingsPage";
import { renderWithProviders, jsonResponse } from "../../test/testUtils";

/** Phase 7B — recovery-code management: counts only, one-time display, password step-up. */
const error = (status: number, message: string) => jsonResponse(status, { error: { message, status_code: status } });
const STATUS = (n: number, active = true) =>
  jsonResponse(200, { unused_count: n, generated_at: n ? "2026-11-01T10:00:00Z" : null, authenticator_active: active });
const CODES = ["AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-GGGG-HHHH", "JJJJ-KKKK-MMMM-NNNN"];

describe("SecuritySettingsPage (Phase 7B)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("shows counts only and explains when the authenticator is not set up", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(STATUS(0, false)));
    renderWithProviders(<SecuritySettingsPage />, { route: "/security" });
    expect(await screen.findByText(/set up an authenticator first/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
  });

  it("shows the unused count and a low-stock warning", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(STATUS(2)));
    renderWithProviders(<SecuritySettingsPage />, { route: "/security" });
    expect(await screen.findByTestId("recovery-summary")).toHaveTextContent("2");
    expect(screen.getByText(/running low/i)).toBeInTheDocument();
  });

  it("requires confirmation and the current password, then shows the codes exactly once", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(STATUS(10))
      .mockResolvedValueOnce(jsonResponse(200, { codes: CODES, count: 3, generated_at: "2026-11-02T10:00:00Z" }))
      .mockResolvedValueOnce(STATUS(3));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithProviders(<SecuritySettingsPage />, { route: "/security" });

    await user.click(await screen.findByRole("button", { name: /generate new recovery codes/i }));
    expect(screen.getByText(/invalidates your 10 unused recovery codes/i)).toBeInTheDocument();
    expect(screen.getByText(/shown/i)).toBeInTheDocument();

    // Password is required before anything is sent.
    await user.click(screen.getByRole("button", { name: /^generate codes$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/current password/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.type(screen.getByLabelText(/current password/i), "Pa55word!pa55");
    await user.click(screen.getByRole("button", { name: /^generate codes$/i }));

    const list = await screen.findByTestId("recovery-codes");
    CODES.forEach((c) => expect(list).toHaveTextContent(c));
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/auth/recovery-codes/regenerate");
    expect(JSON.parse(init.body)).toEqual({ password: "Pa55word!pa55" });

    // Codes live only in component state: not in storage, and gone once acknowledged.
    for (const c of CODES) {
      expect(JSON.stringify({ ...sessionStorage })).not.toContain(c);
      expect(JSON.stringify({ ...localStorage })).not.toContain(c);
    }
    await user.click(screen.getByRole("button", { name: /i have saved these codes/i }));
    expect(screen.queryByTestId("recovery-codes")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(CODES[0]);
    await waitFor(() => expect(screen.getByTestId("recovery-summary")).toHaveTextContent("3"));
  });

  it("shows the backend error for a wrong password and generates nothing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(STATUS(0)).mockResolvedValueOnce(error(401, "Incorrect password.")));
    const user = userEvent.setup();
    renderWithProviders(<SecuritySettingsPage />, { route: "/security" });
    await user.click(await screen.findByRole("button", { name: /generate recovery codes/i }));
    await user.type(screen.getByLabelText(/current password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /^generate codes$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/incorrect password/i);
    expect(screen.queryByTestId("recovery-codes")).not.toBeInTheDocument();
  });

  it("copies all codes with the clipboard when available", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(STATUS(0))
        .mockResolvedValueOnce(jsonResponse(200, { codes: CODES, count: 3, generated_at: "2026-11-02T10:00:00Z" }))
        .mockResolvedValueOnce(STATUS(3)),
    );
    const user = userEvent.setup();
    // userEvent.setup() installs its own clipboard stub; replace it with a spy AFTER setup.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderWithProviders(<SecuritySettingsPage />, { route: "/security" });
    await user.click(await screen.findByRole("button", { name: /generate recovery codes/i }));
    await user.type(screen.getByLabelText(/current password/i), "Pa55word!pa55");
    await user.click(screen.getByRole("button", { name: /^generate codes$/i }));
    await screen.findByTestId("recovery-codes");
    await user.click(screen.getByRole("button", { name: /copy all codes/i }));
    expect(writeText).toHaveBeenCalledWith(CODES.join("\n"));
    expect(await screen.findByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(error(500, "Server error.")));
    renderWithProviders(<SecuritySettingsPage />, { route: "/security" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
