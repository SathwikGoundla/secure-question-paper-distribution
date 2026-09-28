import { useEffect, useState } from "react";
import { getAuditLogs } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type { AuditEventResponse } from "../../../types/audit";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { EmptyState } from "../../../components/common/EmptyState";

/**
 * GET /api/v1/audit/logs (LLD API-09) is Admin-or-Auditor and, as of
 * Phase 6C, returns real persisted audit records
 * (backend/app/services/audit_service.list_audit_events) instead of a
 * 501 stub.
 */
export function AuditLogsPage() {
  const [items, setItems] = useState<AuditEventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAuditLogs({ pageSize: 50 })
      .then((data) => {
        if (!cancelled) setItems(data.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.userMessage : "Unable to load audit logs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="admin-page">
      <h1>Audit Logs</h1>
      {loading && <LoadingIndicator label="Loading audit logs…" />}
      {!loading && error && <ErrorBanner message={error} />}
      {!loading && !error && items.length === 0 && (
        <EmptyState message="No audit events recorded yet." />
      )}
      {!loading && !error && items.length > 0 && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Event Type</th>
              <th>Actor</th>
              <th>Paper ID</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {items.map((event) => (
              <tr key={event.event_id}>
                <td>{new Date(event.created_at).toLocaleString()}</td>
                <td>{event.event_type}</td>
                <td>{event.actor_username ?? "—"}</td>
                <td>{event.paper_id ?? "—"}</td>
                <td>
                  <span className="status-badge">{event.outcome}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
