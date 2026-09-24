/**
 * types.ts — request/response shapes for the Gateway Adapter's
 * internal HTTP API. Mirrors the chaincode's own parameter/return
 * shapes (see blockchain/chaincode/paper-ledger/src/paperContract.ts)
 * as closely as possible so this layer stays a thin translation, not
 * a second place where business rules could drift from the chaincode.
 */

export interface RegisterPaperRequest {
  paper_id: string;
  sha256_hash: string;
  registered_at: string;
  admin_id: string;
  subject: string;
  encryption_algorithm: string;
}

export interface RegisterPaperResponse {
  success: true;
  transaction_id: string;
  paper_id: string;
}

export interface PaperRecord {
  docType: "paper";
  paperId: string;
  sha256Hash: string;
  registeredAt: string;
  adminId: string;
  subject: string;
  encryptionAlgorithm: string;
}

export interface VerifyHashRequest {
  paper_id: string;
  candidate_hash: string;
}

export interface VerifyHashResponse {
  paper_id: string;
  match: boolean;
}

export interface AuditEventRequest {
  event_id: string;
  event_type: string;
  actor_id: string;
  paper_id: string;
  outcome: string;
  timestamp: string;
}

export interface AuditEventResponse {
  success: true;
  transaction_id: string;
  event_id: string;
}

export interface ErrorResponse {
  error: {
    message: string;
    /** Short machine-readable category, e.g. "NOT_FOUND", "DUPLICATE", "VALIDATION_ERROR", "FABRIC_UNAVAILABLE". */
    type: string;
  };
}

export interface HealthResponse {
  status: "ok";
  service: "fabric-gateway-adapter";
  fabric_connected: boolean;
}
