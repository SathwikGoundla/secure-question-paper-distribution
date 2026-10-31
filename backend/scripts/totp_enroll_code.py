"""
Phase 7A — server-operator CLI: issue a ONE-TIME authenticator enrollment code.

This is the bootstrap / recovery path that does not depend on anyone being
able to log in: it needs access to the server and its database, which is the
trust root of the system. Use it to
  * enroll the FIRST Admin (nobody can log in yet, so no Admin can issue a code),
  * enroll existing users after upgrading from Phase 6I or earlier,
  * recover an Admin who lost their authenticator (Admins cannot reset
    themselves through the API, by design).

Usage (from backend/, same environment as the API):
    python -m scripts.totp_enroll_code --username admin1

What it does (identical to the Admin API): wipes any existing authenticator of
that user, revokes that user's active sessions, stores only a SHA-256 of a new
random code, and PRINTS THE CODE ONCE. Give it to the user over a trusted
channel; they open the enrollment page, enter username + password + code, scan
the QR, and confirm. The code expires (TOTP_ENROLLMENT_CODE_TTL_HOURS, default
24 h) and is single use. The code is never logged and never stored in clear.
No TOTP secret is involved at this step.
"""

import argparse
import logging
import sys

from app.database import SessionLocal
from app.logging_config import configure_logging
from app.models.user import User
from app.services import totp_service

configure_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a one-time authenticator enrollment code (Phase 7A).")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username, User.is_active == True).first()  # noqa: E712
        if user is None:
            logger.error("No active user named '%s'.", args.username)
            sys.exit(1)
        code, expires_at = totp_service.issue_enrollment_code(db, user, issued_by=None)
    finally:
        db.close()

    # Printed to stdout on purpose (not through the logger) so it is not captured in log files.
    print(f"Enrollment code for '{args.username}': {code}")
    print(f"Valid until: {expires_at.isoformat()}  (single use). Any previous authenticator was removed.")


if __name__ == "__main__":
    main()
