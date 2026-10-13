/**
 * Types mirroring the backend's actual paper-lifecycle schemas exactly
 * (backend/app/schemas/papers.py) and the RBAC-only 501 stub endpoints
 * (backend/app/api/v1/admin.py, audit.py, exam_session.py). Nothing
 * here is invented — every field name matches a Pydantic response
 * model the backend genuinely returns, or (for the stub endpoints) the
 * plain `{"detail": string}` body those routes return today.
 *
 * IMPORTANT — verified during Phase 6B inspection (see PROJECT_STATE.md
 * Section 17 for the full list): the backend does NOT currently expose
 * a "list all papers" endpoint. LLD API-05/API-08 are both
 * single-paper lookups by `paper_id` (GET /papers/{paper_id} and
 * GET /papers/{paper_id}/status). The Admin Portal's Question Papers
 * page is built around this real constraint rather than inventing a
 * list endpoint.
 */

/**
 * Release state computed by the BACKEND clock (Phase 6H): "released" once
 * the scheduled release time has been reached, otherwise "locked". It does
 * not mean any centre has opened the paper. Never derive this from the
 * browser clock.
 */
export type LockStatus = "locked" | "released";

/** POST /papers/register response body (PaperRegisterResponse). */
export interface PaperRegisterResponse {
  paper_id: string;
  subject: string;
  status: string;
  sha256_hash: string;
  encryption_algorithm: string;
  release_timestamp: string;
  created_at: string;
  ledger_tx_reference: string | null;
  /** Phase 6H: server-computed release state (see LockStatus). */
  lock_status: LockStatus;
}

/** GET /papers/{paper_id} response body (PaperMetadataResponse). */
export interface PaperMetadataResponse {
  paper_id: string;
  subject: string;
  /** Registration status (persisted by the backend). NOT a release or access indicator. */
  status: string;
  sha256_hash: string;
  release_timestamp: string;
  created_at: string;
  /** Phase 6H: server-computed release state (see LockStatus). */
  lock_status: LockStatus;
}

/** GET /papers/{paper_id}/status response body (PaperStatusResponse). */
export interface PaperStatusResponse {
  paper_id: string;
  status: string;
  release_timestamp: string;
  /**
   * Phase 6G: computed by the backend clock when the request is made.
   * Informational only — retrieval is still enforced server-side.
   */
  lock_status: LockStatus;
}

/** PATCH /papers/{paper_id}/schedule response body (PaperScheduleResponse). */
export interface PaperScheduleResponse {
  paper_id: string;
  release_timestamp: string;
  lock_status: LockStatus;
}

/**
 * Phase 6C addition — one row of GET /papers (list). Mirrors
 * backend/app/schemas/papers.py PaperListItemResponse exactly.
 */
export interface PaperListItemResponse {
  paper_id: string;
  subject: string;
  status: string;
  sha256_hash: string;
  release_timestamp: string;
  created_at: string;
  ledger_tx_reference: string | null;
  /** Phase 6H: server-computed release state (see LockStatus). */
  lock_status: LockStatus;
}

/** Phase 6C addition — GET /papers response envelope (paginated). */
export interface PaperListResponse {
  items: PaperListItemResponse[];
  total: number;
  page: number;
  page_size: number;
}

/** Phase 6H — one successful release-time change (PaperScheduleHistoryItem). */
export interface PaperScheduleHistoryItem {
  history_id: string;
  paper_id: string;
  action: string;
  previous_release_timestamp: string;
  new_release_timestamp: string;
  actor_id: string;
  actor_username: string | null;
  created_at: string;
}

/** Phase 6H — GET /papers/{paper_id}/schedule-history envelope (oldest first). */
export interface PaperScheduleHistoryResponse {
  items: PaperScheduleHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

/** POST /papers/{paper_id}/authorize request body (PaperAuthorizeRequest). */
export interface PaperAuthorizeRequest {
  centre_id: string;
}

/** POST /papers/{paper_id}/authorize response body (PaperAuthorizeResponse). */
export interface PaperAuthorizeResponse {
  authorization_id: string;
  paper_id: string;
  centre_id: string;
  authorized_at: string;
}

/**
 * The handful of admin/audit/monitoring routes that existed on the
 * backend only as RBAC-protected 501 "not implemented yet" stubs are
 * now implemented (Phase 6C) — see types/admin.ts, types/audit.ts,
 * types/monitoring.ts for their real response shapes. This type is
 * kept only for app/api/v1/admin.py's still-unimplemented
 * exam-security-events endpoint (LLD API-15, the Faculty-Review
 * Addition — genuinely out of Phase 6C's scope).
 */
export interface NotImplementedResponse {
  detail: string;
}
