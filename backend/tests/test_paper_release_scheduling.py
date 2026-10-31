"""
Phase 6G — release scheduling and lifecycle control.

What this phase adds (found by inspecting the repository): there was no
way to change a paper's release time after registration; the stored
`papers.status` is written once as "registered" and never updated, so
the API never told a caller whether a paper was actually locked or
released (LLD API-08 specifies a `lock_status` field that was never
implemented); and the release timestamp accepted at registration was
never required to carry a timezone, even though it drives the
security-critical time-lock.

These tests do NOT test a new time-lock. The only enforcement point is
still paper_service.retrieve_paper; one test below proves that a
reschedule really changes what that existing check does.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.models.paper import Paper
from tests.conftest import SAMPLE_PDF_BYTES, auth_header
from tests.test_idor_cross_centre import centre_a, centre_b  # noqa: F401 (fixtures)
from tests.test_paper_api import _register_sample_paper


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _future(days: int = 30) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(days=days))


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@pytest.fixture()
def locked_paper(client, admin_principal):
    """A paper whose release time is far in the future. Returns paper_id."""
    reg = _register_sample_paper(client, admin_principal, subject="Locked", release_timestamp=_future(60))
    assert reg.status_code == 201, reg.text
    return reg.json()["paper_id"]


@pytest.fixture()
def released_paper(client, admin_principal):
    """A paper whose release time has passed (helper's default). Returns paper_id."""
    reg = _register_sample_paper(client, admin_principal, subject="Released")
    assert reg.status_code == 201, reg.text
    return reg.json()["paper_id"]


def _reschedule(client, principal, paper_id, value):
    return client.patch(
        f"/api/v1/papers/{paper_id}/schedule",
        json={"release_timestamp": value},
        headers=auth_header(principal),
    )


def _stored_release(db_session, paper_id) -> datetime:
    db_session.expire_all()
    ts = db_session.query(Paper).filter(Paper.paper_id == uuid.UUID(paper_id)).one().release_timestamp
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ===========================================================================
# FUNCTIONAL
# ===========================================================================


def test_admin_reschedules_locked_paper(client, db_session, admin_principal, locked_paper):
    new_time = _future(90)
    resp = _reschedule(client, admin_principal, locked_paper, new_time)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"paper_id", "release_timestamp", "lock_status"}
    assert body["paper_id"] == locked_paper
    assert body["lock_status"] == "locked"
    assert _stored_release(db_session, locked_paper) == _parse(new_time)


def test_reschedule_can_be_repeated_last_value_wins(client, db_session, admin_principal, locked_paper):
    assert _reschedule(client, admin_principal, locked_paper, _future(70)).status_code == 200
    last = _future(80)
    assert _reschedule(client, admin_principal, locked_paper, last).status_code == 200
    assert _stored_release(db_session, locked_paper) == _parse(last)


def test_reschedule_to_same_instant_is_a_noop_without_audit(client, db_session, admin_principal, locked_paper):
    current = _iso(_stored_release(db_session, locked_paper))
    before = db_session.query(AuditEvent).filter(AuditEvent.event_type == "PAPER_RELEASE_RESCHEDULED").count()

    resp = _reschedule(client, admin_principal, locked_paper, current)

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    after = db_session.query(AuditEvent).filter(AuditEvent.event_type == "PAPER_RELEASE_RESCHEDULED").count()
    assert after == before


def test_timezone_offset_is_normalised_to_the_same_utc_instant(client, db_session, admin_principal, locked_paper):
    target_utc = datetime.now(timezone.utc) + timedelta(days=45)
    ist = timezone(timedelta(hours=5, minutes=30))
    resp = _reschedule(client, admin_principal, locked_paper, target_utc.astimezone(ist).isoformat())

    assert resp.status_code == 200, resp.text
    assert _stored_release(db_session, locked_paper) == target_utc


def test_reschedule_unknown_paper_returns_404(client, admin_principal):
    assert _reschedule(client, admin_principal, uuid.uuid4(), _future()).status_code == 404


# ===========================================================================
# INVALID INPUT / INVALID STATE
# ===========================================================================


def test_naive_timestamp_rejected_and_nothing_changes(client, db_session, admin_principal, locked_paper):
    before = _stored_release(db_session, locked_paper)
    resp = _reschedule(client, admin_principal, locked_paper, "2099-01-01T00:00:00")  # no timezone

    assert resp.status_code == 400
    assert "timezone" in resp.json()["error"]["message"]
    assert _stored_release(db_session, locked_paper) == before


def test_past_timestamp_rejected_and_nothing_changes(client, db_session, admin_principal, locked_paper):
    before = _stored_release(db_session, locked_paper)
    resp = _reschedule(client, admin_principal, locked_paper, "2000-01-01T00:00:00Z")

    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "The new release time must be in the future."
    assert _stored_release(db_session, locked_paper) == before


@pytest.mark.parametrize("bad", ["not-a-date", "", None, 12345678901234567890])
def test_garbage_timestamp_rejected(client, admin_principal, locked_paper, bad):
    resp = _reschedule(client, admin_principal, locked_paper, bad)
    assert resp.status_code in (400, 422)
    assert "Traceback" not in resp.text


def test_missing_body_field_rejected(client, admin_principal, locked_paper):
    resp = client.patch(f"/api/v1/papers/{locked_paper}/schedule", json={}, headers=auth_header(admin_principal))
    assert resp.status_code == 422


def test_released_paper_cannot_be_rescheduled(client, db_session, admin_principal, released_paper):
    before = _stored_release(db_session, released_paper)
    resp = _reschedule(client, admin_principal, released_paper, _future())

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["message"] == (
        "This paper has already been released and can no longer be rescheduled."
    )
    assert _stored_release(db_session, released_paper) == before

    db_session.expire_all()
    rejected = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "PAPER_RELEASE_RESCHEDULE_REJECTED",
            AuditEvent.paper_id == uuid.UUID(released_paper),
        )
        .all()
    )
    assert len(rejected) == 1 and rejected[0].outcome == "REJECTED"


# ===========================================================================
# AUTHORIZATION
# ===========================================================================


def test_centre_cannot_reschedule(client, locked_paper, centre_a):
    resp = _reschedule(client, centre_a, locked_paper, _future(90))
    assert resp.status_code == 403


def test_auditor_cannot_reschedule(client, locked_paper, auditor_principal):
    assert _reschedule(client, auditor_principal, locked_paper, _future(90)).status_code == 403


def test_unauthenticated_cannot_reschedule(client, locked_paper):
    resp = client.patch(f"/api/v1/papers/{locked_paper}/schedule", json={"release_timestamp": _future(90)})
    assert resp.status_code == 401


def test_cross_centre_cannot_reschedule_another_centres_paper(client, admin_principal, locked_paper, centre_a, centre_b):
    client.post(
        f"/api/v1/papers/{locked_paper}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    # Centre B holds a valid token and knows Centre A's paper id (UUID substitution).
    assert _reschedule(client, centre_b, locked_paper, _future(90)).status_code == 403


# ===========================================================================
# STATUS / lock_status (informational) and the real time-lock
# ===========================================================================


def test_status_reports_locked_then_released(client, admin_principal, locked_paper, released_paper):
    locked = client.get(f"/api/v1/papers/{locked_paper}/status", headers=auth_header(admin_principal))
    released = client.get(f"/api/v1/papers/{released_paper}/status", headers=auth_header(admin_principal))
    assert locked.status_code == released.status_code == 200
    assert locked.json()["lock_status"] == "locked"
    assert released.json()["lock_status"] == "released"


def test_status_denied_to_unauthorized_centre(client, released_paper, centre_b):
    resp = client.get(f"/api/v1/papers/{released_paper}/status", headers=auth_header(centre_b))
    # Phase 6I disclosure policy: generic 404 (was 403); the release state is still never disclosed.
    assert resp.status_code == 404
    assert "lock_status" not in resp.text


def test_reschedule_really_changes_the_existing_time_lock(client, admin_principal, centre_a):
    """End to end: a paper locked far in the future is rescheduled to ~3s
    from now. Retrieval is denied before that instant and allowed after it
    — the existing retrieve_paper check, reading the updated value. Real
    sleep of a few seconds, deliberately: it exercises the real clock
    rather than a mocked one."""
    reg = _register_sample_paper(client, admin_principal, subject="Soon", release_timestamp=_future(60))
    paper_id = reg.json()["paper_id"]
    client.post(
        f"/api/v1/papers/{paper_id}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    assert client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(centre_a)).status_code == 403

    soon = _iso(datetime.now(timezone.utc) + timedelta(seconds=4))
    assert _reschedule(client, admin_principal, paper_id, soon).status_code == 200

    early = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(centre_a))
    assert early.status_code == 403
    assert early.json()["error"]["message"] == "This paper is not yet available."

    time.sleep(4.5)

    late = client.get(f"/api/v1/papers/{paper_id}/retrieve", headers=auth_header(centre_a))
    assert late.status_code == 200
    assert late.content == SAMPLE_PDF_BYTES
    status = client.get(f"/api/v1/papers/{paper_id}/status", headers=auth_header(admin_principal))
    assert status.json()["lock_status"] == "released"


# ===========================================================================
# REGISTRATION TIMEZONE HARDENING
# ===========================================================================


def test_registration_rejects_naive_release_timestamp(client, admin_principal):
    resp = _register_sample_paper(
        client, admin_principal, subject="Naive", release_timestamp="2099-01-01T00:00:00"
    )
    assert resp.status_code == 400, resp.text
    assert "timezone" in resp.json()["error"]["message"]


def test_registration_accepts_offset_timestamp_and_stores_utc_instant(client, db_session, admin_principal):
    target_utc = datetime.now(timezone.utc) + timedelta(days=10)
    ist = timezone(timedelta(hours=5, minutes=30))
    resp = _register_sample_paper(
        client, admin_principal, subject="Offset", release_timestamp=target_utc.astimezone(ist).isoformat()
    )
    assert resp.status_code == 201, resp.text
    assert _stored_release(db_session, resp.json()["paper_id"]) == target_utc


# ===========================================================================
# AUDIT
# ===========================================================================


def test_successful_reschedule_creates_one_audit_event(client, db_session, admin_principal, locked_paper):
    before = {e.event_id for e in db_session.query(AuditEvent).all()}
    assert _reschedule(client, admin_principal, locked_paper, _future(100)).status_code == 200

    db_session.expire_all()
    new = [
        e
        for e in db_session.query(AuditEvent).all()
        if e.event_id not in before and e.event_type == "PAPER_RELEASE_RESCHEDULED"
    ]
    assert len(new) == 1
    assert new[0].outcome == "SUCCESS"
    assert new[0].actor_id == admin_principal.user_id
    assert new[0].paper_id == uuid.UUID(locked_paper)
