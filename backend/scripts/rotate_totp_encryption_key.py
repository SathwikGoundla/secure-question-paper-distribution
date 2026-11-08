"""
Phase 7B — operator utility: rotate the TOTP encryption key (re-encrypt stored secrets).

Typical procedure (full runbook in backend/README.md section 6):
  1. Generate a NEW key:      python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
  2. Configure the keyring, keeping the OLD key available:
        TOTP_ENCRYPTION_KEY=<old key>                 # still the key with id "legacy"
        TOTP_ENCRYPTION_KEYS=k2=<new key>
        TOTP_ACTIVE_KEY_ID=k2
     (restart the API: new secrets are now encrypted with k2; old records still decrypt)
  3. Preview (changes nothing):  python -m scripts.rotate_totp_encryption_key --to-key-id k2 --dry-run
  4. Rotate:                     python -m scripts.rotate_totp_encryption_key --to-key-id k2
  5. Prove the new key alone suffices (read-only):
                                 python -m scripts.rotate_totp_encryption_key --to-key-id k2 --verify-only
  6. Only after step 5 succeeds, and only after your backups no longer need it, retire the old key.

Exit codes: 0 success (or dry-run/verify OK) | 1 configuration/usage error | 2 preflight failure
(malformed/undecryptable records; nothing was changed) | 3 migration or verification failure.
The output lists counts, key ids and user ids only; never keys, secrets or ciphertext.
"""

import argparse
import logging
import sys

from app.database import SessionLocal
from app.logging_config import configure_logging
from app.services import totp_key_rotation

configure_logging()
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rotate the TOTP encryption key (re-encrypt stored secrets).")
    parser.add_argument("--to-key-id", required=True, help="Key id to encrypt with; must equal TOTP_ACTIVE_KEY_ID.")
    parser.add_argument("--from-key-id", default=None, help="Only re-encrypt records currently under this key id (default: all not under the target).")
    parser.add_argument("--dry-run", action="store_true", help="Preflight only; change nothing.")
    parser.add_argument("--verify-only", action="store_true", help="Read-only: prove every record decrypts with the target key alone.")
    parser.add_argument("--batch-size", type=int, default=100, help="Records per transaction (1-1000).")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        rep = totp_key_rotation.run(
            db,
            target_key_id=args.to_key_id,
            from_key_id=args.from_key_id,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            verify_only=args.verify_only,
        )
    finally:
        db.close()

    print(f"status: {rep.status}" + (" (dry run)" if rep.dry_run else ""))
    print(f"message: {rep.message}")
    print(f"target key id: {rep.target_key_id}" + (f"   from key id: {rep.from_key_id}" if rep.from_key_id else ""))
    print(f"records with a stored secret: {rep.total_records}")
    for key_id, count in sorted(rep.counts_by_key.items()):
        print(f"  currently under key '{key_id}': {count}")
    print(f"already current: {rep.already_current}   to migrate: {rep.to_migrate}   migrated now: {rep.migrated}   left untouched: {rep.left_untouched}")
    if rep.verified_with_target_only is not None:
        print(f"verified decryptable with the target key alone: {rep.verified_with_target_only}")
    for user_id, reason in rep.failures:
        print(f"  PROBLEM user_id={user_id} reason={reason}")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
