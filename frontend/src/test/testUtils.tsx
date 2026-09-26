import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
