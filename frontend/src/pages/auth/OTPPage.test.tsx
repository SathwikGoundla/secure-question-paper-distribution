import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen } from "@testing-library/react";
import { OTPPage } from "./OTPPage";
import { renderWithProviders } from "../../test/testUtils";

describe("OTPPage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("redirects to /login when there is no in-progress OTP step (unauthenticated status)", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithProviders(<OTPPage />);
    // With status "unauthenticated" OTPPage renders a <Navigate>, so its
    // own heading must not be present.
    expect(screen.queryByRole("heading", { name: /enter verification code/i })).not.toBeInTheDocument();
  });

});
