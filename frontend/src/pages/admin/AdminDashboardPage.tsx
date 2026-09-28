import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { getDashboardSummary } from "../../api/endpoints";
import { ApiError } from "../../types/api";
import type { DashboardSummaryResponse } from "../../types/admin";
import { LoadingIndicator } from "../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../components/common/ErrorBanner";

/**
 * GET /api/v1/admin/dashboard/summary (LLD API-13) is Admin-only and,
 * as of Phase 6C, returns real database-derived aggregates
 * (backend/app/services/dashboard_service.py) instead of a 501 stub.
 * Every number below is exactly what the backend returned — nothing
 * is computed or estimated client-side.
 */
export function AdminDashboardPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "Admin";

  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [loading, setLoading] = useState(isAdmin);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDashboardSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.userMessage : "Unable to load the dashboard summary.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  return (
    <div className="admin-page">
      <h1>Dashboard</h1>
      <p className="admin-page-subtitle">
        Signed in as <strong>{user?.username}</strong> ({user?.role})
      </p>

      {isAdmin && loading && <LoadingIndicator label="Loading dashboard summary…" />}
      {isAdmin && !loading && error && <ErrorBanner message={error} />}

      <section className="dashboard-grid">
        {isAdmin && summary && (
          <>
            <div className="dashboard-card">
              <h2>Question Papers</h2>
              <p className="dashboard-metric">{summary.total_papers}</p>
              <p>
                {Object.entries(summary.papers_by_status)
                  .map(([status, count]) => `${count} ${status}`)
                  .join(", ") || "No papers registered yet."}
              </p>
              <Link to="/admin/papers">Go to Question Papers →</Link>
            </div>
            <div className="dashboard-card">
              <h2>Exam Centres</h2>
              <p className="dashboard-metric">{summary.total_exam_centres}</p>
              <p>{summary.active_exam_centres} active</p>
              <Link to="/admin/exam-centres">View details →</Link>
            </div>
            <div className="dashboard-card">
              <h2>Audit Logs</h2>
              <p className="dashboard-metric">{summary.total_audit_events}</p>
              <p>{summary.total_paper_authorizations} paper authorizations recorded</p>
              <Link to="/admin/audit-logs">View details →</Link>
            </div>
            <div className="dashboard-card">
              <h2>Security Events</h2>
              <p className="dashboard-metric">{summary.total_security_events}</p>
              <p>
                {Object.entries(summary.security_events_by_severity)
                  .map(([severity, count]) => `${count} ${severity}`)
                  .join(", ") || "No security events recorded."}
              </p>
              <Link to="/admin/security-events">View details →</Link>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
