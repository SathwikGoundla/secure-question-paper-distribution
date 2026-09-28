import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { useNow } from "../../hooks/useNow";
import { listPapers } from "../../api/endpoints";
import type { PaperListItemResponse } from "../../types/papers";
import { LoadingIndicator } from "../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../components/common/ErrorBanner";
import { EmptyState } from "../../components/common/EmptyState";
import { describeLoadError } from "./errors";

const PAGE_SIZE = 100; // backend maximum for GET /papers

/**
 * Examination Centre dashboard: real data from GET /api/v1/papers, which
 * for this role returns ONLY papers the centre is currently authorized
 * for (backend/app/services/paper_service.list_papers).
 *
 * "Authorized papers" is the backend's own total. The backend paper
 * `status` never changes to "released" (it stays "registered"), so a
 * locked/released split cannot come from the backend. The split shown
 * here compares each backend-supplied scheduled release time with this
 * device's clock, is labelled as informational, and is shown only when
 * every authorized paper was fetched. It never gates any action — the
 * server decides at retrieval time.
 */
export function ExamCentreDashboardPage() {
  const { user } = useAuth();
  const now = useNow(30_000);

  const [papers, setPapers] = useState<PaperListItemResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPapers({ pageSize: PAGE_SIZE })
      .then((data) => {
        if (cancelled) return;
        setPapers(data.items);
        setTotal(data.total);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeLoadError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const haveAll = papers.length === total;
  const reached = papers.filter((p) => new Date(p.release_timestamp).getTime() <= now).length;
  const scheduled = papers.length - reached;

  return (
    <div className="admin-page">
      <h1>Examination Centre Portal</h1>
      <p className="admin-page-subtitle">
        Signed in as <strong>{user?.username}</strong>
        {user?.centreId ? (
          <>
            {" "}
            · Centre ID <span className="mono">{user.centreId}</span>
          </>
        ) : null}
      </p>

      {loading && <LoadingIndicator label="Loading your authorized papers…" />}
      {!loading && error && <ErrorBanner message={error} />}

      {!loading && !error && (
        <>
          <section className="dashboard-grid" aria-label="Summary">
            <div className="dashboard-card">
              <h2>Authorized papers</h2>
              <p className="dashboard-metric">{total}</p>
              <p>Papers this centre is currently authorized to retrieve.</p>
            </div>
            {haveAll && total > 0 && (
              <>
                <div className="dashboard-card">
                  <h2>Release time reached</h2>
                  <p className="dashboard-metric">{reached}</p>
                  <p>Scheduled time has passed on this device. The server decides at retrieval.</p>
                </div>
                <div className="dashboard-card">
                  <h2>Scheduled / locked</h2>
                  <p className="dashboard-metric">{scheduled}</p>
                  <p>Scheduled release time is still in the future on this device.</p>
                </div>
              </>
            )}
          </section>

          <h2 className="admin-section-heading">Authorized question papers</h2>
          {papers.length === 0 ? (
            <EmptyState message="No question papers have been authorized for this centre yet." />
          ) : (
            <div className="table-scroll">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Subject</th>
                    <th>Paper ID</th>
                    <th>Scheduled release</th>
                    <th>Status</th>
                    <th>Authorization</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {papers.map((paper) => (
                    <tr key={paper.paper_id}>
                      <td>{paper.subject}</td>
                      <td className="mono">{paper.paper_id}</td>
                      <td>{new Date(paper.release_timestamp).toLocaleString()}</td>
                      <td>
                        <span className="status-badge">{paper.status}</span>
                      </td>
                      <td>
                        <span className="status-badge status-ok">Authorized</span>
                      </td>
                      <td>
                        <Link to={`/exam-centre/papers/${paper.paper_id}`}>View details</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
