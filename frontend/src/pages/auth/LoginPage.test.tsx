import { describe, it, expect, beforeEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "./LoginPage";
import { renderWithProviders, jsonResponse } from "../../test/testUtils";

describe("LoginPage", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("renders the login form", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, {})));
    renderWithProviders(<LoginPage />);

    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("shows a validation error and does not call the API when fields are empty", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<LoginPage />);

    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/username and password/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disables the submit button while authenticating (loading state)", async () => {
    let resolveFetch: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(pending),
    );
    renderWithProviders(<LoginPage />);

    await userEvent.type(screen.getByLabelText(/username/i), "admin1");
    await userEvent.type(screen.getByLabelText(/password/i), "password123");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const button = screen.getByRole("button", { name: /please wait/i });
    expect(button).toBeDisabled();

    resolveFetch(jsonResponse(200, { otp_required: true, pre_auth_token: "pre-token" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /please wait/i })).not.toBeInTheDocument());
  });

  it("displays the backend's error message on invalid credentials", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(401, { error: { message: "Invalid username or password.", status_code: 401 } }),
      ),
    );
    renderWithProviders(<LoginPage />);

    await userEvent.type(screen.getByLabelText(/username/i), "admin1");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password.");
  });

  it("links to authenticator setup (Phase 7A)", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, {})));
    renderWithProviders(<LoginPage />);
    expect(screen.getByRole("link", { name: /set up authenticator/i })).toHaveAttribute("href", "/enroll");
  });

  it("shows enrollment guidance when the account has no authenticator yet (403)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(403, {
          error: {
            message:
              "Authenticator setup is required for this account. Ask your administrator for an enrollment code, then use 'Set up authenticator'.",
            status_code: 403,
          },
        }),
      ),
    );
    renderWithProviders(<LoginPage />);
    await userEvent.type(screen.getByLabelText(/username/i), "alice");
    await userEvent.type(screen.getByLabelText(/password/i), "Pa55word!pa55");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/authenticator setup is required/i);
  });
});
