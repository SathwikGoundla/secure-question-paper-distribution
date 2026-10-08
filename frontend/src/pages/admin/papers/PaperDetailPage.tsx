import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { authorizeCentre, getPaperMetadata, getPaperStatus, revokeCentre } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type { PaperMetadataResponse, PaperStatusResponse } from "../../../types/papers";
import { useKnownPapers } from "../../../hooks/useKnownPapers";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { Button } from "../../../components/common/Button";
import { Input } from "../../../components/common/Input";

/**
 * Combines GET /papers/{paper_id} (metadata, LLD API-05) and
 * GET /papers/{paper_id}/status (LLD API-08) — both real backend
 * endpoints — plus a small form for POST /papers/{paper_id}/authorize
 * (LLD API-06) and, since Phase 6F, its revoke counterpart
 * (POST /papers/{paper_id}/revoke). Deliberately does not expose the encryption key,
 * wrapped DEK, nonce, or any other secret — the backend's own response
 * schemas (backend/app/schemas/papers.py) already exclude them, and
 * this page renders only the fields those schemas actually return.
 */
export function PaperDetailPage() {
  const { paperId } = useParams<{ paperId: string }>();
  const { remember } = useKnownPapers();

  const [metadata, setMetadata] = useState<PaperMetadataResponse | null>(null);
  const [statusInfo, setStatusInfo] = useState<PaperStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [centreId, setCentreId] = useState("");
  const [authorizeMessage, setAuthorizeMessage] = useState<string | null>(null);
  const [authorizeError, setAuthorizeError] = useState<string | null>(null);
  const [isAuthorizing, setIsAuthorizing] = useState(false);

  // Phase 6F: shares the same centreId input above it — revoking the
  // centre an admin just looked up/authorized is the common case, and
  // reusing the field avoids a second, redundant "enter a UUID" box.
  const [revokeMessage, setRevokeMessage] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);

  const load = useCallback(() => {
    if (!paperId) return;
    setLoading(true);
    setError(null);
    Promise.all([getPaperMetadata(paperId), getPaperStatus(paperId)])
      .then(([meta, status]) => {
        setMetadata(meta);
        setStatusInfo(status);
        remember({
          paper_id: meta.paper_id,
          subject: meta.subject,
          status: meta.status,
          created_at: meta.created_at,
        });
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.userMessage : "Unable to load this paper.");
      })
      .finally(() => setLoading(false));
    // `remember` is stable (useCallback with empty deps in the hook).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAuthorize(event: FormEvent) {
    event.preventDefault();
    setAuthorizeError(null);
    setAuthorizeMessage(null);

    if (!paperId) return;
    const trimmedCentreId = centreId.trim();
    if (!trimmedCentreId) {
      setAuthorizeError("Enter the examination centre's ID (UUID).");
      return;
    }

    setIsAuthorizing(true);
    try {
      const result = await authorizeCentre(paperId, { centre_id: trimmedCentreId });
      setAuthorizeMessage(
        `Centre ${result.centre_id} authorized for this paper at ${new Date(result.authorized_at).toLocaleString()}.`,
      );
      setCentreId("");
    } catch (err) {
      setAuthorizeError(err instanceof ApiError ? err.userMessage : "Unable to authorize that centre.");
    } finally {
      setIsAuthorizing(false);
    }
  }

  async function handleRevoke(event: FormEvent) {
    event.preventDefault();
    setRevokeError(null);
    setRevokeMessage(null);

    if (!paperId) return;
    const trimmedCentreId = centreId.trim();
    if (!trimmedCentreId) {
      setRevokeError("Enter the examination centre's ID (UUID).");
      return;
    }

    setIsRevoking(true);
    try {
      const result = await revokeCentre(paperId, { centre_id: trimmedCentreId });
      setRevokeMessage(`Centre ${result.centre_id}'s authorization for this paper has been revoked.`);
      setCentreId("");
    } catch (err) {
      setRevokeError(err instanceof ApiError ? err.userMessage : "Unable to revoke that centre's authorization.");
    } finally {
      setIsRevoking(false);
    }
  }

  if (loading) return <LoadingIndicator label="Loading paper…" />;

  if (error) {
    return (
      <div className="admin-page">
        <Link to="/admin/papers">← Back to Question Papers</Link>
        <ErrorBanner message={error} />
      </div>
    );
  }

  if (!metadata) return null;

  return (
    <div className="admin-page">
      <Link to="/admin/papers">← Back to Question Papers</Link>
      <h1>{metadata.subject}</h1>

      <dl className="detail-list">
        <dt>Paper ID</dt>
        <dd>{metadata.paper_id}</dd>
        <dt>Status</dt>
        <dd>
          <span className="status-badge">{statusInfo?.status ?? metadata.status}</span>
        </dd>
        <dt>SHA-256 hash</dt>
        <dd className="mono">{metadata.sha256_hash}</dd>
        <dt>Scheduled release time</dt>
        <dd>{new Date(metadata.release_timestamp).toLocaleString()}</dd>
        <dt>Registered at</dt>
        <dd>{new Date(metadata.created_at).toLocaleString()}</dd>
      </dl>

      <h2 className="admin-section-heading">Authorize an examination centre</h2>
      <p className="admin-page-note">
        The backend does not currently expose a way to list registered examination centres (see the
        Exam Centres page), so the centre ID must be entered directly.
      </p>
      <form className="lookup-form" onSubmit={handleAuthorize}>
        <Input
          id="centre-id"
          label="Examination centre ID"
          value={centreId}
          onChange={(e) => setCentreId(e.target.value)}
          disabled={isAuthorizing}
        />
        {authorizeMessage && (
          <p className="success-banner" role="status">
            {authorizeMessage}
          </p>
        )}
        <ErrorBanner message={authorizeError} />
        <Button type="submit" isLoading={isAuthorizing}>
          Authorize Centre
        </Button>
      </form>

      <h2 className="admin-section-heading">Revoke an examination centre's authorization</h2>
      <p className="admin-page-note">
        Uses the centre ID entered above. Revoking takes effect immediately — the centre loses
        retrieval access, and the paper disappears from its paper list, right away.
      </p>
      <form className="lookup-form" onSubmit={handleRevoke}>
        {revokeMessage && (
          <p className="success-banner" role="status">
            {revokeMessage}
          </p>
        )}
        <ErrorBanner message={revokeError} />
        <Button type="submit" variant="secondary" isLoading={isRevoking}>
          Revoke Authorization
        </Button>
      </form>
    </div>
  );
}
