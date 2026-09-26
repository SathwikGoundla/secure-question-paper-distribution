/**
 * Backend inspection result (backend/app/api/v1/admin.py, verified
 * during Phase 6B — see PROJECT_STATE.md Section 17):
 *
 *   POST  /api/v1/admin/centres              -> 501 (create, stub only)
 *   PATCH /api/v1/admin/centres/{centre_id}  -> 501 (update, stub only)
 *
 * There is no endpoint to LIST existing examination centres at all —
 * not even a stub. Building a create/edit form for two endpoints that
 * always return 501, with no way to ever see the result, would not be
 * a genuine feature; it would just be a form that always fails. Per
 * the Phase 6B brief ("Do NOT invent CRUD operations if the backend
 * does not support them... document the limitation instead of
 * inventing data"), this page states the real limitation directly
 * rather than presenting a non-functional form or auto-calling a
 * create endpoint as a side effect of simply viewing this page.
 */
export function ExamCentresPage() {
  return (
    <div className="admin-page">
      <h1>Exam Centres</h1>
      <div className="not-implemented-card" role="status">
        <h2>Examination-centre management is not yet available</h2>
        <p>
          The backend has RBAC-protected routes for creating (<code>POST /admin/centres</code>) and
          updating (<code>PATCH /admin/centres/&#123;centre_id&#125;</code>) examination centres, but
          their business logic has not been implemented yet — both currently return HTTP 501 Not
          Implemented.
        </p>
        <p>
          There is currently no backend endpoint to list existing examination centres at all. A centre
          can still be authorized to retrieve a specific paper by its ID from that paper&apos;s detail
          page, once the centre account itself has been created directly in the database by the
          project team (see backend developer documentation) — this is a genuine, documented gap, not
          a frontend limitation.
        </p>
      </div>
    </div>
  );
}
