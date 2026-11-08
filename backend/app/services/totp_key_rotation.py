"""
TOTP encryption-key rotation — Phase 7B.

Re-encrypts stored TOTP secrets from whatever key (and envelope version) they currently use to the
ACTIVE key, safely and resumably.

State model: each record's own envelope states which key encrypts it (v1 = "legacy"; v2 = explicit id),
and decryption accepts ANY key in the configured keyring. Therefore a database that is half-rotated is
still fully valid and fully usable, and the job can simply be run again: records already under the
target key are skipped (idempotent). Nothing else is changed: no record is deleted, and enrollment
state, last_used_step, role, password and sessions are untouched.

Phases of run():
  1. PREFLIGHT  - keyring loads; target key id is the configured active key; every record is
                  classified and TRIAL-DECRYPTED. If any record is malformed or its key is missing or
                  it fails authentication, NOTHING is written (returns preflight_failed).
  2. DRY RUN    - stops after preflight and reports what would change.
  3. MIGRATE    - in batches; each batch is ONE transaction (row-locked); per record: decrypt with the
                  old key, encrypt with the target key, DECRYPT AGAIN and compare before accepting.
                  A failing batch is rolled back and the run stops (earlier batches stay migrated;
                  re-running resumes).
  4. VERIFY     - every record is re-read and must decrypt with the TARGET KEY ALONE. Only then is the
                  old key provably no longer needed.

Output contains counts, key ids and user ids only; never keys, plaintext secrets or ciphertext.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.user_totp import UserTotp
from app.security import totp as totp_lib

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_PREFLIGHT = 2
EXIT_FAILED = 3


@dataclass
class RotationReport:
    status: str = "ok"  # ok | config_error | preflight_failed | migration_failed | verification_failed
    message: str = ""
    dry_run: bool = False
    target_key_id: str = ""
    from_key_id: str | None = None
    total_records: int = 0
    counts_by_key: dict[str, int] = field(default_factory=dict)
    already_current: int = 0
    to_migrate: int = 0
    migrated: int = 0
    left_untouched: int = 0  # under another key when --from-key-id selects a subset
    failures: list[tuple[str, str]] = field(default_factory=list)  # (user_id, reason code)
    verified_with_target_only: int | None = None

    @property
    def exit_code(self) -> int:
        return {"ok": EXIT_OK, "config_error": EXIT_CONFIG, "preflight_failed": EXIT_PREFLIGHT}.get(self.status, EXIT_FAILED)


def _records(db: Session) -> list[UserTotp]:
    return db.query(UserTotp).filter(UserTotp.secret_encrypted.isnot(None)).order_by(UserTotp.user_id).all()


def _classify(row: UserTotp, ring: totp_lib.Keyring) -> tuple[str | None, str | None]:
    """(key_id, failure_reason). Trial-decrypts so corruption/missing keys surface BEFORE any write."""
    try:
        _version, key_id = totp_lib.envelope_info(row.secret_encrypted)
        totp_lib.decrypt_secret(row.secret_encrypted, row.user_id, ring)
        return key_id, None
    except totp_lib.TotpKeyUnavailableError:
        try:
            return totp_lib.envelope_info(row.secret_encrypted)[1], "key_not_configured"
        except totp_lib.TotpDecryptError:
            return None, "malformed"
    except totp_lib.TotpDecryptError:
        try:
            return totp_lib.envelope_info(row.secret_encrypted)[1], "undecryptable"
        except totp_lib.TotpDecryptError:
            return None, "malformed"


def verify_all_under(db: Session, ring: totp_lib.Keyring, target_key_id: str) -> tuple[int, list[tuple[str, str]]]:
    """Every record must be a v2 envelope under `target_key_id` AND decrypt with that key alone."""
    only = ring.only(target_key_id)
    ok, bad = 0, []
    for row in _records(db):
        try:
            version, key_id = totp_lib.envelope_info(row.secret_encrypted)
            if version != "v2" or key_id != target_key_id:
                bad.append((str(row.user_id), "not_under_target_key"))
                continue
            totp_lib.decrypt_secret(row.secret_encrypted, row.user_id, only)
            ok += 1
        except totp_lib.TotpDecryptError:
            bad.append((str(row.user_id), "undecryptable_with_target_only"))
    return ok, bad


def run(
    db: Session,
    target_key_id: str,
    from_key_id: str | None = None,
    dry_run: bool = False,
    batch_size: int = 100,
    verify_only: bool = False,
) -> RotationReport:
    rep = RotationReport(dry_run=dry_run, target_key_id=target_key_id, from_key_id=from_key_id)

    # ---- 1. preflight: configuration
    try:
        ring = totp_lib.load_keyring()
    except totp_lib.TotpConfigError as exc:
        rep.status, rep.message = "config_error", str(exc)
        return rep
    if target_key_id not in ring.keys:
        rep.status, rep.message = "config_error", "--to-key-id is not a configured key id."
        return rep
    if target_key_id != ring.active_id:
        rep.status, rep.message = "config_error", "--to-key-id must equal TOTP_ACTIVE_KEY_ID so new writes and rotated records use the same key."
        return rep
    if from_key_id is not None and from_key_id not in ring.keys:
        rep.status, rep.message = "config_error", "--from-key-id is not a configured key id."
        return rep
    if from_key_id == target_key_id:
        rep.status, rep.message = "config_error", "--from-key-id and --to-key-id must differ."
        return rep
    if batch_size < 1 or batch_size > 1000:
        rep.status, rep.message = "config_error", "--batch-size must be between 1 and 1000."
        return rep

    # ---- verify-only: read-only proof that the target key alone suffices
    if verify_only:
        rows = _records(db)
        rep.total_records = len(rows)
        ok, bad = verify_all_under(db, ring, target_key_id)
        rep.verified_with_target_only, rep.failures = ok, bad
        rep.status = "ok" if not bad else "verification_failed"
        rep.message = "Every record decrypts with the target key alone." if not bad else "Some records still need the old key or are unreadable."
        return rep

    # ---- 1b. preflight: classify and trial-decrypt every record (read-only)
    rows = _records(db)
    rep.total_records = len(rows)
    plan: list[uuid.UUID] = []
    for row in rows:
        key_id, reason = _classify(row, ring)
        if reason is not None:
            rep.failures.append((str(row.user_id), reason))
            if key_id:
                rep.counts_by_key[key_id] = rep.counts_by_key.get(key_id, 0) + 1
            continue
        rep.counts_by_key[key_id] = rep.counts_by_key.get(key_id, 0) + 1
        version = totp_lib.envelope_info(row.secret_encrypted)[0]
        if key_id == target_key_id and version == "v2":
            rep.already_current += 1
        elif from_key_id is not None and key_id != from_key_id:
            rep.left_untouched += 1
        else:
            plan.append(row.user_id)
    rep.to_migrate = len(plan)
    db.rollback()  # end the read-only transaction

    if rep.failures:
        rep.status = "preflight_failed"
        rep.message = "Some records are malformed or cannot be decrypted with the configured keys. Nothing was changed."
        return rep
    if dry_run:
        rep.message = "Dry run: no changes were made."
        return rep

    # ---- 3. migrate, one transaction per batch
    for start in range(0, len(plan), batch_size):
        batch = plan[start : start + batch_size]
        try:
            locked = (
                db.query(UserTotp)
                .filter(UserTotp.user_id.in_(batch))
                .order_by(UserTotp.user_id)
                .with_for_update()
                .all()
            )
            for row in locked:
                if row.secret_encrypted is None:
                    continue
                version, key_id = totp_lib.envelope_info(row.secret_encrypted)
                if key_id == target_key_id and version == "v2":
                    continue  # another run/process already did it
                plaintext = totp_lib.decrypt_secret(row.secret_encrypted, row.user_id, ring)
                new_blob = totp_lib.encrypt_secret(plaintext, row.user_id, ring)
                if totp_lib.decrypt_secret(new_blob, row.user_id, ring) != plaintext:
                    raise totp_lib.TotpDecryptError("re-encryption verification failed")
                row.secret_encrypted = new_blob
                rep.migrated += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001 - report the class only, never data
            db.rollback()
            rep.status = "migration_failed"
            rep.message = f"A batch failed and was rolled back ({type(exc).__name__}). Earlier batches remain migrated; re-run to resume."
            logger.error("TOTP key rotation batch failed: %s", type(exc).__name__)
            return rep

    # ---- 4. verify
    still_old = [r for r in _records(db)]
    if from_key_id is None:
        ok, bad = verify_all_under(db, ring, target_key_id)
        rep.verified_with_target_only = ok
        if bad:
            rep.failures, rep.status = bad, "verification_failed"
            rep.message = "Verification failed: some records do not decrypt with the target key alone."
            return rep
    else:
        remaining = [r for r in still_old if totp_lib.envelope_info(r.secret_encrypted)[1] == from_key_id]
        if remaining:
            rep.failures = [(str(r.user_id), "still_under_from_key") for r in remaining]
            rep.status, rep.message = "verification_failed", "Some records are still under the --from-key-id key."
            return rep
    rep.message = "Rotation complete and verified."
    return rep
