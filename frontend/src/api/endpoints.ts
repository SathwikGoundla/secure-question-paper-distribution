/**
 * Typed functions for the backend endpoints consumed by the frontend.
 * Every path/method/shape below was verified directly against the
 * backend source (Phase 6A: auth; Phase 6B addition below: papers,
 * admin, audit, exam-session — see PROJECT_STATE.md Section 17 for
 * the exact Phase 6B inspection notes):
 *
 *   backend/app/api/v1/auth.py, papers.py, admin.py, audit.py, exam_session.py
 *   backend/app/schemas/auth.py, papers.py
 *
 * No endpoint here is invented.
 */
import { apiRequest, apiRequestMultipart } from "./client";
import type {
  CurrentUserResponse,
  LoginRequest,
  LoginResponse,
  OtpVerifyRequest,
  OtpVerifyResponse,
} from "../types/auth";
import type {
  NotImplementedResponse,
  PaperAuthorizeRequest,
  PaperAuthorizeResponse,
  PaperMetadataResponse,
  PaperRegisterResponse,
  PaperStatusResponse,
} from "../types/papers";

/** POST /api/v1/auth/login — first factor (username + password). */
export function login(payload: LoginRequest): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: payload,
    authenticated: false,
  });
}

/** POST /api/v1/auth/otp/verify — second factor (OTP), issues the session JWT. */
export function verifyOtp(payload: OtpVerifyRequest): Promise<OtpVerifyResponse> {
  return apiRequest<OtpVerifyResponse>("/auth/otp/verify", {
    method: "POST",
    body: payload,
    authenticated: false,
  });
}

/** POST /api/v1/auth/logout — revokes the current session. Requires a valid JWT. */
export function logout(): Promise<{ detail: string }> {
  return apiRequest<{ detail: string }>("/auth/logout", { method: "POST" });
}

/** GET /api/v1/auth/me — canonical current-user identity. Requires a valid JWT. */
export function getCurrentUser(): Promise<CurrentUserResponse> {
  return apiRequest<CurrentUserResponse>("/auth/me", { method: "GET" });
}

// ---------------------------------------------------------------------------
// Phase 6B additions — Admin Portal. Every function below was matched against
// the real backend route it calls; see PROJECT_STATE.md Section 17 for the
// exact file/line inspection notes performed before writing this file.
// ---------------------------------------------------------------------------

/**
 * POST /api/v1/papers/register — Admin-only (backend/app/api/v1/papers.py
 * `register_paper`, LLD API-04). Multipart request: `subject` (form
 * field), `release_timestamp` (form field, ISO datetime), `file`
 * (the PDF). The backend performs AES-256 encryption, SHA-256 hashing,
 * off-chain storage, and a best-effort Hyperledger Fabric registration
 * itself — the frontend only ever sends the original plaintext file.
 */
export function registerPaper(params: {
  subject: string;
  releaseTimestamp: string;
  file: File;
}): Promise<PaperRegisterResponse> {
  const formData = new FormData();
  formData.append("subject", params.subject);
  formData.append("release_timestamp", params.releaseTimestamp);
  formData.append("file", params.file);
  return apiRequestMultipart<PaperRegisterResponse>("/papers/register", formData);
}

/**
 * GET /api/v1/papers/{paper_id} — Admin (any paper) or Examination
 * Centre (only if authorized for this paper) (LLD API-05). Returns
 * non-sensitive metadata only — never the encrypted file, key material,
 * or plaintext.
 */
export function getPaperMetadata(paperId: string): Promise<PaperMetadataResponse> {
  return apiRequest<PaperMetadataResponse>(`/papers/${paperId}`, { method: "GET" });
}

/**
 * GET /api/v1/papers/{paper_id}/status — Admin or authorized
 * Examination Centre (LLD API-08). Read-only; the backend does not
 * generate an audit event for this call.
 */
export function getPaperStatus(paperId: string): Promise<PaperStatusResponse> {
  return apiRequest<PaperStatusResponse>(`/papers/${paperId}/status`, { method: "GET" });
}

/**
 * POST /api/v1/papers/{paper_id}/authorize — Admin-only (LLD API-06).
 * Grants a specific examination centre (by its UUID) permission to
 * retrieve this specific paper. The backend does not currently expose
 * any endpoint to list existing examination-centre records (see
 * `exam-centres` limitation, Section 8 of the Phase 6B prompt and
 * PROJECT_STATE.md Section 17), so the centre UUID must be entered
 * directly — this UI does not invent a centre picker backed by data
 * the backend cannot supply.
 */
export function authorizeCentre(
  paperId: string,
  body: PaperAuthorizeRequest,
): Promise<PaperAuthorizeResponse> {
  return apiRequest<PaperAuthorizeResponse>(`/papers/${paperId}/authorize`, {
    method: "POST",
    body,
  });
}

/**
 * The four endpoints below (backend/app/api/v1/admin.py, audit.py)
 * are real, RBAC-protected routes — authentication and role checks
 * are genuinely enforced — but their business logic has not been
 * implemented yet: every one of them returns HTTP 501 with a plain
 * `{"detail": "..."}` body (verified directly in the route source,
 * not assumed). They are still wrapped here, rather than skipped,
 * so the Admin Portal can make the real call, receive the real 501,
 * and surface the backend's own "not implemented yet" message via
 * the standard ApiError path instead of a page that silently pretends
 * the feature exists by faking a request.
 */

/** POST /api/v1/admin/centres — Admin-only. Currently a 501 stub. */
export function createCentre(): Promise<NotImplementedResponse> {
  return apiRequest<NotImplementedResponse>("/admin/centres", { method: "POST" });
}

/** GET /api/v1/admin/dashboard/summary — Admin-only. Currently a 501 stub. */
export function getDashboardSummary(): Promise<NotImplementedResponse> {
  return apiRequest<NotImplementedResponse>("/admin/dashboard/summary", { method: "GET" });
}

/** GET /api/v1/audit/logs — Admin or Auditor. Currently a 501 stub. */
export function getAuditLogs(): Promise<NotImplementedResponse> {
  return apiRequest<NotImplementedResponse>("/audit/logs", { method: "GET" });
}

/** GET /api/v1/monitoring/security-events — Admin or Auditor. Currently a 501 stub. */
export function getSecurityEvents(): Promise<NotImplementedResponse> {
  return apiRequest<NotImplementedResponse>("/monitoring/security-events", { method: "GET" });
}
