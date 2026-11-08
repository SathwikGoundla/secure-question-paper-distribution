import { useCallback, useEffect, useState, type FormEvent } from "react";
import { issueTotpEnrollmentCode, listTotpUsers } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type { AdminEnrollmentCodeResponse, AdminTotpUser, TotpEnrollmentStatus } from "../../../types/auth";
import { Button } from "../../../components/common/Button";
import { Input } from "../../../components/common/Input";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { EmptyState } from "../../../components/common/EmptyState";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";

const PAGE_SIZE = 25;

const STATUS_LABEL: Record<TotpEnrollmentStatus, string> = {
  not_enrolled: "Not enrolled",
  code_issued: "Code issued",
  enrollment_in_progress: "Enrollment in progress",
  code_expired: "Code expired",
  needs_new_code: "Needs a new code",
  active: "Active",
};

/**
 * Phase 7B — Admin authenticator (TOTP) enrollment management.
 *
 * Lists each user's enrollment STATE and lets an Admin issue a one-time enrollment code for another
 * user (GET /admin/totp/users, POST /admin/totp/enrollment-codes). The code is displayed once, in this
 * component's state only, and discarded on dismissal. The page never receives secrets, hashes or
 * recovery codes: the backend does not return them. Authorization is enforced by the backend; the
 * route guard and the disabled "Issue" button for your own row are UX only.
 */
export function TotpManagementPage() {
  const [users, setUsers] = useState<AdminTotpUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [pending, setPending] = useState<AdminTotpUser | null>(null);
  const [isIssuing, setIsIssuing] = useState(false);
  const [issueError, setIssueError] = useState<string | null>(null);
  const [issued, setIssued] = useState<AdminEnrollmentCodeResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    listTotpUsers({ page, pageSize: PAGE_SIZE, q: appliedFilter || undefined })
      .then((data) => {
        setUsers(data.items);
        setTotal(data.total);
      })
      .catch((err: unknown) =>
        setLoadError(err instanceof ApiError ? err.userMessage : "Unable to load enrollment status."),
      )
      .finally(() => setLoading(false));
  }, [page, appliedFilter]);

  useEffect(() => {
    load();
  }, [load]);

  function applyFilter(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setAppliedFilter(filter.trim());
  }

  async function confirmIssue() {
    if (!pending) return;
    setIsIssuing(true);
    setIssueError(null);
    try {
      const result = await issueTotpEnrollmentCode(pending.username);
      setIssued(result);
      setCopied(false);
      setPending(null);
      load();
    } catch (err) {
      setIssueError(err instanceof ApiError ? err.userMessage : "Unable to issue an enrollment code.");
    } finally {
      setIsIssuing(false);
    }
  }

  async function copyCode() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.enrollment_code);
      setCopied(true);
    } catch {
      setCopied(false);
      setIssueError("Copying is not available in this browser. Select the code and copy it manually.");
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="admin-page">
      <h1>Authenticator Enrollment</h1>
      <p className="admin-page-note">
        Users must enroll an authenticator app before they can sign in. Issue a one-time enrollment code and give it to
        the user over a trusted channel; they then open “Set up authenticator” on the sign-in page.
      </p>

      {issued && (
        <section role="status" aria-label="New enrollment code" className="admin-callout">
          <p>
            Enrollment code for <strong>{issued.username}</strong> — shown only once:
          </p>
          <p>
            <code data-testid="issued-code">{issued.enrollment_code}</code>
          </p>
          <p>Valid until {new Date(issued.expires_at).toLocaleString()}. It works once.</p>
          <Button type="button" onClick={() => void copyCode()}>
            {copied ? "Copied" : "Copy code"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setIssued(null);
              setCopied(false);
            }}
          >
            Done — hide code
          </Button>
        </section>
      )}

      <form className="lookup-form" onSubmit={applyFilter}>
        <Input
          id="totp-filter"
          label="Filter by username"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <Button type="submit">Filter</Button>
      </form>

      {pending && (
        <section role="alertdialog" aria-label="Confirm enrollment code" className="admin-callout">
          <p>
            {pending.totp_status === "active" ? (
              <>
                Issuing a new code for <strong>{pending.username}</strong> will <strong>remove their current
                authenticator and recovery codes and sign them out</strong>. They cannot sign in again until they
                re-enroll with the new code.
              </>
            ) : (
              <>
                Issue a new one-time enrollment code for <strong>{pending.username}</strong>? Any earlier unused code
                stops working and any sessions are revoked.
              </>
            )}
          </p>
          <ErrorBanner message={issueError} />
          <Button type="button" onClick={() => void confirmIssue()} isLoading={isIssuing}>
            Issue code
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setPending(null);
              setIssueError(null);
            }}
          >
            Cancel
          </Button>
        </section>
      )}
      {!pending && issueError && <ErrorBanner message={issueError} />}

      {loading && <LoadingIndicator label="Loading enrollment status…" />}
      {!loading && loadError && <ErrorBanner message={loadError} />}
      {!loading && !loadError && users.length === 0 && <EmptyState message="No users match." />}
      {!loading && !loadError && users.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Role</th>
                  <th>Centre</th>
                  <th>Authenticator</th>
                  <th>Code expires</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id}>
                    <td>
                      {u.username}
                      {u.is_self && <span className="role-badge"> you</span>}
                    </td>
                    <td>{u.role}</td>
                    <td>{u.centre_name ?? "—"}</td>
                    <td>
                      <span className="status-badge">{STATUS_LABEL[u.totp_status] ?? u.totp_status}</span>
                    </td>
                    <td>{u.code_expires_at ? new Date(u.code_expires_at).toLocaleString() : "—"}</td>
                    <td>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={u.is_self}
                        title={u.is_self ? "You cannot reset your own authenticator here. Ask the server operator." : undefined}
                        aria-label={`${u.totp_status === "active" || u.totp_status === "needs_new_code" || u.totp_status === "code_expired" ? "Reissue" : "Issue"} enrollment code for ${u.username}`}
                        onClick={() => {
                          setIssued(null);
                          setIssueError(null);
                          setPending(u);
                        }}
                      >
                        {u.totp_status === "not_enrolled" ? "Issue code" : "Reissue code"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="admin-page-note">
            Page {page} of {pageCount} ({total} user{total === 1 ? "" : "s"})
            {" "}
            <Button type="button" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button type="button" variant="secondary" disabled={page >= pageCount} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </p>
        </>
      )}
    </div>
  );
}
