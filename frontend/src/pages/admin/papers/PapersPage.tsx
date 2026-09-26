import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getPaperMetadata } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import { useKnownPapers } from "../../../hooks/useKnownPapers";
import { Button } from "../../../components/common/Button";
import { Input } from "../../../components/common/Input";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { EmptyState } from "../../../components/common/EmptyState";

/**
 * The backend has no "list all papers" endpoint (verified during
 * Phase 6B inspection — backend/app/api/v1/papers.py exposes only
 * register / get-by-id / authorize / retrieve / status, all keyed by
 * a specific paper_id). This page is honest about that limitation: it
 * shows papers the current admin has genuinely seen this session
 * (registered or looked up — real backend responses, cached
 * client-side by useKnownPapers) plus a "look up by ID" form backed
 * by the real GET /papers/{paper_id} endpoint.
 */
export function PapersPage() {
  const { papers, remember } = useKnownPapers();
  const navigate = useNavigate();

  const [paperId, setPaperId] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [isLookingUp, setIsLookingUp] = useState(false);

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

      <p className="admin-page-note">
        The backend does not currently provide a way to list every registered paper — only
        single-paper lookup by ID (GET /papers/{"{paper_id}"}). The list below shows papers you have
        registered or looked up in this session; it is not a complete catalogue.
      </p>

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

      <h2 className="admin-section-heading">Papers seen this session</h2>
      {papers.length === 0 ? (
        <EmptyState message="No question papers found. Register a paper or look one up by ID." />
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Paper ID</th>
              <th>Subject</th>
              <th>Status</th>
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
                <td>{new Date(paper.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
