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
}

/** GET /papers/{paper_id} response body (PaperMetadataResponse). */
export interface PaperMetadataResponse {
  paper_id: string;
  subject: string;
  status: string;
  sha256_hash: string;
  release_timestamp: string;
  created_at: string;
}

/** GET /papers/{paper_id}/status response body (PaperStatusResponse). */
export interface PaperStatusResponse {
  paper_id: string;
  status: string;
  release_timestamp: string;
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
 * The handful of admin/audit/monitoring routes that exist on the
 * backend today only as RBAC-protected 501 "not implemented yet"
 * stubs (backend/app/api/v1/admin.py, audit.py, exam_session.py).
 * Calling them succeeds in the sense that authentication + RBAC are
 * real and enforced; the business logic itself has not been built.
 */
export interface NotImplementedResponse {
  detail: string;
}
