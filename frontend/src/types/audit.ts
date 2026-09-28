/**
 * Types mirroring backend/app/schemas/audit.py exactly (Phase 6C).
 */

export interface AuditEventResponse {
  event_id: string;
  event_type: string;
  actor_id: string | null;
  actor_username: string | null;
  paper_id: string | null;
  outcome: string;
  ledger_tx_reference: string | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditEventResponse[];
  total: number;
  page: number;
  page_size: number;
}
