/**
 * Types mirroring backend/app/schemas/monitoring.py exactly (Phase 6C).
 */

export interface SecurityEventResponse {
  security_event_id: string;
  event_type: string;
  actor_id: string | null;
  actor_username: string | null;
  paper_id: string | null;
  severity: string;
  created_at: string;
}

export interface SecurityEventListResponse {
  items: SecurityEventResponse[];
  total: number;
  page: number;
  page_size: number;
}
