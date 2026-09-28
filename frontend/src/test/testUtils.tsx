import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../contexts/AuthContext";

/** Renders a component wrapped with the same providers App.tsx uses (minus BrowserRouter, using MemoryRouter for tests). */
export function renderWithProviders(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

/** Builds a minimal mock Response-like object for a JSON body. */
export function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

/**
 * Phase 6B test helper: seeds sessionStorage with a valid access token
 * so AuthProvider's initial-load effect calls GET /auth/me and lands
 * directly in the "authenticated" state, without re-running the full
 * login/OTP flow in every Admin Portal test. `fetchMock` should be a
 * `vi.fn()` that already knows how to answer `/auth/me` for the given
 * role (and any endpoint(s) under test) — this helper only seeds the
 * token.
 */
export function seedAuthenticatedSession(): void {
  sessionStorage.setItem("qpaper_access_token", "test-jwt");
}

/** Builds a fetch mock that dispatches by URL substring to a map of responses/handlers. */
export function routedFetchMock(
  routes: Record<string, () => Promise<Response> | Response>,
): ReturnType<typeof vi.fn> {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const matchKey = Object.keys(routes).find((key) => url.includes(key));
    if (!matchKey) {
      throw new Error(`routedFetchMock: no route registered for ${url}`);
    }
    return routes[matchKey]();
  });
}

/**
 * Phase 6D test helper: a Response-like object for a successful binary
 * PDF download (what GET /papers/{id}/retrieve returns), including the
 * `content-type` header the API client checks before accepting a body.
 */
export function pdfResponse(contentType = "application/pdf"): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? contentType : null) },
    blob: async () => new Blob(["%PDF-1.4 test"], { type: "application/pdf" }),
    json: async () => ({}),
  } as unknown as Response;
}
