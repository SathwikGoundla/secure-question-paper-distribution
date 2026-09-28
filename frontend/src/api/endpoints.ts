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
  PaperListResponse,
  PaperMetadataResponse,
  PaperRegisterResponse,
  PaperStatusResponse,
} from "../types/papers";
import type {
  CentreCreateRequest,
  CentreListResponse,
  CentreResponse,
  CentreUpdateRequest,
  DashboardSummaryResponse,
} from "../types/admin";
import type { AuditLogListResponse } from "../types/audit";
import type { SecurityEventListResponse } from "../types/monitoring";

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
 * GET /api/v1/papers — Phase 6C addition. Not a separately numbered
 * LLD API; see backend/app/api/v1/papers.py `list_papers` and
 * PROJECT_STATE.md's Phase 6C section for why it exists. Admin sees
 * every paper; Examination Centre sees only papers it is currently
 * authorized for.
 */
export function listPapers(params: { page?: number; pageSize?: number; status?: string } = {}): Promise<PaperListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.status) query.set("status", params.status);
  const qs = query.toString();
  return apiRequest<PaperListResponse>(`/papers${qs ? `?${qs}` : ""}`, { method: "GET" });
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
 * retrieve this specific paper.
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

// ---------------------------------------------------------------------------
// Phase 6C — real business logic. Every route below was a 501 stub as of
// Phase 6B; app/api/v1/admin.py and audit.py now implement real,
// RBAC-protected, database-backed behaviour (see PROJECT_STATE.md's
// Phase 6C section for the exact backend inspection performed).
// ---------------------------------------------------------------------------

/** GET /api/v1/admin/centres — Admin-only (LLD 7.3 list). */
export function listCentres(params: { page?: number; pageSize?: number } = {}): Promise<CentreListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  const qs = query.toString();
  return apiRequest<CentreListResponse>(`/admin/centres${qs ? `?${qs}` : ""}`, { method: "GET" });
}

/** GET /api/v1/admin/centres/{centre_id} — Admin-only. */
export function getCentre(centreId: string): Promise<CentreResponse> {
  return apiRequest<CentreResponse>(`/admin/centres/${centreId}`, { method: "GET" });
}

/** POST /api/v1/admin/centres — Admin-only (LLD API-11). */
export function createCentre(body: CentreCreateRequest): Promise<CentreResponse> {
  return apiRequest<CentreResponse>("/admin/centres", { method: "POST", body });
}

/** PATCH /api/v1/admin/centres/{centre_id} — Admin-only (LLD API-12). */
export function updateCentre(centreId: string, body: CentreUpdateRequest): Promise<CentreResponse> {
  return apiRequest<CentreResponse>(`/admin/centres/${centreId}`, { method: "PATCH", body });
}

/** GET /api/v1/admin/dashboard/summary — Admin-only (LLD API-13). Real, database-derived aggregates. */
export function getDashboardSummary(): Promise<DashboardSummaryResponse> {
  return apiRequest<DashboardSummaryResponse>("/admin/dashboard/summary", { method: "GET" });
}

/** GET /api/v1/audit/logs — Admin or Auditor (LLD API-09). */
export function getAuditLogs(
  params: {
    page?: number;
    pageSize?: number;
    paperId?: string;
    eventType?: string;
    outcome?: string;
  } = {},
): Promise<AuditLogListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.paperId) query.set("paper_id", params.paperId);
  if (params.eventType) query.set("event_type", params.eventType);
  if (params.outcome) query.set("outcome", params.outcome);
  const qs = query.toString();
  return apiRequest<AuditLogListResponse>(`/audit/logs${qs ? `?${qs}` : ""}`, { method: "GET" });
}

/** GET /api/v1/monitoring/security-events — Admin or Auditor (LLD API-10). */
export function getSecurityEvents(
  params: { page?: number; pageSize?: number; severity?: string; eventType?: string } = {},
): Promise<SecurityEventListResponse> {
  const query = new URLSearchParams();
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("page_size", String(params.pageSize));
  if (params.severity) query.set("severity", params.severity);
  if (params.eventType) query.set("event_type", params.eventType);
  const qs = query.toString();
  return apiRequest<SecurityEventListResponse>(`/monitoring/security-events${qs ? `?${qs}` : ""}`, {
    method: "GET",
  });
}

/**
 * GET /api/v1/admin/exam-security-events — LLD API-15 (Faculty-Review
 * Addition). Still a genuine 501 stub — out of Phase 6C's scope.
 */
export function getExamSecurityEvents(): Promise<NotImplementedResponse> {
  return apiRequest<NotImplementedResponse>("/admin/exam-security-events", { method: "GET" });
}
