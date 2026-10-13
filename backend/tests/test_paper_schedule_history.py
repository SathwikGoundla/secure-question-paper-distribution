"""
Phase 6H — paper lifecycle consistency and release-schedule history.

Two things are tested here (found by inspecting the Phase 6G code):

1. Lifecycle semantics. `papers.status` is a persisted REGISTRATION
   status (always "registered"). `lock_status` is the RELEASE state,
   computed by the server clock through the one shared function
   paper_service.is_released. Before this phase only two endpoints
   returned lock_status; now every endpoint that returns a paper
   returns it, from the same helper. Neither value says a centre opened
   the paper; that is access history, visible only as PAPER_RELEASED
   audit events written after a verified, decrypted delivery.

2. Schedule history. Every successful, effective reschedule writes a
   paper_schedule_history row (old and new instants) in the SAME
   transaction as the update. Rejected attempts and same-instant no-ops
   write nothing.

These tests do not add or test a second time-lock; retrieve_paper is
still the only gate.
"""

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.deps import CurrentUser
from app.database import get_db
from app.exceptions.base import ConflictException
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.paper import Paper
from app.models.paper_schedule_history import PaperScheduleHistory
from app.services import paper_service
from tests.conftest import SAMPLE_PDF_BYTES, auth_header
from tests.test_idor_cross_centre import centre_a  # noqa: F401 (fixture)
from tests.test_paper_api import _register_sample_paper
from tests.test_paper_release_scheduling import (  # noqa: F401 (fixtures + helpers)
    _future,
    _iso,
    _parse,
    _reschedule,
    _stored_release,
    locked_paper,
    released_paper,
)


def _history_rows(db_session, paper_id) -> list[PaperScheduleHistory]:
    db_session.expire_all()
    return (
        db_session.query(PaperScheduleHistory)
        .filter(PaperScheduleHistory.paper_id == uuid.UUID(str(paper_id)))
        .order_by(PaperScheduleHistory.created_at.asc(), PaperScheduleHistory.history_id.asc())
        .all()
    )


def _count_events(db_session, event_type: str, paper_id) -> int:
    db_session.expire_all()
    return (
        db_session.query(AuditEvent)
        .filter(AuditEvent.event_type == event_type, AuditEvent.paper_id == uuid.UUID(str(paper_id)))
        .count()
    )


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _get_history(client, principal, paper_id, **params):
    return client.get(
        f"/api/v1/papers/{paper_id}/schedule-history",
        params=params,
        headers=auth_header(principal),
    )


def _as_current_user(principal) -> CurrentUser:
    return CurrentUser(
        user_id=principal.user_id,
        username=principal.username,
        role_name="Admin",
        centre_id=None,
        jti="test",
    )


# ===========================================================================
# LIFECYCLE / STATUS CONSISTENCY
# ===========================================================================


def test_future_paper_is_registered_and_locked_in_every_response(client, admin_principal):
    reg = _register_sample_paper(client, admin_principal, subject="Future", release_timestamp=_future(30))
    assert reg.status_code == 201, reg.text
    paper_id = reg.json()["paper_id"]
    h = auth_header(admin_principal)

    bodies = {
        "register": reg.json(),
        "metadata": client.get(f"/api/v1/papers/{paper_id}", headers=h).json(),
        "status": client.get(f"/api/v1/papers/{paper_id}/status", headers=h).json(),
        "list": next(
            i for i in client.get("/api/v1/papers", headers=h).json()["items"] if i["paper_id"] == paper_id
        ),
    }
    for name, body in bodies.items():
        assert body["status"] == "registered", name
        assert body["lock_status"] == "locked", name


def test_past_paper_is_registered_and_released_in_every_response(client, admin_principal, released_paper):
    h = auth_header(admin_principal)
    bodies = {
        "metadata": client.get(f"/api/v1/papers/{released_paper}", headers=h).json(),
        "status": client.get(f"/api/v1/papers/{released_paper}/status", headers=h).json(),
        "list": next(
            i for i in client.get("/api/v1/papers", headers=h).json()["items"] if i["paper_id"] == released_paper
        ),
    }
    for name, body in bodies.items():
        assert body["status"] == "registered", name  # registration status is unchanged by release
        assert body["lock_status"] == "released", name


def test_registering_a_released_paper_reports_released_in_the_register_response(client, admin_principal):
    reg = _register_sample_paper(client, admin_principal, subject="Past")
    assert reg.status_code == 201
    assert reg.json()["status"] == "registered"
    assert reg.json()["lock_status"] == "released"


def test_release_boundary_is_inclusive_and_uses_the_shared_helper():
    t = datetime(2030, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    assert paper_service.lock_status_for(t, now=t - timedelta(microseconds=1)) == "locked"
    assert paper_service.lock_status_for(t, now=t) == "released"  # exact instant = released
    assert paper_service.lock_status_for(t, now=t + timedelta(microseconds=1)) == "released"
    # and it is literally the same decision the time-lock uses
    for now in (t - timedelta(seconds=1), t, t + timedelta(seconds=1)):
        assert (paper_service.lock_status_for(t, now) == "released") == paper_service.is_released(t, now)


def test_every_endpoint_derives_lock_status_from_the_one_shared_function(
    client, admin_principal, locked_paper, monkeypatch
):
    """If is_released is forced true, EVERY surface must flip together —
    proof that no endpoint carries its own copy of the comparison."""
    monkeypatch.setattr(paper_service, "is_released", lambda *a, **k: True)
    h = auth_header(admin_principal)
    assert client.get(f"/api/v1/papers/{locked_paper}", headers=h).json()["lock_status"] == "released"
    assert client.get(f"/api/v1/papers/{locked_paper}/status", headers=h).json()["lock_status"] == "released"
    listed = next(
        i for i in client.get("/api/v1/papers", headers=h).json()["items"] if i["paper_id"] == locked_paper
    )
    assert listed["lock_status"] == "released"


def test_centre_sees_the_same_server_computed_release_state(
    client, admin_principal, centre_a, locked_paper, released_paper  # noqa: F811
):
    for pid, expected in ((locked_paper, "locked"), (released_paper, "released")):
        r = client.post(
            f"/api/v1/papers/{pid}/authorize",
            json={"centre_id": str(centre_a.centre_id)},
            headers=auth_header(admin_principal),
        )
        assert r.status_code == 200, r.text
        h = auth_header(centre_a)
        assert client.get(f"/api/v1/papers/{pid}", headers=h).json()["lock_status"] == expected
        assert client.get(f"/api/v1/papers/{pid}/status", headers=h).json()["lock_status"] == expected
        listed = next(i for i in client.get("/api/v1/papers", headers=h).json()["items"] if i["paper_id"] == pid)
        assert listed["lock_status"] == expected


def test_release_time_passing_does_not_claim_the_paper_was_accessed(
    client, db_session, admin_principal, centre_a, released_paper  # noqa: F811
):
    """Released != opened. No access evidence exists until a centre
    actually retrieves the paper; the status fields never imply it."""
    client.post(
        f"/api/v1/papers/{released_paper}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    status_body = client.get(f"/api/v1/papers/{released_paper}/status", headers=auth_header(admin_principal)).json()
    assert set(status_body.keys()) == {"paper_id", "status", "release_timestamp", "lock_status"}
    assert status_body["lock_status"] == "released"
    assert _count_events(db_session, "PAPER_RELEASED", released_paper) == 0  # nobody opened it

    # A real, verified retrieval creates the (only) access evidence, and
    # changes neither status field's meaning.
    r = client.get(f"/api/v1/papers/{released_paper}/retrieve", headers=auth_header(centre_a))
    assert r.status_code == 200, r.text
    assert r.content == SAMPLE_PDF_BYTES
    assert _count_events(db_session, "PAPER_RELEASED", released_paper) == 1
    after = client.get(f"/api/v1/papers/{released_paper}/status", headers=auth_header(admin_principal)).json()
    assert after["status"] == "registered" and after["lock_status"] == "released"


def test_missing_or_naive_schedule_is_rejected_and_nothing_is_stored(client, db_session, admin_principal):
    before = db_session.query(Paper).count()
    files = {"file": ("sample.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    missing = client.post(
        "/api/v1/papers/register",
        data={"subject": "No schedule"},
        files=files,
        headers=auth_header(admin_principal),
    )
    assert missing.status_code == 422
    naive = _register_sample_paper(client, admin_principal, release_timestamp="2031-01-01T09:00:00")
    assert naive.status_code == 400
    db_session.expire_all()
    assert db_session.query(Paper).count() == before


def test_release_timestamp_column_is_not_nullable(db_session, admin_principal):
    """The schema itself forbids a paper without a schedule, so 'missing
    schedule' cannot exist as a stored lifecycle state."""
    p = Paper(
        subject="x",
        file_reference="x",
        sha256_hash="0" * 64,
        release_timestamp=None,  # type: ignore[arg-type]
        registered_by=admin_principal.user_id,
    )
    db_session.add(p)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_rescheduling_still_only_allowed_while_locked(client, db_session, admin_principal, released_paper):
    resp = _reschedule(client, admin_principal, released_paper, _future(5))
    assert resp.status_code == 409
    assert _history_rows(db_session, released_paper) == []


# ===========================================================================
# SCHEDULE HISTORY — WRITES
# ===========================================================================


def test_first_reschedule_records_actual_old_and_new_values(client, db_session, admin_principal, locked_paper):
    original = _stored_release(db_session, locked_paper)
    new_time = _future(90)

    resp = _reschedule(client, admin_principal, locked_paper, new_time)
    assert resp.status_code == 200, resp.text

    rows = _history_rows(db_session, locked_paper)
    assert len(rows) == 1
    row = rows[0]
    assert str(row.paper_id) == locked_paper
    assert row.actor_id == admin_principal.user_id
    assert row.action == "RESCHEDULED"
    assert _aware(row.previous_release_timestamp) == original
    assert _aware(row.new_release_timestamp) == _parse(new_time)
    assert abs(_aware(row.created_at) - datetime.now(timezone.utc)) < timedelta(minutes=2)
    assert _count_events(db_session, "PAPER_RELEASE_RESCHEDULED", locked_paper) == 1


def test_new_value_is_stored_as_the_utc_instant_for_any_input_offset(client, db_session, admin_principal, locked_paper):
    target = datetime.now(timezone.utc) + timedelta(days=45)
    ist = timezone(timedelta(hours=5, minutes=30))
    sent = target.astimezone(ist).isoformat()
    assert _reschedule(client, admin_principal, locked_paper, sent).status_code == 200

    row = _history_rows(db_session, locked_paper)[0]
    assert _aware(row.new_release_timestamp) == target.replace(microsecond=target.microsecond)
    assert _aware(row.new_release_timestamp).utcoffset() == timedelta(0)


def test_multiple_reschedules_form_an_ordered_unbroken_chain(client, db_session, admin_principal, locked_paper):
    original = _stored_release(db_session, locked_paper)
    values = [_future(70), _future(80), _future(95)]
    for v in values:
        assert _reschedule(client, admin_principal, locked_paper, v).status_code == 200

    rows = _history_rows(db_session, locked_paper)
    assert [_aware(r.new_release_timestamp) for r in rows] == [_parse(v) for v in values]
    assert _aware(rows[0].previous_release_timestamp) == original
    for earlier, later in zip(rows, rows[1:]):
        assert _aware(later.previous_release_timestamp) == _aware(earlier.new_release_timestamp)
    assert _stored_release(db_session, locked_paper) == _parse(values[-1])


def test_same_instant_is_a_noop_with_no_history_row(client, db_session, admin_principal, locked_paper):
    assert _reschedule(client, admin_principal, locked_paper, _future(88)).status_code == 200
    current = _iso(_stored_release(db_session, locked_paper))
    assert len(_history_rows(db_session, locked_paper)) == 1

    again = _reschedule(client, admin_principal, locked_paper, current)

    assert again.status_code == 200
    assert len(_history_rows(db_session, locked_paper)) == 1
    assert _count_events(db_session, "PAPER_RELEASE_RESCHEDULED", locked_paper) == 1


@pytest.mark.parametrize(
    "bad_value,expected_status",
    [
        ("2031-01-01T09:00:00", 400),  # no timezone
        ("2001-01-01T00:00:00Z", 400),  # past
        ("not-a-date", 422),
    ],
)
def test_rejected_updates_create_no_history(client, db_session, admin_principal, locked_paper, bad_value, expected_status):
    original = _stored_release(db_session, locked_paper)
    resp = _reschedule(client, admin_principal, locked_paper, bad_value)
    assert resp.status_code == expected_status
    assert _history_rows(db_session, locked_paper) == []
    assert _stored_release(db_session, locked_paper) == original


def test_already_released_rejection_creates_rejected_audit_but_no_history(
    client, db_session, admin_principal, released_paper
):
    resp = _reschedule(client, admin_principal, released_paper, _future(10))
    assert resp.status_code == 409
    assert _history_rows(db_session, released_paper) == []
    assert _count_events(db_session, "PAPER_RELEASE_RESCHEDULE_REJECTED", released_paper) == 1
    assert _count_events(db_session, "PAPER_RELEASE_RESCHEDULED", released_paper) == 0


def test_non_admin_and_unauthenticated_cannot_reschedule_or_create_history(
    client, db_session, admin_principal, centre_a, auditor_principal, locked_paper  # noqa: F811
):
    value = _future(66)
    assert _reschedule(client, centre_a, locked_paper, value).status_code == 403
    assert _reschedule(client, auditor_principal, locked_paper, value).status_code == 403
    anon = client.patch(f"/api/v1/papers/{locked_paper}/schedule", json={"release_timestamp": value})
    assert anon.status_code == 401
    assert _history_rows(db_session, locked_paper) == []


def test_unknown_paper_reschedule_is_404_and_creates_nothing(client, db_session, admin_principal):
    before = db_session.query(PaperScheduleHistory).count()
    resp = _reschedule(client, admin_principal, str(uuid.uuid4()), _future(10))
    assert resp.status_code == 404
    db_session.expire_all()
    assert db_session.query(PaperScheduleHistory).count() == before


# ===========================================================================
# SCHEDULE HISTORY — ATOMICITY / CONCURRENCY
# ===========================================================================


def test_history_failure_rolls_back_the_schedule_update(client, db_session, admin_principal, locked_paper, monkeypatch):
    """The history row is built after the paper is modified. If that step
    fails, the paper's release time must be unchanged and no success
    audit event exists."""
    original = _stored_release(db_session, locked_paper)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated history write failure")

    monkeypatch.setattr(paper_service, "PaperScheduleHistory", boom)

    with pytest.raises(RuntimeError):
        paper_service.reschedule_paper_release(
            db_session, _as_current_user(admin_principal), uuid.UUID(locked_paper), datetime.now(timezone.utc) + timedelta(days=99)
        )

    assert _stored_release(db_session, locked_paper) == original
    assert _history_rows(db_session, locked_paper) == []
    assert _count_events(db_session, "PAPER_RELEASE_RESCHEDULED", locked_paper) == 0


def test_database_level_history_failure_rolls_back_the_paper_update(
    client, db_session, admin_principal, locked_paper, monkeypatch
):
    """Stronger: both rows reach the database in one transaction and the
    HISTORY insert violates a NOT NULL constraint at commit. The earlier
    UPDATE of papers must be undone with it."""
    original = _stored_release(db_session, locked_paper)
    real = PaperScheduleHistory

    def broken_factory(**kwargs):
        kwargs["actor_id"] = None  # NOT NULL column -> IntegrityError at commit
        return real(**kwargs)

    monkeypatch.setattr(paper_service, "PaperScheduleHistory", broken_factory)

    with pytest.raises(IntegrityError):
        paper_service.reschedule_paper_release(
            db_session, _as_current_user(admin_principal), uuid.UUID(locked_paper), datetime.now(timezone.utc) + timedelta(days=99)
        )

    assert _stored_release(db_session, locked_paper) == original
    assert _history_rows(db_session, locked_paper) == []
    assert _count_events(db_session, "PAPER_RELEASE_RESCHEDULED", locked_paper) == 0


def test_stale_session_cannot_record_a_wrong_previous_value(db_engine, db_session, admin_principal, locked_paper):
    """Another admin's reschedule committed after this session loaded the
    paper. The recorded 'previous' value must be the committed one, not
    the stale cached one (regression guard for populate_existing())."""
    pid = uuid.UUID(locked_paper)
    stale = db_session.get(Paper, pid)  # session now caches the original value
    t0 = _aware(stale.release_timestamp)

    other = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)()
    try:
        t1 = datetime.now(timezone.utc) + timedelta(days=200)
        p = other.get(Paper, pid)
        p.release_timestamp = t1
        other.commit()
    finally:
        other.close()

    t2 = datetime.now(timezone.utc) + timedelta(days=210)
    paper_service.reschedule_paper_release(db_session, _as_current_user(admin_principal), pid, t2)

    row = _history_rows(db_session, locked_paper)[0]
    assert _aware(row.previous_release_timestamp) == t1.replace(microsecond=t1.microsecond)
    assert _aware(row.previous_release_timestamp) != t0
    assert _aware(row.new_release_timestamp) == t2


def test_concurrent_reschedule_waits_on_row_lock_and_records_committed_previous(
    db_engine, db_session, admin_principal, locked_paper
):
    """Real two-transaction race. PostgreSQL only: SQLite ignores FOR UPDATE."""
    if db_engine.dialect.name != "postgresql":
        pytest.skip("row-level locking is only enforced by PostgreSQL")

    pid = uuid.UUID(locked_paper)
    Sess = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    holder = Sess()
    holder_paper = holder.query(Paper).filter(Paper.paper_id == pid).with_for_update().one()  # takes the lock

    t2 = datetime.now(timezone.utc) + timedelta(days=210)
    errors: list[BaseException] = []

    def worker():
        s = Sess()
        try:
            paper_service.reschedule_paper_release(s, _as_current_user(admin_principal), pid, t2)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s.close()

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(1.5)
    assert th.is_alive(), "worker should be blocked on the row lock"

    t1 = datetime.now(timezone.utc) + timedelta(days=200)
    holder_paper.release_timestamp = t1
    holder.add(
        PaperScheduleHistory(
            paper_id=pid,
            actor_id=admin_principal.user_id,
            action="RESCHEDULED",
            previous_release_timestamp=_aware(holder_paper.release_timestamp),
            new_release_timestamp=t1,
        )
    )
    holder.commit()
    holder.close()

    th.join(timeout=20)
    assert not th.is_alive()
    assert errors == []

    rows = _history_rows(db_session, locked_paper)
    assert len(rows) == 2
    last = rows[-1]
    assert _aware(last.previous_release_timestamp) == t1  # the winner's value, not the stale original
    assert _aware(last.new_release_timestamp) == t2
    assert _stored_release(db_session, locked_paper) == t2


def test_reschedule_of_a_paper_released_by_the_time_the_lock_is_acquired_is_rejected(
    db_session, admin_principal, released_paper
):
    with pytest.raises(ConflictException):
        paper_service.reschedule_paper_release(
            db_session, _as_current_user(admin_principal), uuid.UUID(released_paper), datetime.now(timezone.utc) + timedelta(days=5)
        )
    assert _history_rows(db_session, released_paper) == []


# ===========================================================================
# SCHEDULE HISTORY — READ ENDPOINT
# ===========================================================================


def test_admin_reads_history_in_chronological_order(client, admin_principal, locked_paper):
    values = [_future(70), _future(80), _future(95)]
    for v in values:
        assert _reschedule(client, admin_principal, locked_paper, v).status_code == 200

    resp = _get_history(client, admin_principal, locked_paper)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3 and body["page"] == 1
    assert [_parse(i["new_release_timestamp"]) for i in body["items"]] == [_parse(v) for v in values]
    item = body["items"][0]
    assert set(item.keys()) == {
        "history_id", "paper_id", "action", "previous_release_timestamp",
        "new_release_timestamp", "actor_id", "actor_username", "created_at",
    }
    assert item["paper_id"] == locked_paper
    assert item["actor_id"] == str(admin_principal.user_id)
    assert item["actor_username"] == admin_principal.username
    assert item["action"] == "RESCHEDULED"
    created = [_parse(i["created_at"]) for i in body["items"]]
    assert created == sorted(created)


def test_history_is_empty_for_a_paper_never_rescheduled(client, admin_principal, locked_paper):
    resp = _get_history(client, admin_principal, locked_paper)
    assert resp.status_code == 200
    assert resp.json()["items"] == [] and resp.json()["total"] == 0


def test_history_pagination(client, admin_principal, locked_paper):
    values = [_future(70), _future(80), _future(95)]
    for v in values:
        _reschedule(client, admin_principal, locked_paper, v)

    p1 = _get_history(client, admin_principal, locked_paper, page=1, page_size=2).json()
    p2 = _get_history(client, admin_principal, locked_paper, page=2, page_size=2).json()
    assert p1["total"] == 3 and len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert _parse(p2["items"][0]["new_release_timestamp"]) == _parse(values[2])
    assert _get_history(client, admin_principal, locked_paper, page_size=101).status_code == 422
    assert _get_history(client, admin_principal, locked_paper, page=0).status_code == 422


def test_history_access_control(client, admin_principal, centre_a, auditor_principal, locked_paper):  # noqa: F811
    url = f"/api/v1/papers/{locked_paper}/schedule-history"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get(url, headers=auth_header(centre_a)).status_code == 403
    assert client.get(url, headers=auth_header(auditor_principal)).status_code == 403
    assert client.get(url, headers=auth_header(admin_principal)).status_code == 200


def test_authorized_centre_still_cannot_read_history(client, admin_principal, centre_a, locked_paper):  # noqa: F811
    """IDOR: being authorized for the paper grants retrieval, not its schedule history."""
    client.post(
        f"/api/v1/papers/{locked_paper}/authorize",
        json={"centre_id": str(centre_a.centre_id)},
        headers=auth_header(admin_principal),
    )
    _reschedule(client, admin_principal, locked_paper, _future(77))
    r = _get_history(client, centre_a, locked_paper)
    assert r.status_code == 403
    assert "previous_release_timestamp" not in r.text


def test_history_unknown_and_malformed_paper_ids(client, admin_principal):
    assert _get_history(client, admin_principal, uuid.uuid4()).status_code == 404
    assert _get_history(client, admin_principal, "not-a-uuid").status_code == 422


def test_history_is_scoped_to_its_own_paper(client, admin_principal, locked_paper):
    other = _register_sample_paper(client, admin_principal, subject="Other", release_timestamp=_future(40)).json()["paper_id"]
    _reschedule(client, admin_principal, locked_paper, _future(77))
    assert _get_history(client, admin_principal, other).json()["items"] == []
    assert _get_history(client, admin_principal, locked_paper).json()["total"] == 1


def test_history_exposes_no_secrets_or_unrelated_metadata(client, db_session, admin_principal, locked_paper):
    _reschedule(client, admin_principal, locked_paper, _future(77))
    text = _get_history(client, admin_principal, locked_paper).text.lower()
    for forbidden in (
        "password", "otp", "jwt", "access_token", "bearer", "wrapped_dek", "file_nonce",
        "master_key", "file_reference", "sha256", "ledger_tx",
    ):
        assert forbidden not in text, forbidden

    cols = {c["name"] for c in sa_inspect(db_session.get_bind()).get_columns("paper_schedule_history")}
    assert cols == {
        "history_id", "paper_id", "actor_id", "action",
        "previous_release_timestamp", "new_release_timestamp", "created_at",
    }


def test_history_endpoint_is_documented_in_openapi(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/api/v1/papers/{paper_id}/schedule-history"]["get"]
    assert op["summary"]
    assert {"401", "403", "404"} <= set(op["responses"].keys())
    props = spec["components"]["schemas"]["PaperMetadataResponse"]["properties"]
    assert "lock_status" in props and "status" in props


def test_unhandled_error_in_history_read_does_not_leak_details(db_engine, admin_principal, locked_paper, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(paper_service, "list_schedule_history", boom)
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get(f"/api/v1/papers/{locked_paper}/schedule-history", headers=auth_header(admin_principal))
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500
    assert "secret-internal-detail" not in r.text
