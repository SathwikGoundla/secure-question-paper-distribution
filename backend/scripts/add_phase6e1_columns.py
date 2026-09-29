"""
Phase 6E-1 schema helper — adds the new failed_attempts column to an
ALREADY-EXISTING otp_codes table.

Why this script exists: this project does not use Alembic (a Phase 1
decision — see docs/PHASE1_IMPLEMENTATION_STATUS.md), and
Base.metadata.create_all() (used by scripts/init_db.py) only CREATES
tables that don't exist yet — it never ALTERs an existing table's
columns. Anyone who set up their database before Phase 6E-1 will have
an otp_codes table missing the column defined in app/models/otp_code.py.
This follows the exact same pattern already established by
scripts/add_phase3_columns.py and scripts/add_phase5d_columns.py — a
small, explicit, idempotent (safe to re-run) statement list for
exactly the one column this phase adds.

If you are setting up the database for the FIRST time, you do not need
this: scripts/init_db.py already creates otp_codes with every current
column, this one included.

Usage:
    cd backend
    python -m scripts.add_phase6e1_columns
"""

import logging

from sqlalchemy import text

from app.database import engine
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# Written for PostgreSQL (the project's approved database, LLD Section 4.6).
# IF NOT EXISTS makes this safe to re-run. DEFAULT 0 matches the ORM
# column's default (app/models/otp_code.py) and is honest: every
# pre-existing otp_codes row predates per-attempt tracking, so treating
# it as "zero failed attempts recorded so far" is the only truthful
# value — nothing is fabricated or backfilled from guesswork.
_STATEMENTS = [
    "ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS failed_attempts INTEGER NOT NULL DEFAULT 0",
]


def main() -> None:
    with engine.begin() as conn:
        for statement in _STATEMENTS:
            logger.info("Executing: %s", statement)
            conn.execute(text(statement))
    logger.info(
        "Phase 6E-1 column is present on otp_codes. Pre-existing rows now have "
        "failed_attempts = 0 (honest: no per-attempt tracking existed before "
        "this phase) — this is expected, not an error."
    )


if __name__ == "__main__":
    main()
