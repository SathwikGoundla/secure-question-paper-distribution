"""
Examination-centre-to-paper authorization scoping (SRS FR-004; LLD
Section 5.4, 15, paper_authorizations table Section 7.5).

A valid login must NOT automatically mean unrestricted access — an
authenticated Examination-Centre-role user may still be denied access
to a SPECIFIC paper if no non-revoked paper_authorizations row exists
for (paper_id, centre_id).

This module is deliberately built now (Phase 2) even though the paper
retrieval endpoint itself (LLD API-07) is Phase 3+ work — the check
requires only paper_authorizations + exam_centres, both of which are
Phase-1 tables, and is exercised by the Phase 2 test suite directly
against the database so the mechanism is proven before Phase 3 wires
it into the real retrieval flow.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.paper_authorization import PaperAuthorization


def is_centre_authorized_for_paper(db: Session, centre_id: uuid.UUID, paper_id: uuid.UUID) -> bool:
    """
    Returns True only if a non-revoked paper_authorizations row exists
    for this exact (paper_id, centre_id) pair (FR-004, FR-009).
    """
    row = (
        db.query(PaperAuthorization)
        .filter(
            PaperAuthorization.paper_id == paper_id,
            PaperAuthorization.centre_id == centre_id,
            PaperAuthorization.is_revoked == False,  # noqa: E712
        )
        .first()
    )
    return row is not None
