import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  authorizeCentre,
  getPaperMetadata,
  getPaperScheduleHistory,
  getPaperStatus,
  reschedulePaperRelease,
  revokeCentre,
} from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type {
  PaperMetadataResponse,
  PaperScheduleHistoryItem,
  PaperStatusResponse,
} from "../../../types/papers";
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

  // Phase 6G: release rescheduling. The datetime-local value is the
  // admin's LOCAL wall-clock time; it is converted to an explicit UTC
  // instant before sending, because the backend requires a timezone.
  const [newRelease, setNewRelease] = useState("");
  const [rescheduleMessage, setRescheduleMessage] = useState<string | null>(null);
  const [rescheduleError, setRescheduleError] = useState<string | null>(null);
  const [isRescheduling, setIsRescheduling] = useState(false);

  // Phase 6H: release-schedule history (separate from the main page load, so
  // a history failure never hides the paper itself).
  const [history, setHistory] = useState<PaperScheduleHistoryItem[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadHistory = useCallback(() => {
    if (!paperId) return;
    setHistoryLoading(true);
    setHistoryError(null);
    getPaperScheduleHistory(paperId)
      .then((data) => {
        // Defensive: never trust the shape blindly.
        if (!data || !Array.isArray(data.items)) throw new Error("unexpected history response");
        setHistory(data.items);
      })
      .catch((err: unknown) => {
        setHistory(null);
        setHistoryError(
          err instanceof ApiError ? err.userMessage : "Unable to load the release schedule history.",
        );
      })
      .finally(() => setHistoryLoading(false));
  }, [paperId]);

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
    loadHistory();
  }, [load, loadHistory]);

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

  async function handleReschedule(event: FormEvent) {
    event.preventDefault();
    setRescheduleError(null);
    setRescheduleMessage(null);

    if (!paperId) return;
    if (!newRelease) {
      setRescheduleError("Choose the new release date and time.");
      return;
    }
    const chosen = new Date(newRelease);
    if (Number.isNaN(chosen.getTime())) {
      setRescheduleError("That date and time is not valid.");
      return;
    }

    setIsRescheduling(true);
    try {
      // No client-side "must be in the future" check on purpose: the
      // server decides (and its message is shown), the browser clock
      // is not a security control.
      const result = await reschedulePaperRelease(paperId, chosen.toISOString());
      setMetadata((prev) => (prev ? { ...prev, release_timestamp: result.release_timestamp } : prev));
      setStatusInfo((prev) =>
        prev
          ? { ...prev, release_timestamp: result.release_timestamp, lock_status: result.lock_status }
          : prev,
      );
      setRescheduleMessage(
        `Release time updated to ${new Date(result.release_timestamp).toLocaleString()}.`,
      );
      setNewRelease("");
      loadHistory(); // show the new entry; never patch history optimistically
    } catch (err) {
      setRescheduleError(err instanceof ApiError ? err.userMessage : "Unable to reschedule this paper.");
    } finally {
      setIsRescheduling(false);
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
        <dt>Registration status</dt>
        <dd>
          <span className="status-badge">{statusInfo?.status ?? metadata.status}</span>
          <span className="admin-page-note"> Whether the paper is registered in the system.</span>
        </dd>
        <dt>SHA-256 hash</dt>
        <dd className="mono">{metadata.sha256_hash}</dd>
        <dt>Release state</dt>
        <dd>
          <span className="status-badge">
            {(statusInfo?.lock_status ?? metadata.lock_status) === "released" ? "Released" : "Locked"}
          </span>
          <span className="admin-page-note">
            {" "}
            Decided by the server clock. Released means the scheduled time has been reached, not that
            any centre has opened the paper.
          </span>
        </dd>
        <dt>Scheduled release time</dt>
        <dd>{new Date(metadata.release_timestamp).toLocaleString()}</dd>
        <dt>Registered at</dt>
        <dd>{new Date(metadata.created_at).toLocaleString()}</dd>
      </dl>

      <h2 className="admin-section-heading">Release schedule</h2>
      {statusInfo?.lock_status === "released" ? (
        <p className="admin-page-note">
          This paper has already been released, so its release time can no longer be changed.
        </p>
      ) : (
        <>
          <p className="admin-page-note">
            Changes when this paper unlocks. The server enforces the lock; this form only updates the
            scheduled time, and the server rejects times that are not in the future.
          </p>
          <form className="lookup-form" onSubmit={handleReschedule}>
            <Input
              id="new-release"
              label="New release time (your local time)"
              type="datetime-local"
              value={newRelease}
              onChange={(e) => setNewRelease(e.target.value)}
              disabled={isRescheduling}
            />
            {rescheduleMessage && (
              <p className="success-banner" role="status">
                {rescheduleMessage}
              </p>
            )}
            <ErrorBanner message={rescheduleError} />
            <Button type="submit" isLoading={isRescheduling}>
              Reschedule Release
            </Button>
          </form>
        </>
      )}

      <h2 className="admin-section-heading">Release schedule history</h2>
      {historyLoading && (
        // Plain text, not LoadingIndicator: that component is role="status", which would collide
        // with the success banners on this page (also role="status") while history loads.
        <p className="admin-page-note" aria-busy="true">
          Loading schedule history…
        </p>
      )}
      {!historyLoading && historyError && <ErrorBanner message={historyError} />}
      {!historyLoading && !historyError && history !== null && history.length === 0 && (
        <p className="admin-page-note">The release time has not been changed since this paper was registered.</p>
      )}
      {!historyLoading && !historyError && history !== null && history.length > 0 && (
        <div className="table-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Changed at</th>
                <th>Changed by</th>
                <th>Previous release time</th>
                <th>New release time</th>
              </tr>
            </thead>
            <tbody>
              {history.map((entry) => (
                <tr key={entry.history_id}>
                  <td title={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</td>
                  <td>{entry.actor_username ?? entry.actor_id}</td>
                  <td title={entry.previous_release_timestamp}>
                    {new Date(entry.previous_release_timestamp).toLocaleString()}
                  </td>
                  <td title={entry.new_release_timestamp}>
                    {new Date(entry.new_release_timestamp).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
