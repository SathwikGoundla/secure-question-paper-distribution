import { useEffect, useState } from "react";
import { getSecurityEvents } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type { SecurityEventResponse } from "../../../types/monitoring";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { EmptyState } from "../../../components/common/EmptyState";

/**
 * GET /api/v1/monitoring/security-events (LLD API-10) is Admin-or-
 * Auditor and, as of Phase 6C, returns real persisted security events
 * (backend/app/services/audit_service.list_security_events) instead of
 * a 501 stub. No AI-based insider-threat detection is introduced here
 * — these are the same rule-based events the backend already records
 * (failed logins, hash mismatches, unauthorized/pre-release access).
 */
export function SecurityEventsPage() {
  const [items, setItems] = useState<SecurityEventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSecurityEvents({ pageSize: 50 })
      .then((data) => {
        if (!cancelled) setItems(data.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.userMessage : "Unable to load security events.");
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
      <h1>Security Events</h1>
      {loading && <LoadingIndicator label="Loading security events…" />}
      {!loading && error && <ErrorBanner message={error} />}
      {!loading && !error && items.length === 0 && (
        <EmptyState message="No security events recorded yet." />
      )}
      {!loading && !error && items.length > 0 && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Event Type</th>
              <th>Severity</th>
              <th>Actor</th>
              <th>Paper ID</th>
            </tr>
          </thead>
          <tbody>
            {items.map((event) => (
              <tr key={event.security_event_id}>
                <td>{new Date(event.created_at).toLocaleString()}</td>
                <td>{event.event_type}</td>
                <td>
                  <span className="status-badge">{event.severity}</span>
                </td>
                <td>{event.actor_username ?? "—"}</td>
                <td>{event.paper_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
