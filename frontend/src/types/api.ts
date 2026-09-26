/**
 * Shared API types.
 *
 * The error shape here matches the backend's actual, single, central
 * error handler exactly (backend/app/exceptions/handlers.py
 * `_error_body`):
 *
 *   { "error": { "message": string, "status_code": number } }
 *
 * This shape is used for both expected `AppException`s (401, 403,
 * 404, 409, etc.) and the generic 500 fallback. No other error shape
 * is invented here.
 */
export interface BackendErrorBody {
  error: {
    message: string;
    status_code: number;
  };
}

/**
 * Normalized error thrown by the API client for any non-2xx response,
 * or for a network/timeout failure. Components should catch this type
 * and display `userMessage` — never a raw stack trace or backend
 * internal detail.
 */
export class ApiError extends Error {
  readonly status: number | null;
  readonly userMessage: string;

  constructor(userMessage: string, status: number | null) {
    super(userMessage);
    this.name = "ApiError";
    this.status = status;
    this.userMessage = userMessage;
  }
}
