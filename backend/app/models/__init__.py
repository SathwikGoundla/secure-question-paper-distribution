"""
Importing this package registers every ORM model against
app.database.Base.metadata, which is what Base.metadata.create_all()
(used by scripts/init_db.py in Phase 1) relies on.

Table -> LLD reference:
  roles                 -> LLD 7.2
  exam_centres           -> LLD 7.3
  users                  -> LLD 7.1
  papers                 -> LLD 7.4
  paper_authorizations   -> LLD 7.5
  audit_events           -> LLD 7.6
  security_events        -> LLD 7.7
  otp_codes              -> LLD 7.8
  auth_sessions          -> LLD 7.9
  exam_security_events   -> LLD 7.10 (Faculty-Review Addition)
"""

from app.models.role import Role  # noqa: F401
from app.models.exam_centre import ExamCentre  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.paper import Paper  # noqa: F401
from app.models.paper_authorization import PaperAuthorization  # noqa: F401
from app.models.audit_event import AuditEvent  # noqa: F401
from app.models.security_event import SecurityEvent  # noqa: F401
from app.models.otp_code import OtpCode  # noqa: F401
from app.models.auth_session import AuthSession  # noqa: F401
from app.models.exam_security_event import ExamSecurityEvent  # noqa: F401

__all__ = [
    "Role",
    "ExamCentre",
    "User",
    "Paper",
    "PaperAuthorization",
    "AuditEvent",
    "SecurityEvent",
    "OtpCode",
    "AuthSession",
    "ExamSecurityEvent",
]
