import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EnrollPage } from "./EnrollPage";
import { renderWithProviders, jsonResponse } from "../../test/testUtils";

/**
 * Phase 7A — authenticator enrollment page. The backend owns every security decision; these tests
 * check the three-step UX, validation, error display, that the secret is only ever held in
 * component state (never storage) and is discarded afterwards, and that no auth header is sent.
 */

const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const START_OK = {
  enrollment_token: "enroll-token-abc",
  provisioning_uri: `otpauth://totp/QPaper%20System:alice?secret=${SECRET}&issuer=QPaper%20System`,
  secret: SECRET,
  qr_svg_data_uri: "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
  expires_in_seconds: 600,
};
const error = (status: number, message: string) => jsonResponse(status, { error: { message, status_code: status } });

async function fillStartForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/username/i), "alice");
  await user.type(screen.getByLabelText(/^password/i), "Pa55word!pa55");
  await user.type(screen.getByLabelText(/enrollment code/i), "ABCD-EFGH-JKMN");
}

describe("EnrollPage (Phase 7A)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("has labelled form controls and requires every field before any request is made", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithProviders(<EnrollPage />, { route: "/enroll" });

    expect(screen.getByRole("heading", { name: /set up authenticator/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/enrollment code/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/all required/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("walks through start -> scan -> confirm -> done and then discards the secret", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, START_OK))
      .mockResolvedValueOnce(jsonResponse(200, { enrolled: true }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithProviders(<EnrollPage />, { route: "/enroll" });

    await fillStartForm(user);
    await user.click(screen.getByRole("button", { name: /continue/i }));

    // Step 2: QR, one-time setup key, instructions, and the confirmation field.
    expect(await screen.findByAltText(/qr code/i)).toHaveAttribute("src", START_OK.qr_svg_data_uri);
    expect(screen.getByTestId("setup-key")).toHaveTextContent(SECRET);
    expect(screen.getByText(/shown only once/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^password/i)).not.toBeInTheDocument(); // password dropped from the UI

    // The secret is not persisted anywhere.
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET);

    await user.type(screen.getByLabelText(/6-digit code/i), "123456");
    await user.click(screen.getByRole("button", { name: /activate authenticator/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/authenticator is active/i);
    expect(screen.getByRole("link", { name: /go to sign in/i })).toHaveAttribute("href", "/login");
    expect(screen.queryByTestId("setup-key")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);

    // Requests: exact bodies, and no Authorization header (there is no session yet).
    const [startUrl, startInit] = fetchMock.mock.calls[0];
    expect(String(startUrl)).toContain("/auth/totp/enroll/start");
    expect(JSON.parse(startInit.body)).toEqual({
      username: "alice",
      password: "Pa55word!pa55",
      enrollment_code: "ABCD-EFGH-JKMN",
    });
    const [confirmUrl, confirmInit] = fetchMock.mock.calls[1];
    expect(String(confirmUrl)).toContain("/auth/totp/enroll/confirm");
    expect(JSON.parse(confirmInit.body)).toEqual({ enrollment_token: "enroll-token-abc", otp_code: "123456" });
    for (const [, init] of fetchMock.mock.calls) {
      expect(JSON.stringify(init.headers ?? {}).toLowerCase()).not.toContain("authorization");
    }
  });

  it("shows the backend's generic message when start fails and stays on the form", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(error(401, "Invalid username, password or enrollment code.")),
    );
    const user = userEvent.setup();
    renderWithProviders(<EnrollPage />, { route: "/enroll" });
    await fillStartForm(user);
    await user.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid username, password or enrollment code/i);
    expect(screen.getByLabelText(/enrollment code/i)).toBeInTheDocument();
    expect(screen.queryByAltText(/qr code/i)).not.toBeInTheDocument();
  });

  it("validates the 6-digit code locally and shows a server rejection without leaving the scan step", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, START_OK))
      .mockResolvedValueOnce(error(401, "Invalid or expired code. Please try again."));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWithProviders(<EnrollPage />, { route: "/enroll" });
    await fillStartForm(user);
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByAltText(/qr code/i);

    await user.type(screen.getByLabelText(/6-digit code/i), "12ab");
    await user.click(screen.getByRole("button", { name: /activate authenticator/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/6-digit code/i);
    expect(fetchMock).toHaveBeenCalledTimes(1); // nothing was sent for a malformed code

    await user.clear(screen.getByLabelText(/6-digit code/i));
    await user.type(screen.getByLabelText(/6-digit code/i), "654321");
    await user.click(screen.getByRole("button", { name: /activate authenticator/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/invalid or expired code/i));
    expect(screen.getByAltText(/qr code/i)).toBeInTheDocument(); // still on the scan step
  });

  it("'Start over' discards the secret and returns to the first step", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(200, START_OK)));
    const user = userEvent.setup();
    renderWithProviders(<EnrollPage />, { route: "/enroll" });
    await fillStartForm(user);
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByTestId("setup-key");

    await user.click(screen.getByRole("button", { name: /start over/i }));
    expect(screen.getByLabelText(/enrollment code/i)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("shows a generic message when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const user = userEvent.setup();
    renderWithProviders(<EnrollPage />, { route: "/enroll" });
    await fillStartForm(user);
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
