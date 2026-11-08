"""
Phase 7B — TOTP encryption keyring and key rotation.

Phase 7A records (envelope "v1", encrypted with the single TOTP_ENCRYPTION_KEY) are produced here with
an independent re-implementation of the 7A scheme, so compatibility is tested against the real 7A
format and not against the new code's own output.
"""

import base64
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import sessionmaker

import app.services.totp_key_rotation as rotation
from app.config import get_settings
from app.models.user import User
from app.models.user_totp import UserTotp
from app.security import totp as t
from app.services import totp_service
from tests.test_totp_auth import PASSWORD, _enroll, _make_user, _sign_in, clock, totp_mode  # noqa: F401


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def _ring(monkeypatch, legacy: str | None, keys: str = "", active: str = "") -> None:
    s = get_settings()
    monkeypatch.setattr(s, "TOTP_ENCRYPTION_KEY", legacy or "")
    monkeypatch.setattr(s, "TOTP_ENCRYPTION_KEYS", keys)
    monkeypatch.setattr(s, "TOTP_ACTIVE_KEY_ID", active)


def _v1_blob(secret: str, user_id: uuid.UUID, key_b64: str) -> bytes:
    """The exact Phase 7A format: b"v1" + nonce + AES-256-GCM(ct||tag), AAD = user id bytes."""
    nonce = os.urandom(12)
    return b"v1" + nonce + AESGCM(base64.b64decode(key_b64)).encrypt(nonce, secret.encode(), user_id.bytes)


def _v2_blob(secret: str, user_id: uuid.UUID, key_id: str, key_b64: str) -> bytes:
    ring = t.Keyring({key_id: base64.b64decode(key_b64)}, key_id)
    return t.encrypt_secret(secret, user_id, ring)


def _put(db, user, blob, confirmed=True) -> UserTotp:
    row = UserTotp(
        user_id=user.user_id,
        secret_encrypted=blob,
        confirmed_at=datetime.now(timezone.utc) if confirmed else None,
        last_used_step=7 if confirmed else None,
    )
    db.add(row)
    db.commit()
    return row


def _blobs(db) -> dict:
    db.expire_all()
    return {r.user_id: bytes(r.secret_encrypted) for r in db.query(UserTotp).filter(UserTotp.secret_encrypted.isnot(None)).all()}


@pytest.fixture()
def clean_totp_table(db_session):
    """These tests reason about the WHOLE table, so start (and leave) it empty."""
    db_session.query(UserTotp).delete()
    db_session.commit()
    yield
    db_session.query(UserTotp).delete()
    db_session.commit()


# ===========================================================================
# Keyring configuration
# ===========================================================================


def test_single_legacy_key_is_the_phase_7a_configuration(monkeypatch):
    k = _key()
    _ring(monkeypatch, k)
    ring = t.load_keyring()
    assert set(ring.keys) == {"legacy"} and ring.active_id == "legacy"
    assert t.load_encryption_key() == base64.b64decode(k)  # Phase 7A name still works


def test_several_keys_require_an_explicit_active_id(monkeypatch):
    old, new = _key(), _key()
    _ring(monkeypatch, old, f"k2={new}")
    with pytest.raises(t.TotpConfigError) as exc:
        t.load_keyring()
    assert "TOTP_ACTIVE_KEY_ID" in str(exc.value)
    _ring(monkeypatch, old, f"k2={new}", "k2")
    ring = t.load_keyring()
    assert set(ring.keys) == {"legacy", "k2"} and ring.active_id == "k2"
    _ring(monkeypatch, None, f"k2={new}")  # a single named key needs no active id
    assert t.load_keyring().active_id == "k2"


@pytest.mark.parametrize(
    "legacy,keys,active,needle",
    [
        (None, "", "", "not configured"),
        ("%%%", "", "", "base64"),
        (base64.b64encode(b"short").decode(), "", "", "32 bytes"),
        ("OLD", "k2=%%%", "k2", "base64"),
        ("OLD", "k2=" + base64.b64encode(b"short").decode(), "k2", "32 bytes"),
        ("OLD", "bad id=NEW", "legacy", "id=base64key"),
        ("OLD", "k2", "legacy", "id=base64key"),
        ("OLD", "legacy=NEW", "legacy", "reserved"),
        ("OLD", "k2=NEW,k2=NEW2", "k2", "Duplicate"),
        ("OLD", "k2=OLD", "k2", "distinct"),
        ("OLD", "k2=NEW", "nope", "does not match"),
    ],
)
def test_invalid_keyrings_are_refused_without_echoing_key_material(monkeypatch, legacy, keys, active, needle):
    old, new, new2 = _key(), _key(), _key()

    def sub(x):
        return x.replace("NEW2", new2).replace("NEW", new).replace("OLD", old) if x else x

    _ring(monkeypatch, sub(legacy) if legacy else None, sub(keys), active)
    with pytest.raises(t.TotpConfigError) as exc:
        t.load_keyring()
    assert needle in str(exc.value)
    for material in (old, new, new2):
        assert material not in str(exc.value)


def test_no_configured_key_may_equal_the_paper_master_key(monkeypatch):
    shared = _key()
    monkeypatch.setattr(get_settings(), "QUESTION_PAPER_MASTER_KEY", shared)
    for legacy, keys, active in ((shared, "", ""), (_key(), f"k2={shared}", "k2")):
        _ring(monkeypatch, legacy, keys, active)
        with pytest.raises(t.TotpConfigError) as exc:
            t.load_keyring()
        assert "differ" in str(exc.value)


# ===========================================================================
# Envelope compatibility and safety
# ===========================================================================


def test_phase_7a_records_remain_decryptable_and_are_never_reinterpreted(monkeypatch):
    k = _key()
    _ring(monkeypatch, k)
    uid, secret = uuid.uuid4(), t.generate_secret()
    v1 = _v1_blob(secret, uid, k)
    assert t.envelope_info(v1) == ("v1", "legacy")
    assert t.decrypt_secret(v1, uid) == secret
    with pytest.raises(t.TotpDecryptError):
        t.decrypt_secret(v1, uuid.uuid4())  # still bound to the user


def test_new_encryptions_are_v2_under_the_active_key_and_old_keys_still_decrypt(monkeypatch):
    old, new = _key(), _key()
    uid, secret = uuid.uuid4(), t.generate_secret()
    _ring(monkeypatch, old)
    old_blob = _v1_blob(secret, uid, old)
    _ring(monkeypatch, old, f"k2={new}", "k2")
    fresh = t.encrypt_secret(secret, uid)
    assert t.envelope_info(fresh) == ("v2", "k2")
    assert secret.encode() not in fresh
    assert t.decrypt_secret(fresh, uid) == secret and t.decrypt_secret(old_blob, uid) == secret


def test_v2_envelope_binds_user_and_key_id_and_detects_tampering(monkeypatch):
    k = _key()
    _ring(monkeypatch, None, f"k1={k}", "k1")
    uid, secret = uuid.uuid4(), t.generate_secret()
    blob = t.encrypt_secret(secret, uid)
    with pytest.raises(t.TotpDecryptError):
        t.decrypt_secret(blob, uuid.uuid4())
    flipped = bytearray(blob)
    flipped[-1] ^= 1
    with pytest.raises(t.TotpDecryptError):
        t.decrypt_secret(bytes(flipped), uid)
    # Re-labelling the key id (k1 -> k9 with the same length) is detected by the authenticated header.
    relabelled = bytearray(blob)
    relabelled[3:5] = b"k9"
    _ring(monkeypatch, None, f"k1={k},k9={_key()}", "k1")  # k9 exists, but it is a different key and AAD differs
    with pytest.raises(t.TotpDecryptError):
        t.decrypt_secret(bytes(relabelled), uid)
    for junk in (b"", b"v3" + b"x" * 40, b"v2\x00" + b"x" * 40, b"v2\x40" + b"x" * 10):
        with pytest.raises(t.TotpDecryptError):
            t.decrypt_secret(junk, uid)


def test_a_record_whose_key_is_not_configured_is_reported_distinctly_and_never_decrypts(monkeypatch):
    old, new = _key(), _key()
    uid, secret = uuid.uuid4(), t.generate_secret()
    _ring(monkeypatch, None, f"k1={old}", "k1")
    blob = t.encrypt_secret(secret, uid)
    _ring(monkeypatch, None, f"k2={new}", "k2")  # k1 was retired too early
    with pytest.raises(t.TotpKeyUnavailableError):
        t.decrypt_secret(blob, uid)
    # And a WRONG key under the same id fails authentication, not "unavailable".
    _ring(monkeypatch, None, f"k1={new}", "k1")
    with pytest.raises(t.TotpDecryptError) as exc:
        t.decrypt_secret(blob, uid)
    assert not isinstance(exc.value, t.TotpKeyUnavailableError)


def test_new_enrollments_use_the_active_key_and_login_still_works(client, db_session, clock, totp_mode, monkeypatch):
    old, new = _key(), _key()
    _ring(monkeypatch, old, f"k2={new}", "k2")
    user = _make_user(db_session)
    secret = _enroll(client, db_session, clock, user)
    db_session.expire_all()
    assert t.envelope_info(db_session.get(UserTotp, user.user_id).secret_encrypted) == ("v2", "k2")
    assert _sign_in(client, user, secret, clock).status_code == 200


def test_login_fails_safely_when_the_records_key_is_unavailable_or_wrong(client, db_session, clock, totp_mode, monkeypatch):
    old, new = _key(), _key()
    _ring(monkeypatch, old)
    user = _make_user(db_session)
    secret = t.generate_secret()
    _put(db_session, user, _v1_blob(secret, user.user_id, old))
    assert _sign_in(client, user, secret, clock).status_code == 200
    clock.advance(30)
    _ring(monkeypatch, new)  # a DIFFERENT key replaced "legacy" without re-encrypting
    resp = _sign_in(client, user, secret, clock)
    assert resp.status_code == 401 and "access_token" not in resp.text


# ===========================================================================
# Rotation
# ===========================================================================


def _setup_three(db_session, monkeypatch, clean_totp_table=None):
    old, new = _key(), _key()
    _ring(monkeypatch, old)
    users, secrets_ = [], {}
    for _ in range(3):
        u = _make_user(db_session)
        s = t.generate_secret()
        _put(db_session, u, _v1_blob(s, u.user_id, old))
        users.append(u)
        secrets_[u.user_id] = s
    _ring(monkeypatch, old, f"k2={new}", "k2")
    return old, new, users, secrets_


def test_dry_run_changes_nothing(db_session, monkeypatch, clean_totp_table):
    _o, _n, users, _s = _setup_three(db_session, monkeypatch)
    before = _blobs(db_session)
    rep = rotation.run(db_session, "k2", dry_run=True)
    assert rep.status == "ok" and rep.dry_run and rep.exit_code == 0
    assert rep.total_records == 3 and rep.to_migrate == 3 and rep.migrated == 0
    assert rep.counts_by_key == {"legacy": 3}
    assert _blobs(db_session) == before


def test_rotation_reencrypts_everything_and_preserves_all_state(client, db_session, clock, totp_mode, monkeypatch, clean_totp_table):
    _o, new, users, secrets_ = _setup_three(db_session, monkeypatch)
    snapshot = {
        r.user_id: (r.confirmed_at, r.last_used_step, r.enrollment_code_hash, r.enrollment_failed_attempts)
        for r in db_session.query(UserTotp).all()
    }
    pw_hashes = {u.user_id: u.password_hash for u in db_session.query(User).filter(User.user_id.in_([x.user_id for x in users]))}
    roles = {u.user_id: u.role_id for u in db_session.query(User).filter(User.user_id.in_([x.user_id for x in users]))}

    rep = rotation.run(db_session, "k2", batch_size=2)
    assert rep.status == "ok" and rep.exit_code == 0
    assert rep.migrated == 3 and rep.verified_with_target_only == 3

    db_session.expire_all()
    rows = db_session.query(UserTotp).all()
    assert len(rows) == 3
    for r in rows:
        assert t.envelope_info(r.secret_encrypted) == ("v2", "k2")
        assert t.decrypt_secret(r.secret_encrypted, r.user_id) == secrets_[r.user_id]
        assert (r.confirmed_at, r.last_used_step, r.enrollment_code_hash, r.enrollment_failed_attempts) == snapshot[r.user_id]
    for u in db_session.query(User).filter(User.user_id.in_(list(secrets_))):
        assert u.password_hash == pw_hashes[u.user_id] and u.role_id == roles[u.user_id]
    # The new key ALONE now suffices (old key retired) and users can still sign in with the SAME authenticators.
    _ring(monkeypatch, None, f"k2={new}", "k2")
    for u in users:
        assert _sign_in(client, u, secrets_[u.user_id], clock).status_code == 200
        clock.advance(30)


def test_rotation_is_idempotent(db_session, monkeypatch, clean_totp_table):
    _setup_three(db_session, monkeypatch)
    assert rotation.run(db_session, "k2").migrated == 3
    before = _blobs(db_session)
    again = rotation.run(db_session, "k2")
    assert again.status == "ok" and again.migrated == 0 and again.already_current == 3 and again.to_migrate == 0
    assert _blobs(db_session) == before  # byte-identical: nothing was re-encrypted


def test_from_key_id_limits_the_scope(db_session, monkeypatch, clean_totp_table):
    old, new = _key(), _key()
    mid = _key()
    _ring(monkeypatch, old, f"k1={mid},k2={new}", "k2")
    a, b = _make_user(db_session), _make_user(db_session)
    sa, sb = t.generate_secret(), t.generate_secret()
    _put(db_session, a, _v1_blob(sa, a.user_id, old))
    _put(db_session, b, _v2_blob(sb, b.user_id, "k1", mid))
    b_before = _blobs(db_session)[b.user_id]
    rep = rotation.run(db_session, "k2", from_key_id="legacy")
    assert rep.status == "ok" and rep.migrated == 1 and rep.left_untouched == 1
    blobs = _blobs(db_session)
    assert t.envelope_info(blobs[a.user_id]) == ("v2", "k2") and blobs[b.user_id] == b_before


def test_a_v2_record_under_an_older_key_is_rotated_too(db_session, monkeypatch, clean_totp_table):
    k1, k2 = _key(), _key()
    _ring(monkeypatch, None, f"k1={k1},k2={k2}", "k2")
    u = _make_user(db_session)
    s = t.generate_secret()
    _put(db_session, u, _v2_blob(s, u.user_id, "k1", k1))
    assert rotation.run(db_session, "k2").migrated == 1
    assert t.envelope_info(_blobs(db_session)[u.user_id]) == ("v2", "k2")


@pytest.mark.parametrize("kind", ["corrupt", "malformed", "key_not_configured"])
def test_preflight_aborts_without_any_change_when_a_record_is_bad(db_session, monkeypatch, clean_totp_table, kind):
    old, new, users, _s = _setup_three(db_session, monkeypatch)
    victim = _make_user(db_session)
    s = t.generate_secret()
    if kind == "corrupt":
        blob = bytearray(_v1_blob(s, victim.user_id, old))
        blob[-3] ^= 0xFF
        blob = bytes(blob)
    elif kind == "malformed":
        blob = b"this-is-not-an-envelope-at-all"
    else:
        blob = _v2_blob(s, victim.user_id, "gone", _key())
    _put(db_session, victim, blob)
    before = _blobs(db_session)
    rep = rotation.run(db_session, "k2")
    assert rep.status == "preflight_failed" and rep.exit_code == 2 and rep.migrated == 0
    assert [uid for uid, _r in rep.failures] == [str(victim.user_id)]
    assert _blobs(db_session) == before  # not even the healthy records were touched


@pytest.mark.parametrize(
    "kwargs,needle",
    [
        ({"target_key_id": "nope"}, "not a configured"),
        ({"target_key_id": "legacy"}, "must equal TOTP_ACTIVE_KEY_ID"),
        ({"target_key_id": "k2", "from_key_id": "ghost"}, "--from-key-id"),
        ({"target_key_id": "k2", "from_key_id": "k2"}, "must differ"),
        ({"target_key_id": "k2", "batch_size": 0}, "batch-size"),
        ({"target_key_id": "k2", "batch_size": 5000}, "batch-size"),
    ],
)
def test_configuration_errors_exit_1_and_change_nothing(db_session, monkeypatch, clean_totp_table, kwargs, needle):
    _setup_three(db_session, monkeypatch)
    before = _blobs(db_session)
    rep = rotation.run(db_session, **kwargs)
    assert rep.status == "config_error" and rep.exit_code == 1 and needle in rep.message
    assert _blobs(db_session) == before


def test_missing_key_configuration_fails_safely(db_session, monkeypatch, clean_totp_table):
    _setup_three(db_session, monkeypatch)
    before = _blobs(db_session)
    _ring(monkeypatch, None)
    rep = rotation.run(db_session, "k2")
    assert rep.status == "config_error" and rep.exit_code == 1
    assert _blobs(db_session) == before


def test_interrupted_rotation_leaves_a_valid_mixed_state_and_can_be_resumed(client, db_session, clock, totp_mode, monkeypatch, clean_totp_table):
    old, new, users, secrets_ = _setup_three(db_session, monkeypatch)
    real_encrypt, calls = t.encrypt_secret, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash mid-rotation")
        return real_encrypt(*a, **k)

    monkeypatch.setattr(t, "encrypt_secret", flaky)
    rep = rotation.run(db_session, "k2", batch_size=1)
    assert rep.status == "migration_failed" and rep.exit_code == 3 and rep.migrated == 1
    mixed = _blobs(db_session)
    kinds = sorted(t.envelope_info(b) for b in mixed.values())
    assert kinds == [("v1", "legacy"), ("v1", "legacy"), ("v2", "k2")]
    # Every record still decrypts and every user can still sign in (mixed state is valid).
    for u in users:
        assert t.decrypt_secret(mixed[u.user_id], u.user_id) == secrets_[u.user_id]
    assert _sign_in(client, users[0], secrets_[users[0].user_id], clock).status_code == 200

    monkeypatch.setattr(t, "encrypt_secret", real_encrypt)
    resumed = rotation.run(db_session, "k2", batch_size=1)
    assert resumed.status == "ok" and resumed.migrated == 2 and resumed.already_current == 1
    assert all(t.envelope_info(b) == ("v2", "k2") for b in _blobs(db_session).values())


def test_a_reencryption_that_does_not_verify_is_never_committed(db_session, monkeypatch, clean_totp_table):
    _setup_three(db_session, monkeypatch)
    before = _blobs(db_session)
    real = t.encrypt_secret
    monkeypatch.setattr(t, "encrypt_secret", lambda secret, uid, ring=None: real(t.generate_secret(), uid, ring))  # wrong plaintext
    rep = rotation.run(db_session, "k2")
    assert rep.status == "migration_failed" and rep.migrated == 0
    assert _blobs(db_session) == before


def test_verify_only_proves_the_target_key_alone_suffices(db_session, monkeypatch, clean_totp_table):
    old, new, users, _s = _setup_three(db_session, monkeypatch)
    pre = rotation.run(db_session, "k2", verify_only=True)
    assert pre.status == "verification_failed" and pre.exit_code == 3 and len(pre.failures) == 3
    assert rotation.run(db_session, "k2").status == "ok"
    post = rotation.run(db_session, "k2", verify_only=True)
    assert post.status == "ok" and post.verified_with_target_only == 3 and not post.failures
    _ring(monkeypatch, None, f"k2={new}", "k2")  # the old key is retired
    assert rotation.run(db_session, "k2", verify_only=True).status == "ok"


def test_retiring_the_old_key_before_rotation_is_caught(db_session, monkeypatch, clean_totp_table):
    old, new, users, _s = _setup_three(db_session, monkeypatch)
    _ring(monkeypatch, None, f"k2={new}", "k2")
    rep = rotation.run(db_session, "k2")
    assert rep.status == "preflight_failed" and {r for _u, r in rep.failures} == {"key_not_configured"}


# ===========================================================================
# CLI and leakage
# ===========================================================================


def test_cli_exit_codes_and_output_contain_no_key_secret_or_ciphertext(db_session, monkeypatch, clean_totp_table, capsys, caplog):
    from scripts import rotate_totp_encryption_key as cli

    old, new, users, secrets_ = _setup_three(db_session, monkeypatch)
    blobs = _blobs(db_session)
    with caplog.at_level(logging.DEBUG):
        assert cli.main(["--to-key-id", "k2", "--dry-run"]) == 0
        assert cli.main(["--to-key-id", "k2", "--verify-only"]) == 3
        assert cli.main(["--to-key-id", "legacy"]) == 1
        assert cli.main(["--to-key-id", "k2"]) == 0
        assert cli.main(["--to-key-id", "k2", "--verify-only"]) == 0
    out = capsys.readouterr().out + caplog.text
    assert "currently under key 'legacy': 3" in out and "verified decryptable with the target key alone: 3" in out
    after = _blobs(db_session)
    leaks = [old, new, *secrets_.values(), *[b.hex() for b in blobs.values()], *[b.hex() for b in after.values()]]
    for needle in leaks:
        assert needle not in out
    for needle in (*blobs.values(), *after.values()):
        assert base64.b64encode(needle).decode() not in out


def test_cli_reports_problem_records_by_user_id_and_reason_only(db_session, monkeypatch, clean_totp_table, capsys):
    from scripts import rotate_totp_encryption_key as cli

    _setup_three(db_session, monkeypatch)
    bad = _make_user(db_session)
    _put(db_session, bad, b"garbage-garbage-garbage-garbage-garbage")
    assert cli.main(["--to-key-id", "k2"]) == 2
    out = capsys.readouterr().out
    assert f"user_id={bad.user_id} reason=malformed" in out and "garbage" not in out


# ===========================================================================
# PostgreSQL-only: concurrent rotation runs
# ===========================================================================


def test_two_concurrent_rotation_runs_migrate_each_record_exactly_once(db_engine, db_session, monkeypatch, clean_totp_table):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("row-level locking is only enforced by PostgreSQL")
    old, new = _key(), _key()
    _ring(monkeypatch, old, f"k2={new}", "k2")
    secrets_ = {}
    for _ in range(12):
        u = _make_user(db_session)
        s = t.generate_secret()
        _put(db_session, u, _v1_blob(s, u.user_id, old))
        secrets_[u.user_id] = s

    Sess = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    reports = []
    barrier = threading.Barrier(2)

    def worker():
        s = Sess()
        try:
            barrier.wait(timeout=10)
            reports.append(rotation.run(s, "k2", batch_size=3))
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert [r.status for r in reports] == ["ok", "ok"], [r.message for r in reports]
    assert sum(r.migrated for r in reports) == 12  # no record was re-encrypted twice
    blobs = _blobs(db_session)
    assert all(t.envelope_info(b) == ("v2", "k2") for b in blobs.values())
    assert all(t.decrypt_secret(b, uid) == secrets_[uid] for uid, b in blobs.items())
