"""
GET /health — confirms the backend is running and (best-effort) whether
the database is reachable. This is the Phase-1-required health-check
endpoint; no such endpoint is separately specified in the LLD API table
(Section 6), so this follows standard practice for a FastAPI service.
"""

from fastapi import APIRouter

from app.config import get_settings
from app.database import check_database_connection
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    db_ok = check_database_connection()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app=settings.APP_NAME,
        environment=settings.APP_ENV,
        database="connected" if db_ok else "unavailable",
    )
