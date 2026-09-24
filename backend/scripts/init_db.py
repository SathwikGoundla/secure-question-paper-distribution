"""
Development/demo-only database initialisation.

Creates every table defined in app/models/*.py directly from SQLAlchemy
metadata (Base.metadata.create_all). This is NOT a migration tool — for
a real project a proper migration framework (e.g. Alembic) should be
introduced before any schema changes after the first deployment. That
is explicitly out of scope for Phase 1 and is listed as a known
limitation in docs/PHASE1_IMPLEMENTATION_STATUS.md.

Phase 2 addition: also seeds the fixed roles set (LLD 7.2 / SRS Section
4: Admin, Examination Centre, Auditor) idempotently — authentication
cannot function without at least these rows existing, and no role
outside this approved set is introduced. This is DATA seeding, not a
schema change.

Usage:
    cd backend
    python -m scripts.init_db
"""

import logging

from app.database import Base, SessionLocal, engine
from app.logging_config import configure_logging
from app.models.role import Role

# Importing app.models registers every table on Base.metadata.
import app.models  # noqa: F401

configure_logging()
logger = logging.getLogger(__name__)

# LLD 7.2 / SRS Section 4 — the ONLY approved roles. No new role is introduced.
APPROVED_ROLES = ["Admin", "Examination Centre", "Auditor"]


def _seed_roles() -> None:
    db = SessionLocal()
    try:
        existing = {r.role_name for r in db.query(Role).all()}
        created = []
        for role_name in APPROVED_ROLES:
            if role_name not in existing:
                db.add(Role(role_name=role_name))
                created.append(role_name)
        if created:
            db.commit()
            logger.info("Seeded roles: %s", ", ".join(created))
        else:
            logger.info("Roles already seeded: %s", ", ".join(APPROVED_ROLES))
    finally:
        db.close()


def main() -> None:
    logger.info("Creating tables (if not already present) on the configured database...")
    Base.metadata.create_all(bind=engine)
    table_names = sorted(Base.metadata.tables.keys())
    logger.info("Done. %d tables ensured: %s", len(table_names), ", ".join(table_names))
    _seed_roles()


if __name__ == "__main__":
    main()
