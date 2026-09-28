"""
DashboardService — Phase 6C. Implements LLD API-13 (GET
/admin/dashboard/summary) with real, database-derived aggregates only.

Every number below comes from a real SQL COUNT/GROUP BY against the
actual tables (LLD Section 7). Nothing here is hard-coded, randomised,
estimated, or otherwise fabricated — this is the explicit, repeated
instruction in the Phase 6C brief ("Do NOT fabricate numbers... Do NOT
use hard-coded values... Do NOT use random values... Do NOT calculate
fake statistics").

Metrics were deliberately kept to simple, deterministic totals and
breakdowns (no rolling time windows, e.g. "events in the last 24
hours") so that the same database state always produces the same
response — this also makes the endpoint straightforward to test
without needing to control wall-clock time in test fixtures.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.exam_centre import ExamCentre
from app.models.paper import Paper
from app.models.paper_authorization import PaperAuthorization
from app.models.security_event import SecurityEvent
from app.schemas.admin import DashboardSummaryResponse


def get_dashboard_summary(db: Session) -> DashboardSummaryResponse:
    total_papers = db.query(func.count(Paper.paper_id)).scalar() or 0

    papers_by_status = {
        status_value: count
        for status_value, count in db.query(Paper.status, func.count(Paper.paper_id))
        .group_by(Paper.status)
        .all()
    }

    total_exam_centres = db.query(func.count(ExamCentre.centre_id)).scalar() or 0
    active_exam_centres = (
        db.query(func.count(ExamCentre.centre_id))
        .filter(ExamCentre.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )

    total_paper_authorizations = db.query(func.count(PaperAuthorization.authorization_id)).scalar() or 0

    total_audit_events = db.query(func.count(AuditEvent.event_id)).scalar() or 0
    total_security_events = db.query(func.count(SecurityEvent.security_event_id)).scalar() or 0

    security_events_by_severity = {
        severity: count
        for severity, count in db.query(SecurityEvent.severity, func.count(SecurityEvent.security_event_id))
        .group_by(SecurityEvent.severity)
        .all()
    }

    return DashboardSummaryResponse(
        total_papers=total_papers,
        papers_by_status=papers_by_status,
        total_exam_centres=total_exam_centres,
        active_exam_centres=active_exam_centres,
        total_paper_authorizations=total_paper_authorizations,
        total_audit_events=total_audit_events,
        total_security_events=total_security_events,
        security_events_by_severity=security_events_by_severity,
    )
