import { useEffect, useState } from "react";
import { getSecurityEvents } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { NotYetAvailableNotice } from "../../../components/admin/NotYetAvailableNotice";

/**
 * GET /api/v1/monitoring/security-events (LLD API-10,
 * backend/app/api/v1/audit.py) is a real, RBAC-protected route (Admin
 * or Auditor) but its business logic has not been implemented yet —
 * it currently returns HTTP 501. This page makes the real call and
 * surfaces the backend's own message, rather than fabricating
 * security events or building AI-based insider-threat detection
 * (explicitly out of scope).
 */
export function SecurityEventsPage() {
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSecurityEvents()
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 501) {
          setNotice(err.userMessage);
        } else if (err instanceof ApiError) {
          setError(err.userMessage);
        } else {
          setError("Unable to load security events.");
        }
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
      {!loading && notice && <NotYetAvailableNotice title="Security event monitoring" backendMessage={notice} />}
      {!loading && error && <ErrorBanner message={error} />}
    </div>
  );
}
