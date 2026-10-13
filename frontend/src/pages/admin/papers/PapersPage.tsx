import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listPapers, getPaperMetadata } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type { PaperListItemResponse } from "../../../types/papers";
import { useKnownPapers } from "../../../hooks/useKnownPapers";
import { Button } from "../../../components/common/Button";
import { Input } from "../../../components/common/Input";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { EmptyState } from "../../../components/common/EmptyState";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";

/**
 * GET /api/v1/papers (Phase 6C addition — see PROJECT_STATE.md) now
 * provides a real paper catalogue: every paper the current Admin (or,
 * for an Examination Centre, every paper it is currently authorized
 * for) can see. The "look up by ID" form is kept for the common case
 * of navigating straight to a specific paper's detail page.
 */
export function PapersPage() {
  const { remember } = useKnownPapers();
  const navigate = useNavigate();

  const [papers, setPapers] = useState<PaperListItemResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [paperId, setPaperId] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [isLookingUp, setIsLookingUp] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listPapers({ pageSize: 100 })
      .then((data) => {
        if (!cancelled) setPapers(data.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError ? err.userMessage : "Unable to load question papers.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleLookup(event: FormEvent) {
    event.preventDefault();
    setLookupError(null);

    const trimmed = paperId.trim();
    if (!trimmed) {
      setLookupError("Enter a paper ID to look up.");
      return;
    }

    setIsLookingUp(true);
    try {
      const metadata = await getPaperMetadata(trimmed);
      remember({
        paper_id: metadata.paper_id,
        subject: metadata.subject,
        status: metadata.status,
        created_at: metadata.created_at,
      });
      navigate(`/admin/papers/${metadata.paper_id}`);
    } catch (err) {
      setLookupError(err instanceof ApiError ? err.userMessage : "Unable to look up that paper.");
    } finally {
      setIsLookingUp(false);
    }
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <h1>Question Papers</h1>
        <Link to="/admin/papers/upload" className="btn btn-primary admin-header-btn">
          Register New Paper
        </Link>
      </div>

      <form className="lookup-form" onSubmit={handleLookup}>
        <Input
          id="paper-id-lookup"
          label="Look up a paper by ID"
          placeholder="e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6"
          value={paperId}
          onChange={(e) => setPaperId(e.target.value)}
        />
        <ErrorBanner message={lookupError} />
        <Button type="submit" isLoading={isLookingUp}>
          Look up
        </Button>
      </form>

      <h2 className="admin-section-heading">All question papers</h2>
      {loading && <LoadingIndicator label="Loading question papers…" />}
      {!loading && loadError && <ErrorBanner message={loadError} />}
      {!loading && !loadError && papers.length === 0 && (
        <EmptyState message="No question papers found. Register a paper or look one up by ID." />
      )}
      {!loading && !loadError && papers.length > 0 && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Paper ID</th>
              <th>Subject</th>
              <th>Registration status</th>
              <th>Release state</th>
              <th>Registered</th>
            </tr>
          </thead>
          <tbody>
            {papers.map((paper) => (
              <tr key={paper.paper_id}>
                <td>
                  <Link to={`/admin/papers/${paper.paper_id}`}>{paper.paper_id}</Link>
                </td>
                <td>{paper.subject}</td>
                <td>
                  <span className="status-badge">{paper.status}</span>
                </td>
                <td>
                  <span className="status-badge">{paper.lock_status === "released" ? "Released" : "Locked"}</span>
                </td>
                <td>{new Date(paper.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
