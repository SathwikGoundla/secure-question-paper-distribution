"""
User provisioning CLI (Phase 2).

FLAGGED DESIGN DECISION — read before use: the approved LLD API table
(Section 6, API-01 through API-15) does NOT define a "create user"
REST endpoint. users (LLD 7.1) is a table, but account provisioning
itself is not specified as a public API in PRD/SRS/HLD/LLD — consistent
with this being an exam-security system where accounts are provisioned
by an administrator out-of-band, not self-registered.

Rather than inventing an endpoint the LLD doesn't define, this is a
local admin-only CLI script. If the project owner later decides a real
POST /admin/users (or similar) endpoint IS wanted, that should go
through the same document-update process as the Faculty-Review
Addendum, not be silently added here.

Usage:
    cd backend
    python -m scripts.create_user --username admin1 --password 'Str0ng!Pass' --role Admin
    python -m scripts.create_user --username centre1 --password 'Str0ng!Pass' --role "Examination Centre" --centre-id <uuid>

Passwords are hashed immediately (bcrypt, app/security/password.py) —
the plaintext value is never written to disk or logged.
"""

import argparse
import logging
import sys
import uuid

from app.database import SessionLocal
from app.logging_config import configure_logging
from app.models.exam_centre import ExamCentre
from app.models.role import Role
from app.models.user import User
from app.security.password import hash_password

configure_logging()
logger = logging.getLogger(__name__)


def create_user(username: str, password: str, role_name: str, centre_id: str | None) -> None:
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.role_name == role_name).first()
        if role is None:
            logger.error(
                "Role '%s' does not exist. Run 'python -m scripts.init_db' first "
                "to seed the approved roles (Admin, Examination Centre, Auditor).",
                role_name,
            )
            sys.exit(1)

        if db.query(User).filter(User.username == username).first() is not None:
            logger.error("Username '%s' already exists.", username)
            sys.exit(1)

        centre_uuid = None
        if centre_id:
            centre_uuid = uuid.UUID(centre_id)
            if db.get(ExamCentre, centre_uuid) is None:
                logger.error("exam_centres row with centre_id=%s does not exist.", centre_id)
                sys.exit(1)

        if role_name == "Examination Centre" and centre_uuid is None:
            logger.error("--centre-id is required when --role is 'Examination Centre'.")
            sys.exit(1)

        user = User(
            username=username,
            password_hash=hash_password(password),  # plaintext never stored (SEC-010)
            role_id=role.role_id,
            centre_id=centre_uuid,
        )
        db.add(user)
        db.commit()
        logger.info("Created user '%s' (role=%s, user_id=%s)", username, role_name, user.user_id)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a user account (Phase 2 CLI, dev/demo tool).")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True, help="Plaintext password — hashed immediately, never stored.")
    parser.add_argument("--role", required=True, choices=["Admin", "Examination Centre", "Auditor"])
    parser.add_argument("--centre-id", required=False, default=None, help="Required if --role is 'Examination Centre'.")
    args = parser.parse_args()

    create_user(args.username, args.password, args.role, args.centre_id)
    print(
        "Next (Phase 7A): this account cannot sign in until an authenticator is enrolled. Run\n"
        f"    python -m scripts.totp_enroll_code --username {args.username}\n"
        "and give the printed one-time code to the user (or have an Admin issue one)."
    )


if __name__ == "__main__":
    main()
