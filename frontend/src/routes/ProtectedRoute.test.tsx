import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../contexts/AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";
import { jsonResponse } from "../test/testUtils";

function TestApp({ initialPath = "/protected" }: { initialPath?: string }) {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<p>Login page</p>} />
          <Route
            path="/protected"
            element={
              <ProtectedRoute>
                <p>Secret content</p>
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("redirects an unauthenticated user to /login instead of rendering protected content", async () => {
    // No token in sessionStorage -> AuthProvider finishes initializing
    // as unauthenticated without ever calling fetch.
    vi.stubGlobal("fetch", vi.fn());
    render(<TestApp />);

    expect(await screen.findByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Secret content")).not.toBeInTheDocument();
  });

  it("renders protected content once a valid session is restored from storage", async () => {
    sessionStorage.setItem("qpaper_access_token", "stored-jwt");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(200, { user_id: "u1", username: "admin1", role: "Admin", centre_id: null }),
      ),
    );
    render(<TestApp />);

    expect(await screen.findByText("Secret content")).toBeInTheDocument();
  });
});
