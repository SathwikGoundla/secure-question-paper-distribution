interface NotYetAvailableNoticeProps {
  title: string;
  /** The real message returned by the backend's 501 stub, if the call was made and failed that way. */
  backendMessage?: string | null;
}

/**
 * Used by Admin Portal pages whose backend endpoint exists and is
 * RBAC-protected (authentication + role checks are real and enforced)
 * but whose business logic has not been implemented yet — it returns
 * HTTP 501 (backend/app/api/v1/admin.py, audit.py). This is shown
 * instead of a fake table, fake form, or fabricated data, per the
 * project rule: "Do NOT invent CRUD operations if the backend does
 * not support them."
 */
export function NotYetAvailableNotice({ title, backendMessage }: NotYetAvailableNoticeProps) {
  return (
    <div className="not-implemented-card" role="status">
      <h2>{title}</h2>
      <p>
        This feature is not yet available. The backend route exists and enforces authentication and
        role-based access control, but its business logic has not been implemented yet
        (HTTP 501 Not Implemented).
      </p>
      {backendMessage && <p className="not-implemented-detail">Backend message: “{backendMessage}”</p>}
    </div>
  );
}
