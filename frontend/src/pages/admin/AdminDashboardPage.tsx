import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { getDashboardSummary } from "../../api/endpoints";
import { ApiError } from "../../types/api";
import { LoadingIndicator } from "../../components/common/LoadingIndicator";
import { NotYetAvailableNotice } from "../../components/admin/NotYetAvailableNotice";
import { useKnownPapers } from "../../hooks/useKnownPapers";

/**
 * GET /api/v1/admin/dashboard/summary (LLD API-13) is Admin-only on
 * the backend (backend/app/api/v1/admin.py `require_role("Admin")`)
 * and is currently a 501 stub — no aggregate statistics exist yet.
 * Per the Phase 6B brief ("Do not add a new analytics backend... use
 * existing list endpoints only where appropriate"), and since no list
 * endpoint exists either (see PROJECT_STATE.md Section 17), this page
 * does not fabricate any chart or count. It makes the real call so an
 * Admin sees the backend's own status honestly, and otherwise offers
 * real navigation into the pages that do have working functionality.
 */
export function AdminDashboardPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "Admin";
  const { papers } = useKnownPapers();

  const [loading, setLoading] = useState(isAdmin);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDashboardSummary()
      .then(() => {
        // The endpoint currently never resolves successfully (it is a
        // 501 stub), but if a future backend phase implements it,
        // nothing here assumes a particular success shape yet.
        if (!cancelled) setNotice(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 501) {
          setNotice(err.userMessage);
        } else if (err instanceof ApiError) {
          setError(err.userMessage);
        } else {
          setError("Unable to load the dashboard summary.");
        }
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

      {isAdmin && loading && <LoadingIndicator label="Checking dashboard availability…" />}
      {isAdmin && !loading && notice && (
        <NotYetAvailableNotice title="Dashboard summary" backendMessage={notice} />
      )}
      {isAdmin && !loading && error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <section className="dashboard-grid">
        {isAdmin && (
          <div className="dashboard-card">
            <h2>Question Papers</h2>
            <p>{papers.length} paper(s) registered or looked up this session.</p>
            <Link to="/admin/papers">Go to Question Papers →</Link>
          </div>
        )}
        {isAdmin && (
          <div className="dashboard-card">
            <h2>Exam Centres</h2>
            <p>Examination-centre management is not yet available on the backend.</p>
            <Link to="/admin/exam-centres">View details →</Link>
          </div>
        )}
        <div className="dashboard-card">
          <h2>Audit Logs</h2>
          <p>Backend audit-log retrieval is not yet available.</p>
          <Link to="/admin/audit-logs">View details →</Link>
        </div>
        <div className="dashboard-card">
          <h2>Security Events</h2>
          <p>Backend security-event monitoring is not yet available.</p>
          <Link to="/admin/security-events">View details →</Link>
        </div>
      </section>
    </div>
  );
}
