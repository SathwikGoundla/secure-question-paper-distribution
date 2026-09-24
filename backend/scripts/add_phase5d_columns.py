"""
Phase 5D schema helper — adds the new ledger_tx_reference column to an
ALREADY-EXISTING papers table.

Why this script exists: this project does not use Alembic (a Phase 1
decision — see docs/PHASE1_IMPLEMENTATION_STATUS.md), and
Base.metadata.create_all() (used by scripts/init_db.py) only CREATES
tables that don't exist yet — it never ALTERs an existing table's
columns. Anyone who ran init_db.py (or add_phase3_columns.py) before
Phase 5D will have a papers table missing the column defined in
app/models/paper.py.

This script is intentionally NOT a general migration framework — it is
a small, explicit, idempotent (safe to re-run) statement list for
exactly the one column Phase 5D adds. If you are setting up the
database for the FIRST time, you do not need this: scripts/init_db.py
already creates the papers table with every current column, this one
included.

Usage:
    cd backend
    python -m scripts.add_phase5d_columns

(Run as a module, matching scripts/init_db.py's own convention —
`python scripts/add_phase5d_columns.py` directly will fail with
`ModuleNotFoundError: No module named 'app'` because the script needs
`backend/` on sys.path, which `-m` provides automatically. Verified in
this session: `python scripts/add_phase3_columns.py`'s docstring
states the direct-script form, but the direct form does not actually
work from a fresh shell without backend/ separately added to
PYTHONPATH — the `-m` form is the one confirmed working here and is
what this docstring recommends going forward.)
"""

import logging

from sqlalchemy import text

from app.database import engine
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# Written for PostgreSQL (the project's approved database, LLD Section 4.6).
# IF NOT EXISTS makes this safe to re-run. No DEFAULT is set (the column
# is nullable with no default) — every PRE-EXISTING row will simply have
# ledger_tx_reference = NULL after this runs, which is the correct,
# honest value: those rows were registered before Phase 5D existed, so
# no Fabric transaction was ever recorded for them. Nothing is
# backfilled or fabricated.
_STATEMENTS = [
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS ledger_tx_reference VARCHAR(255)",
]


def main() -> None:
    with engine.begin() as conn:
        for statement in _STATEMENTS:
            logger.info("Executing: %s", statement)
            conn.execute(text(statement))
    logger.info(
        "Phase 5D column is present on papers. Pre-existing rows now have "
        "ledger_tx_reference = NULL (honest: no Fabric write was ever "
        "attempted for them) — this is expected, not an error."
    )


if __name__ == "__main__":
    main()
