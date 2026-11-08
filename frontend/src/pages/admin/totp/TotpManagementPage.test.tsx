import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TotpManagementPage } from "./TotpManagementPage";
import { AppRoutes } from "../../../routes/AppRoutes";
import { renderWithProviders, jsonResponse, routedFetchMock, seedAuthenticatedSession } from "../../../test/testUtils";

/** Phase 7B — Admin authenticator-enrollment management page and its access control. */
const error = (status: number, message: string) => jsonResponse(status, { error: { message, status_code: status } });
const user = (over: Record<string, unknown>) => ({
  user_id: `id-${over.username}`,
  role: "Examination Centre",
  centre_name: "Centre One",
  totp_status: "not_enrolled",
  confirmed_at: null,
  code_issued_at: null,
  code_expires_at: null,
  is_self: false,
  ...over,
});
const LIST = {
  items: [
    user({ username: "admin1", role: "Admin", centre_name: null, totp_status: "active", is_self: true }),
    user({ username: "centre_active", totp_status: "active" }),
    user({ username: "centre_new", totp_status: "not_enrolled" }),
    user({ username: "centre_issued", totp_status: "code_issued", code_expires_at: "2099-01-01T00:00:00Z" }),
    user({ username: "centre_progress", totp_status: "enrollment_in_progress" }),
    user({ username: "centre_expired", totp_status: "code_expired" }),
    user({ username: "centre_locked", totp_status: "needs_new_code" }),
  ],
  total: 7,
  page: 1,
  page_size: 25,
};

describe("TotpManagementPage (Phase 7B)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("lists every enrollment state with readable labels and disables the caller's own row", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(200, LIST)));
    renderWithProviders(<TotpManagementPage />, { route: "/admin/totp" });

    const row = async (name: string) => (await screen.findByText(name)).closest("tr") as HTMLElement;
    expect(within(await row("centre_active")).getByText("Active")).toBeInTheDocument();
    expect(within(await row("centre_new")).getByText("Not enrolled")).toBeInTheDocument();
    expect(within(await row("centre_issued")).getByText("Code issued")).toBeInTheDocument();
    expect(within(await row("centre_progress")).getByText("Enrollment in progress")).toBeInTheDocument();
    expect(within(await row("centre_expired")).getByText("Code expired")).toBeInTheDocument();
    expect(within(await row("centre_locked")).getByText("Needs a new code")).toBeInTheDocument();

    const self = await row("admin1");
    expect(within(self).getByText("you")).toBeInTheDocument();
    expect(within(self).getByRole("button")).toBeDisabled();
    // Nothing secret is rendered: only state.
    expect(document.body.textContent).not.toMatch(/secret|recovery code|\$2b\$/i);
  });

  it("issues a code only after confirmation, shows it once, and can copy and hide it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, LIST))
      .mockResolvedValueOnce(jsonResponse(201, { username: "centre_new", enrollment_code: "ABCD-EFGH-JKMN", expires_at: "2099-01-02T00:00:00Z" }))
      .mockResolvedValueOnce(jsonResponse(200, LIST));
    vi.stubGlobal("fetch", fetchMock);
    const u = userEvent.setup();
    // userEvent.setup() installs its own clipboard stub; replace it with a spy AFTER setup.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderWithProviders(<TotpManagementPage />, { route: "/admin/totp" });

    const row = (await screen.findByText("centre_new")).closest("tr") as HTMLElement;
    await u.click(within(row).getByRole("button", { name: /issue enrollment code for centre_new/i }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/issue a new one-time enrollment code for centre_new/i);
    expect(fetchMock).toHaveBeenCalledTimes(1); // nothing issued before confirming

    await u.click(within(dialog).getByRole("button", { name: /^issue code$/i }));
    expect(await screen.findByTestId("issued-code")).toHaveTextContent("ABCD-EFGH-JKMN");
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/admin/totp/enrollment-codes");
    expect(JSON.parse(init.body)).toEqual({ username: "centre_new" });
    expect(screen.getByText(/shown only once/i)).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: /copy code/i }));
    expect(writeText).toHaveBeenCalledWith("ABCD-EFGH-JKMN");

    await u.click(screen.getByRole("button", { name: /hide code/i }));
    expect(screen.queryByTestId("issued-code")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("ABCD-EFGH-JKMN");
  });

  it("warns that reissuing for an ACTIVE user removes their authenticator and recovery codes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(200, LIST)));
    const u = userEvent.setup();
    renderWithProviders(<TotpManagementPage />, { route: "/admin/totp" });
    const row = (await screen.findByText("centre_active")).closest("tr") as HTMLElement;
    await u.click(within(row).getByRole("button", { name: /reissue enrollment code for centre_active/i }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/remove their current authenticator and recovery codes and sign them out/i);
    await u.click(within(dialog).getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows the backend error when issuing fails and issues nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(200, LIST)).mockResolvedValueOnce(error(404, "The requested resource was not found.")),
    );
    const u = userEvent.setup();
    renderWithProviders(<TotpManagementPage />, { route: "/admin/totp" });
    const row = (await screen.findByText("centre_new")).closest("tr") as HTMLElement;
    await u.click(within(row).getByRole("button", { name: /issue enrollment code/i }));
    await u.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: /^issue code$/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
    expect(screen.queryByTestId("issued-code")).not.toBeInTheDocument();
  });

  it("filters by username through the API and supports an empty result", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, LIST))
      .mockResolvedValueOnce(jsonResponse(200, { items: [], total: 0, page: 1, page_size: 25 }));
    vi.stubGlobal("fetch", fetchMock);
    const u = userEvent.setup();
    renderWithProviders(<TotpManagementPage />, { route: "/admin/totp" });
    await screen.findByText("centre_new");
    await u.type(screen.getByLabelText(/filter by username/i), "zzz");
    await u.click(screen.getByRole("button", { name: /^filter$/i }));
    expect(await screen.findByText(/no users match/i)).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[1][0])).toContain("q=zzz");
  });

  it("shows a load error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(error(500, "Server error.")));
    renderWithProviders(<TotpManagementPage />, { route: "/admin/totp" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("is reachable by an Admin but a centre user is redirected away (route guard)", async () => {
    seedAuthenticatedSession();
    // Admin
    vi.stubGlobal(
      "fetch",
      routedFetchMock({
        "/auth/me": () => jsonResponse(200, { user_id: "a", username: "admin1", role: "Admin", centre_id: null }),
        "/admin/totp/users": () => jsonResponse(200, LIST),
      }),
    );
    const first = renderWithProviders(<AppRoutes />, { route: "/admin/totp" });
    expect(await screen.findByRole("heading", { name: /authenticator enrollment/i })).toBeInTheDocument();
    first.unmount();

    // Examination Centre: never reaches the page, and the admin API is never called
    const fetchMock = routedFetchMock({
      "/auth/me": () => jsonResponse(200, { user_id: "c", username: "centre1", role: "Examination Centre", centre_id: "cid" }),
      "/admin/totp/users": () => jsonResponse(200, LIST),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<AppRoutes />, { route: "/admin/totp" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: /authenticator enrollment/i })).not.toBeInTheDocument());
    const urls = (fetchMock as unknown as { mock: { calls: [unknown][] } }).mock.calls.map((c) => String(c[0]));
    expect(urls.some((x) => x.includes("/admin/totp/users"))).toBe(false);
  });
});
