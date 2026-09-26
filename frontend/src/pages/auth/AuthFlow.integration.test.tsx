import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAuth } from "../../hooks/useAuth";
import { LoginPage } from "./LoginPage";
import { OTPPage } from "./OTPPage";
import { renderWithProviders, jsonResponse } from "../../test/testUtils";

/**
 * Small harness that mirrors the relevant slice of AppRoutes (login ->
 * otp -> authenticated) without pulling in the full router tree, so
 * this test exercises the real AuthContext + real page components
 * together.
 */
function AuthFlowHarness() {
  const { status, user, logout } = useAuth();
  if (status === "authenticated" && user) {
    return (
      <div>
        <p>Authenticated as {user.username}</p>
        <button onClick={() => void logout()}>Log out</button>
      </div>
    );
  }
  if (status === "otp_required") {
    return <OTPPage />;
  }
  return <LoginPage />;
}

function renderHarness() {
  return renderWithProviders(<AuthFlowHarness />);
}

describe("full authentication flow", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("moves unauthenticated -> otp_required -> authenticated, then logout returns to unauthenticated", async () => {
    const fetchMock = vi
      .fn()
      // POST /auth/login
      .mockResolvedValueOnce(jsonResponse(200, { otp_required: true, pre_auth_token: "pre-token-abc" }))
      // POST /auth/otp/verify
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "jwt-xyz", token_type: "bearer", role: "Admin" }))
      // GET /auth/me
      .mockResolvedValueOnce(
        jsonResponse(200, { user_id: "u1", username: "admin1", role: "Admin", centre_id: null }),
      )
      // POST /auth/logout
      .mockResolvedValueOnce(jsonResponse(200, { detail: "Logged out." }));
    vi.stubGlobal("fetch", fetchMock);

    renderHarness();

    await userEvent.type(screen.getByLabelText(/username/i), "admin1");
    await userEvent.type(screen.getByLabelText(/password/i), "password123");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByLabelText(/one-time passcode/i)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/one-time passcode/i), "123456");
    await userEvent.click(screen.getByRole("button", { name: /verify/i }));

    expect(await screen.findByText(/authenticated as admin1/i)).toBeInTheDocument();
    expect(sessionStorage.getItem("qpaper_access_token")).toBe("jwt-xyz");

    await userEvent.click(screen.getByRole("button", { name: /log out/i }));

    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(sessionStorage.getItem("qpaper_access_token")).toBeNull();
  });
});
