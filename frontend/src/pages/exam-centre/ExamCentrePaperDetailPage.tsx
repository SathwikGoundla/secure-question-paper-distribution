import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getPaperMetadata, getPaperStatus, retrievePaper } from "../../api/endpoints";
import type { PaperMetadataResponse, PaperStatusResponse } from "../../types/papers";
import { useNow, formatRemaining } from "../../hooks/useNow";
import { useReleasedPaperFile } from "../../hooks/useReleasedPaperFile";
import { LoadingIndicator } from "../../components/common/LoadingIndicator";
import { ErrorBanner } from "../../components/common/ErrorBanner";
import { Button } from "../../components/common/Button";
import { describeLoadError, describeRetrievalError, type DescribedError } from "./errors";

/** After a failed retrieval the button pauses briefly so a centre cannot hammer the server. */
const RETRY_COOLDOWN_MS = 10_000;

function safeFileName(subject: string): string {
  const cleaned = subject.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return `question-paper-${cleaned || "paper"}.pdf`;
}

/**
 * Detail + retrieval for ONE authorized paper.
 *
 * Every decision (authorization, time-lock, AES-256-GCM, SHA-256,
 * blockchain verification, audit logging) is made by the backend inside
 * GET /papers/{id}/retrieve. This page only calls it and renders the
 * result. The countdown is visual and never blocks or permits access.
 */
export function ExamCentrePaperDetailPage() {
  const { paperId } = useParams<{ paperId: string }>();
  const now = useNow(1000);
  const { objectUrl, hold, discard } = useReleasedPaperFile();

  const [metadata, setMetadata] = useState<PaperMetadataResponse | null>(null);
  const [statusInfo, setStatusInfo] = useState<PaperStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [isRetrieving, setIsRetrieving] = useState(false);
  const [retrievalError, setRetrievalError] = useState<DescribedError | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState(0);

  useEffect(() => {
    if (!paperId) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([getPaperMetadata(paperId), getPaperStatus(paperId)])
      .then(([meta, status]) => {
        if (cancelled) return;
        setMetadata(meta);
        setStatusInfo(status);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(describeLoadError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [paperId]);

  const handleRetrieve = useCallback(async () => {
    if (!paperId) return;
    setRetrievalError(null);
    discard();
    setIsRetrieving(true);
    try {
      const blob = await retrievePaper(paperId);
      hold(blob);
    } catch (err) {
      setRetrievalError(describeRetrievalError(err));
      setCooldownUntil(Date.now() + RETRY_COOLDOWN_MS);
    } finally {
      setIsRetrieving(false);
    }
  }, [paperId, hold, discard]);

  if (loading) return <LoadingIndicator label="Loading paper…" />;

  if (loadError || !metadata) {
    return (
      <div className="admin-page">
        <Link to="/exam-centre">← Back to My Papers</Link>
        <ErrorBanner message={loadError ?? "Unable to load this paper."} />
      </div>
    );
  }

  const releaseAt = new Date(statusInfo?.release_timestamp ?? metadata.release_timestamp);
  const msUntilRelease = releaseAt.getTime() - now;
  const inCooldown = cooldownUntil > now;
  const cooldownSeconds = Math.ceil((cooldownUntil - now) / 1000);

  return (
    <div className="admin-page">
      <Link to="/exam-centre">← Back to My Papers</Link>
      <h1>{metadata.subject}</h1>

      <dl className="detail-list">
        <dt>Paper ID</dt>
        <dd className="mono">{metadata.paper_id}</dd>
        <dt>Status</dt>
        <dd>
          <span className="status-badge">{statusInfo?.status ?? metadata.status}</span>
        </dd>
        <dt>Authorization</dt>
        <dd>
          <span className="status-badge status-ok">Authorized for this centre</span>
        </dd>
        <dt>Scheduled release time</dt>
        <dd>{releaseAt.toLocaleString()}</dd>
        <dt>Registered SHA-256</dt>
        <dd className="mono">{metadata.sha256_hash}</dd>
        <dt>Integrity / release state</dt>
        <dd>Verified by the server at retrieval time; no result is available before then.</dd>
      </dl>

      {msUntilRelease > 0 && !objectUrl && (
        <p className="notice notice-locked" role="status">
          Scheduled release in <strong>{formatRemaining(msUntilRelease)}</strong> (device clock, for
          information only — the server decides whether the paper can be released).
        </p>
      )}

      {retrievalError && (
        <div
          className={`notice ${retrievalError.kind === "locked" ? "notice-locked" : "notice-security"}`}
          role="alert"
        >
          <strong>{retrievalError.message}</strong>
          {retrievalError.kind === "locked" && (
            <div>Scheduled release: {releaseAt.toLocaleString()}</div>
          )}
        </div>
      )}

      {objectUrl ? (
        <div className="notice notice-success" role="status">
          <p>
            <strong>Question paper released.</strong> The server verified its integrity and the
            scheduled release time. The file is held in this browser tab only and is discarded
            automatically.
          </p>
          <p className="action-row">
            <a className="btn btn-primary btn-link" href={objectUrl} target="_blank" rel="noopener noreferrer">
              Open question paper
            </a>
            <a className="btn btn-secondary btn-link" href={objectUrl} download={safeFileName(metadata.subject)}>
              Download PDF
            </a>
            <Button type="button" variant="secondary" onClick={discard}>
              Discard from browser
            </Button>
          </p>
        </div>
      ) : (
        <Button
          type="button"
          isLoading={isRetrieving}
          disabled={inCooldown}
          onClick={() => {
            void handleRetrieve();
          }}
        >
          {inCooldown ? `Try again in ${cooldownSeconds}s` : "Retrieve question paper"}
        </Button>
      )}
    </div>
  );
}
