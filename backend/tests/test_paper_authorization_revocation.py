"""
Phase 6F — examination-centre authorization revocation.

Objective (determined by inspecting the actual repository, not
invented): app/models/paper_authorization.py's is_revoked column, and
app/services/blockchain_service.py's BlockchainService.revoke_centre()
abstract method (with a working StubBlockchainService implementation),
have existed since early phases — but no API endpoint, no service
function, and no audit event type ever actually set is_revoked to
True. LLD CC-03 (RevokeCentre) was designed but never wired up.
Inspection also surfaced a real, demonstrable, previously-untestable
bug: PaperAuthorization has a genuine database-level UniqueConstraint
on (paper_id, centre_id) alone (not also is_revoked), but
authorize_centre's pre-Phase-6F existing-row lookup only matched
NON-revoked rows — so once a revoked row could exist, re-authorizing
that exact (paper_id, centre_id) pair would fall through to an INSERT
and collide with the constraint, raising an unhandled 500. This file
both closes the missing-capability gap (a working revoke endpoint) and
proves the accompanying authorize_centre fix.

No blockchain call is attempted by revoke_centre_authorization,
mirroring authorize_centre's own existing design: CC-02 AuthorizeCentre
and CC-03 RevokeCentre are both UNSUPPORTED by the deployed Fabric
chaincode today (see fabric_blockchain_service.py's support matrix) —
this was not changed by Phase 6F and no new blockchain code was added.
"""

import uuid

import pytest

from app.models.paper_authorization import PaperAuthorization
from tests.conftest import auth_header
from tests.test_idor_cross_centre import centre_a, centre_b  # noqa: F401 (fixtures)
from tests.test_paper_api import _register_sample_paper


@pytest.fixture()
def authorized_paper(client, admin_principal, centre_a):
    """A released paper, actively authorized to centre_a. Returns
    (paper_id, centre_id) as (str, uuid.UUID)."""
    reg = _register_sample_paper(client, admin_principal, subject="Revocation Test Paper")
    assert reg.status_code == 201, reg.text
    paper_id = reg.json()["paper_id"]

    auth_resp = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert auth_resp.status_code == 200, auth_resp.text

    return paper_id, centre_a.centre_id


# ===========================================================================
# FUNCTIONAL
# ===========================================================================


def test_admin_revokes_active_authorization(client, db_session, admin_principal, authorized_paper):
    paper_id, centre_id = authorized_paper

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["paper_id"] == paper_id
    assert body["centre_id"] == str(centre_id)

    db_session.expire_all()
    row = (
        db_session.query(PaperAuthorization)
        .filter(PaperAuthorization.paper_id == uuid.UUID(paper_id), PaperAuthorization.centre_id == centre_id)
        .one()
    )
    assert row.is_revoked is True


def test_revoking_never_authorized_centre_is_rejected(client, admin_principal, centre_b):
    reg = _register_sample_paper(client, admin_principal, subject="Never Authorized Paper")
    assert reg.status_code == 201, reg.text
    paper_id = reg.json()["paper_id"]

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_b.centre_id)},
        headers=auth_header(admin_principal),
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["message"] == "This centre is not currently authorized for this paper."


def test_revoking_an_already_revoked_authorization_is_rejected_not_silent(
    client, admin_principal, authorized_paper
):
    paper_id, centre_id = authorized_paper

    first = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )
    assert second.status_code == 400, second.text
    assert second.json()["error"]["message"] == "This centre is not currently authorized for this paper."


def test_reauthorizing_after_revocation_succeeds_instead_of_500ing(
    client, db_session, admin_principal, authorized_paper
):
    """
    THE bug-fix regression test. Before the Phase 6F fix to
    authorize_centre, this exact sequence (authorize -> revoke ->
    authorize again for the SAME paper+centre pair) raised an
    unhandled IntegrityError (surfacing as a bare 500) the moment a
    revoked row could exist at all, because the old existing-row
    lookup excluded revoked rows and therefore always tried to INSERT
    a second row for a (paper_id, centre_id) pair already covered by
    uq_paper_authorizations_paper_centre.
    """
    paper_id, centre_id = authorized_paper

    revoke_resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )
    assert revoke_resp.status_code == 200, revoke_resp.text

    reauthorize_resp = client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )

    assert reauthorize_resp.status_code == 200, reauthorize_resp.text
    assert "Traceback" not in reauthorize_resp.text

    db_session.expire_all()
    rows = (
        db_session.query(PaperAuthorization)
        .filter(PaperAuthorization.paper_id == uuid.UUID(paper_id), PaperAuthorization.centre_id == centre_id)
        .all()
    )
    # Exactly one row for this pair (re-activated, not duplicated) —
    # the unique constraint's own guarantee, confirmed from the
    # application side too.
    assert len(rows) == 1
    assert rows[0].is_revoked is False

    # And the centre is immediately usable again (not just "a row
    # exists" — the actual authorization-check path agrees).
    detail_resp = client.get(f"/api/v1/papers/{paper_id}", headers=auth_header(admin_principal))
    assert detail_resp.status_code == 200


def test_revoking_unknown_centre_id_rejected(client, admin_principal):
    reg = _register_sample_paper(client, admin_principal, subject="Unknown Centre Revoke Paper")
    assert reg.status_code == 201, reg.text
    paper_id = reg.json()["paper_id"]

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(uuid.uuid4())},
        headers=auth_header(admin_principal),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "Unknown centre_id."


def test_revoking_unknown_paper_id_returns_404(client, admin_principal, centre_a):
    resp = client.post(
        f"/api/v1/papers/{uuid.uuid4()}/revoke",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert resp.status_code == 404


# ===========================================================================
# AUTHORIZATION / RBAC
# ===========================================================================


def test_examination_centre_cannot_call_revoke(client, authorized_paper, centre_a):
    paper_id, centre_id = authorized_paper

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(centre_a),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "You do not have permission to perform this action."


def test_auditor_cannot_call_revoke(client, authorized_paper, auditor_principal):
    paper_id, centre_id = authorized_paper

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(auditor_principal),
    )
    assert resp.status_code == 403


def test_cross_centre_cannot_revoke_another_centres_authorization(
    client, authorized_paper, centre_b
):
    """Centre B (not even Admin) attempting to revoke Centre A's
    authorization for a paper — blocked purely by RBAC (Admin-only),
    never reaching any paper/centre lookup."""
    paper_id, centre_id_a = authorized_paper

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id_a)},
        headers=auth_header(centre_b),
    )
    assert resp.status_code == 403


def test_unauthenticated_cannot_call_revoke(client, authorized_paper):
    paper_id, centre_id = authorized_paper
    resp = client.post(f"/api/v1/papers/{paper_id}/revoke", json={"centre_id": str(centre_id)})
    assert resp.status_code == 401


# ===========================================================================
# END-TO-END SECURITY EFFECT OF REVOCATION
# ===========================================================================


def test_revoked_centre_denied_retrieval(client, admin_principal, authorized_paper, centre_a):
    """Confirms is_centre_authorized_for_paper's existing is_revoked
    filter (unchanged by Phase 6F) takes effect immediately, and that
    a revoked centre is denied with the exact same generic message as
    a never-authorized one — no new oracle introduced. Also proves
    this is a real transition (retrieval succeeds BEFORE revocation),
    not merely "it was already impossible."
    """
    paper_id, centre_id = authorized_paper
    assert centre_id == centre_a.centre_id

    before_resp = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(centre_a))
    assert before_resp.status_code == 200, before_resp.text

    revoke_resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )
    assert revoke_resp.status_code == 200, revoke_resp.text

    after_resp = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(centre_a))
    assert after_resp.status_code == 404
    assert after_resp.json()["error"]["message"] == "The requested resource was not found."


def test_revoked_paper_disappears_from_centre_list(client, admin_principal, authorized_paper, centre_a):
    paper_id, centre_id = authorized_paper

    before_list = client.get("/api/v1/papers", headers=auth_header(centre_a))
    assert paper_id in {item["paper_id"] for item in before_list.json()["items"]}

    client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )

    after_list = client.get("/api/v1/papers", headers=auth_header(centre_a))
    assert paper_id not in {item["paper_id"] for item in after_list.json()["items"]}


def test_revoked_centre_denied_metadata_view(client, admin_principal, authorized_paper, centre_a):
    paper_id, centre_id = authorized_paper

    client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )

    resp = client.get(f"/api/v1/papers/{paper_id}", headers=auth_header(centre_a))
    assert resp.status_code == 404


# ===========================================================================
# AUDIT LOGGING
# ===========================================================================


def test_revocation_creates_audit_event(client, db_session, admin_principal, authorized_paper):
    from app.models.audit_event import AuditEvent

    paper_id, centre_id = authorized_paper
    before_ids = {e.event_id for e in db_session.query(AuditEvent).all()}

    resp = client.post(
        f"/api/v1/papers/{paper_id}/revoke",
        json={"centre_id": str(centre_id)},
        headers=auth_header(admin_principal),
    )
    assert resp.status_code == 200

    db_session.expire_all()
    new_events = [e for e in db_session.query(AuditEvent).all() if e.event_id not in before_ids]
    revoke_events = [e for e in new_events if e.event_type == "CENTRE_AUTHORIZATION_REVOKED"]
    assert len(revoke_events) == 1
    assert revoke_events[0].outcome == "SUCCESS"
    assert revoke_events[0].paper_id == uuid.UUID(paper_id)
    assert revoke_events[0].actor_id == admin_principal.user_id
