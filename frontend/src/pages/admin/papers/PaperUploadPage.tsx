import { useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { registerPaper } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import { useKnownPapers } from "../../../hooks/useKnownPapers";
import { Button } from "../../../components/common/Button";
import { Input } from "../../../components/common/Input";
import { ErrorBanner } from "../../../components/common/ErrorBanner";

type UploadState =
  | "idle"
  | "uploading"
  | "success"
  | "validation_error"
  | "auth_error"
  | "server_error"
  | "network_error";

/**
 * POST /api/v1/papers/register (LLD API-04, backend/app/api/v1/papers.py
 * `register_paper`) — Admin-only, multipart/form-data. The backend
 * performs AES-256 encryption, SHA-256 hashing, off-chain storage, and
 * a best-effort Hyperledger Fabric registration entirely server-side;
 * this page only ever sends the original plaintext PDF the admin
 * selected. No encryption happens in the browser.
 */
export function PaperUploadPage() {
  const navigate = useNavigate();
  const { remember } = useKnownPapers();

  const [subject, setSubject] = useState("");
  const [releaseTimestamp, setReleaseTimestamp] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [state, setState] = useState<UploadState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);

    if (!subject.trim() || !releaseTimestamp || !file) {
      setState("validation_error");
      setMessage("Subject, release date/time, and a question-paper file are all required.");
      return;
    }

    setState("uploading");
    try {
      // <input type="datetime-local"> yields "YYYY-MM-DDTHH:mm" with no
      // timezone; new Date(...).toISOString() sends an explicit UTC
      // instant so the backend never has to guess the browser's
      // timezone for a security-sensitive release-time comparison.
      const isoTimestamp = new Date(releaseTimestamp).toISOString();
      const result = await registerPaper({ subject: subject.trim(), releaseTimestamp: isoTimestamp, file });
      remember({
        paper_id: result.paper_id,
        subject: result.subject,
        status: result.status,
        created_at: result.created_at,
      });
      setState("success");
      setMessage(`Paper registered successfully (status: ${result.status}).`);
      window.setTimeout(() => navigate(`/admin/papers/${result.paper_id}`), 1200);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400 || err.status === 422) {
          setState("validation_error");
        } else if (err.status === 401 || err.status === 403) {
          setState("auth_error");
        } else if (err.status === null) {
          setState("network_error");
        } else {
          setState("server_error");
        }
        setMessage(err.userMessage);
      } else {
        setState("server_error");
        setMessage("An unexpected error occurred while uploading the paper.");
      }
    }
  }

  const isUploading = state === "uploading";

  return (
    <div className="admin-page">
      <h1>Register New Question Paper</h1>
      <p className="admin-page-note">
        The file is uploaded exactly as selected. Encryption (AES-256) and hashing (SHA-256) are
        performed by the backend, never in the browser.
      </p>

      <form className="admin-form" onSubmit={handleSubmit}>
        <Input
          id="subject"
          label="Subject / exam name"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          disabled={isUploading}
        />
        <Input
          id="release-timestamp"
          label="Scheduled release date/time"
          type="datetime-local"
          value={releaseTimestamp}
          onChange={(e) => setReleaseTimestamp(e.target.value)}
          disabled={isUploading}
        />
        <div className="form-field">
          <label htmlFor="paper-file">Question paper file (PDF)</label>
          <input id="paper-file" type="file" accept="application/pdf" onChange={handleFileChange} disabled={isUploading} />
        </div>

        {state === "success" ? (
          <p className="success-banner" role="status">
            {message}
          </p>
        ) : (
          <ErrorBanner message={message} />
        )}

        <Button type="submit" isLoading={isUploading}>
          Register Paper
        </Button>
      </form>
    </div>
  );
}
