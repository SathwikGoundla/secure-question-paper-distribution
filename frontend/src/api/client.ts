import { ApiError, type BackendErrorBody } from "../types/api";

/**
 * Base URL of the FastAPI backend's versioned API. Configurable via
 * VITE_API_BASE_URL (see .env.example) — never hardcoded elsewhere in
 * the source tree.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/** Request timeout for a single API call. */
const REQUEST_TIMEOUT_MS = 15000;

/**
 * User-facing fallback messages by HTTP status. Used only when the
 * backend's own `error.message` is unavailable (e.g. the response
 * body could not be parsed at all) — the backend already returns safe,
 * user-appropriate messages for its own AppExceptions
 * (backend/app/exceptions/handlers.py), so those are preferred whenever
 * present. This map exists purely as a defensive fallback and never to
 * override a real backend message.
 */
const STATUS_FALLBACK_MESSAGES: Record<number, string> = {
  400: "The request could not be processed. Please check the submitted information and try again.",
  401: "Your session has expired or your credentials are invalid. Please log in again.",
  403: "You do not have permission to perform this action.",
  404: "The requested resource could not be found.",
  409: "The request could not be completed because of a conflict with the current state of the resource.",
  422: "The submitted information is invalid. Please review and try again.",
  429: "Too many requests. Please wait a moment and try again.",
  500: "An internal server error occurred. Please try again or contact the administrator.",
  502: "The server is temporarily unavailable. Please try again shortly.",
  503: "The service is temporarily unavailable. Please try again shortly.",
};

const GENERIC_FALLBACK_MESSAGE =
  "Unable to complete the request. Please try again or contact the administrator.";

const NETWORK_ERROR_MESSAGE =
  "Unable to reach the server. Please check your connection and try again.";

const TIMEOUT_ERROR_MESSAGE = "The request took too long to respond. Please try again.";

let authToken: string | null = null;

/**
 * Sets (or clears, with null) the bearer token attached to every
 * subsequent authenticated request. Called exclusively by
 * AuthContext — no other module should hold or mutate this token.
 */
export function setAuthToken(token: string | null): void {
  authToken = token;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Attach the current bearer token, if any. Defaults to true. */
  authenticated?: boolean;
}

/**
 * Phase 6B addition: the paper-registration endpoint
 * (POST /papers/register, backend/app/api/v1/papers.py) accepts
 * `multipart/form-data` (FastAPI `Form(...)` + `File(...)` parameters),
 * not JSON — the existing `apiRequest` only ever sends
 * `application/json`. Rather than duplicating request/timeout/error
 * handling, this is a thin sibling that reuses the same base URL,
 * timeout, auth-token, and error-extraction logic. The browser sets
 * the `Content-Type: multipart/form-data; boundary=...` header itself
 * when given a `FormData` body — it must never be set manually.
 */
export async function apiRequestMultipart<TResponse>(
  path: string,
  formData: FormData,
  options: { method?: "POST" | "PATCH" | "PUT" } = {},
): Promise<TResponse> {
  const { method = "POST" } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: formData,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(TIMEOUT_ERROR_MESSAGE, null);
    }
    throw new ApiError(NETWORK_ERROR_MESSAGE, null);
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const message = await extractErrorMessage(response);
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }
  return (await response.json()) as TResponse;
}

/**
 * Extracts a safe, user-facing message from a non-2xx response.
 * Falls back to a generic, non-leaking message if the body is not the
 * expected shape (e.g. a proxy/timeout error page, not JSON at all).
 */
async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as Partial<BackendErrorBody> & { detail?: unknown };
    if (body?.error?.message) {
      return body.error.message;
    }
    // Phase 6B addition: a small number of backend endpoints
    // (app/api/v1/admin.py, audit.py, exam_session.py) are still
    // intentional 501 stubs. They return a plain FastAPI dict body
    // `{"detail": "..."}` rather than the app's own AppException shape
    // (backend/app/exceptions/handlers.py), because they never raise
    // an AppException — they just `return {"detail": ...}` directly.
    // Surfacing that real backend message (instead of falling through
    // to a generic "unable to complete request" string) lets the Admin
    // Portal tell the user honestly that a feature is not yet
    // implemented on the backend, rather than implying a transient
    // failure. This is the only change made to this function.
    if (typeof body?.detail === "string" && body.detail.length > 0) {
      return body.detail;
    }
  } catch {
    // Response body was not valid JSON — fall through to the generic fallback.
  }
  return STATUS_FALLBACK_MESSAGES[response.status] ?? GENERIC_FALLBACK_MESSAGE;
}

/**
 * The single, centralized request function every API call in this
 * application goes through. No component should call `fetch()`
 * directly (see endpoints.ts for the typed functions built on this).
 */
export async function apiRequest<TResponse>(
  path: string,
  options: RequestOptions = {},
): Promise<TResponse> {
  const { method = "GET", body, authenticated = true } = options;

  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (authenticated && authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(TIMEOUT_ERROR_MESSAGE, null);
    }
    throw new ApiError(NETWORK_ERROR_MESSAGE, null);
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const message = await extractErrorMessage(response);
    throw new ApiError(message, response.status);
  }

  // 204 No Content or an empty body: nothing further to parse.
  if (response.status === 204) {
    return undefined as TResponse;
  }
  return (await response.json()) as TResponse;
}
