/**
 * Types mirroring backend/app/schemas/admin.py exactly (Phase 6C).
 */

export interface CentreCreateRequest {
  centre_name: string;
}

export interface CentreUpdateRequest {
  centre_name?: string;
  is_active?: boolean;
}

export interface CentreResponse {
  centre_id: string;
  centre_name: string;
  is_active: boolean;
  created_at: string;
}

export interface CentreListResponse {
  items: CentreResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardSummaryResponse {
  total_papers: number;
  papers_by_status: Record<string, number>;
  total_exam_centres: number;
  active_exam_centres: number;
  total_paper_authorizations: number;
  total_audit_events: number;
  total_security_events: number;
  security_events_by_severity: Record<string, number>;
}
