import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAuth } from "../../hooks/useAuth";
import { LoginPage } from "./LoginPage";
import { OTPPage } from "./OTPPage";
import { AppHeader } from "../../components/layout/AppHeader";
import { renderWithProviders, jsonResponse } from "../../test/testUtils";

/**
 * Phase 7B — signing in with a one-time recovery code instead of an authenticator code, through the
 * real AuthContext, LoginPage and OTPPage. The password step is unchanged; the recovery path
 * continues from the same pre-auth challenge.
 */
function Harness() {
  const { status, user } = useAuth();
  if (status === "authenticated" && user) {
    return (
      <div>
        <AppHeader />
        <p>Authenticated as {user.username}</p>
      </div>
    );
  }
  if (status === "otp_required") return <OTPPage />;
  return <LoginPage />;
}

const CODE = "ABCD-EFGH-JKMN-PQRS";
const ME = { user_id: "u1", username: "alice", role: "Auditor", centre_id: null };
const error = (status: number, message: string) => jsonResponse(status, { error: { message, status_code: status } });

async function signInToOtpStep() {
  await userEvent.type(screen.getByLabelText(/username/i), "alice");
  await userEvent.type(screen.getByLabelText(/password/i), "password123");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
  await screen.findByLabelText(/one-time passcode/i);
}

describe("recovery-code sign-in (Phase 7B)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("offers a recovery option, validates input locally, and signs in with the recovery endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { otp_required: true, pre_auth_token: "pre-1", second_factor: "totp" }))
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: "jwt-r", token_type: "bearer", role: "Auditor", recovery_codes_remaining: 9 }),
      )
      .mockResolvedValueOnce(jsonResponse(200, ME));
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<Harness />);
    await signInToOtpStep();

    await userEvent.click(screen.getByRole("button", { name: /use a recovery code/i }));
    expect(screen.getByRole("heading", { name: /use a recovery code/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/one-time passcode/i)).not.toBeInTheDocument();

    // Local validation: nothing is sent for an empty or obviously malformed value.
    await userEvent.click(screen.getByRole("button", { name: /sign in with recovery code/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/enter one of your recovery codes/i);
    await userEvent.type(screen.getByLabelText(/recovery code/i), "ABCD-EFGH");
    await userEvent.click(screen.getByRole("button", { name: /sign in with recovery code/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/16 letters and numbers/i);
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the password step so far

    await userEvent.clear(screen.getByLabelText(/recovery code/i));
    await userEvent.type(screen.getByLabelText(/recovery code/i), CODE);
    await userEvent.click(screen.getByRole("button", { name: /sign in with recovery code/i }));

    expect(await screen.findByText(/authenticated as alice/i)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/auth/recovery-code/verify");
    expect(JSON.parse(init.body)).toEqual({ pre_auth_token: "pre-1", recovery_code: CODE });
    expect(sessionStorage.getItem("qpaper_access_token")).toBe("jwt-r");
    // The user is told a recovery code was used and how many remain.
    expect(await screen.findByText(/signed in with a recovery code — 9 left/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /security/i })).toHaveAttribute("href", "/security");
    // The code itself is not kept anywhere.
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(CODE);
  });

  it("shows the backend's generic message for a used or wrong code and stays on the recovery step", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(200, { otp_required: true, pre_auth_token: "pre-1" }))
        .mockResolvedValueOnce(error(401, "Invalid or expired OTP.")),
    );
    renderWithProviders(<Harness />);
    await signInToOtpStep();
    await userEvent.click(screen.getByRole("button", { name: /use a recovery code/i }));
    await userEvent.type(screen.getByLabelText(/recovery code/i), CODE);
    await userEvent.click(screen.getByRole("button", { name: /sign in with recovery code/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or expired/i);
    expect(screen.getByRole("heading", { name: /use a recovery code/i })).toBeInTheDocument();
    expect(screen.getByText(/ask your administrator for a new enrollment code/i)).toBeInTheDocument();
    expect(sessionStorage.getItem("qpaper_access_token")).toBeNull();
  });

  it("can switch back to the authenticator code without losing the challenge", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { otp_required: true, pre_auth_token: "pre-1" }))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "jwt-t", token_type: "bearer", role: "Auditor" }))
      .mockResolvedValueOnce(jsonResponse(200, ME));
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<Harness />);
    await signInToOtpStep();
    await userEvent.click(screen.getByRole("button", { name: /use a recovery code/i }));
    await userEvent.click(screen.getByRole("button", { name: /back to authenticator code/i }));

    await userEvent.type(screen.getByLabelText(/one-time passcode/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /^verify$/i }));
    expect(await screen.findByText(/authenticated as alice/i)).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[1][0])).toContain("/auth/otp/verify");
    expect(screen.queryByText(/recovery code — /i)).not.toBeInTheDocument(); // no recovery banner for a normal sign-in
  });
});
