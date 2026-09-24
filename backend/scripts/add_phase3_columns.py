"""
Phase 3 schema helper — adds the new encryption-metadata columns to an
ALREADY-EXISTING papers table.

Why this script exists: this project does not use Alembic (a Phase 1
decision — see docs/PHASE1_IMPLEMENTATION_STATUS.md), and
Base.metadata.create_all() (used by scripts/init_db.py) only CREATES
tables that don't exist yet — it never ALTERs an existing table's
columns. Anyone who ran init_db.py before Phase 3 will have a papers
table missing the new columns defined in app/models/paper.py.

This script is intentionally NOT a general migration framework — it is
a small, explicit, idempotent (safe to re-run) statement list for
exactly the columns Phase 3 adds. If you are setting up the database
for the FIRST time, you do not need this: scripts/init_db.py already
creates the papers table with every current column, this script
included.

Usage:
    cd backend
    python scripts/add_phase3_columns.py
"""

import logging

from sqlalchemy import text

from app.database import engine
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# Written for PostgreSQL (the project's approved database, LLD Section 4.6).
# IF NOT EXISTS makes every statement safe to re-run.
_STATEMENTS = [
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS encryption_algorithm VARCHAR(50) "
    "NOT NULL DEFAULT 'AES-256-GCM'",
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS file_nonce VARCHAR(64) NOT NULL DEFAULT ''",
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS wrapped_dek VARCHAR(255) NOT NULL DEFAULT ''",
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255)",
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT",
]


def main() -> None:
    with engine.begin() as conn:
        for statement in _STATEMENTS:
            logger.info("Executing: %s", statement)
            conn.execute(text(statement))
    logger.info(
        "Phase 3 columns are present on papers. Note: file_nonce/wrapped_dek "
        "default to '' for any PRE-EXISTING rows (there should be none yet, "
        "since paper registration was a 501 stub before Phase 3) — such rows "
        "cannot be decrypted and should be treated as invalid test data."
    )


if __name__ == "__main__":
    main()
