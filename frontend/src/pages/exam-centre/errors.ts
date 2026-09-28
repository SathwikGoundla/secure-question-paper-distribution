import { ApiError } from "../../types/api";

/**
 * Phase 6D — maps a failed API call to fixed, user-safe wording.
 *
 * The backend remains authoritative: this file only DESCRIBES the
 * backend's decision, it never makes one. Backend messages are used
 * only where they are known to be safe (see the cases below); several
 * 5xx messages from the backend mention internal configuration and are
 * deliberately NOT rendered — a fixed message is shown instead.
 *
 * 401 is not handled here: the API client's unauthorized handler
 * (AuthContext) clears the session and redirects to login.
 */
export type ExamCentreErrorKind =
  | "locked"
  | "unauthorized"
  | "integrity"
  | "not_found"
  | "unavailable"
  | "rate_limited"
  | "session"
  | "other";

export interface DescribedError {
  kind: ExamCentreErrorKind;
  message: string;
}

/**
 * The backend uses HTTP 403 for BOTH "not authorized for this paper"
 * and "not yet released" (paper_service.retrieve_paper); only the
 * message text distinguishes them. This substring match is a
 * presentation-only mapping — a wrong guess can only change which
 * explanatory sentence is shown, never whether a paper is released.
 */
const NOT_YET_AVAILABLE_MARKER = "not yet available";

export function describeRetrievalError(err: unknown): DescribedError {
  if (!(err instanceof ApiError)) {
    return { kind: "other", message: "Unable to complete the request. Please try again." };
  }

  switch (err.status) {
    case 401:
      return { kind: "session", message: "Your session has expired. Please log in again." };
    case 403:
      if (err.userMessage.toLowerCase().includes(NOT_YET_AVAILABLE_MARKER)) {
        return {
          kind: "locked",
          message: "Question paper is locked until the scheduled release time.",
        };
      }
      return { kind: "unauthorized", message: "You are not authorized to access this question paper." };
    case 409:
      return {
        kind: "integrity",
        message: "Security verification failed. The question paper was not released.",
      };
    case 404:
      return { kind: "not_found", message: "This question paper could not be found." };
    case 429:
      return { kind: "rate_limited", message: "Too many requests. Please wait a moment and try again." };
    case 400:
      return { kind: "other", message: "The request was not valid. Please go back and try again." };
    case 500:
    case 502:
    case 503:
      return {
        kind: "unavailable",
        message:
          "The question paper could not be released because a required service is temporarily unavailable. Please try again shortly.",
      };
    default:
      // null status = network failure / timeout; the client's own
      // messages for those are already safe and user-facing.
      return {
        kind: "other",
        message: err.status === null ? err.userMessage : "Unable to complete the request. Please try again.",
      };
  }
}

/** Same mapping, but for metadata/list loads, where 409 and "locked" cannot occur. */
export function describeLoadError(err: unknown): string {
  const described = describeRetrievalError(err);
  if (described.kind === "locked") {
    return "You are not authorized to access this question paper.";
  }
  return described.message;
}
