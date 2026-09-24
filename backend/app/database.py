"""
Database engine and session management.

PostgreSQL is the approved database (LLD Section 4.6, 7). SQLAlchemy is
used as the ORM/access layer — this was NOT YET DETERMINED in the LLD, so
it is recorded here as a Phase-1 implementation decision (see
docs/PHASE1_IMPLEMENTATION_STATUS.md).

Only the FastAPI backend talks to PostgreSQL directly, per LLD Section
4.6 Security Considerations ("Accessed only by the FastAPI backend").
"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,  # avoids serving requests on a dropped DB connection
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models (app/models/*.py)."""
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session per request and
    guarantees it is closed afterwards, even on error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """
    Lightweight connectivity check used by the /health endpoint.
    Returns True if a trivial query succeeds, False otherwise.
    Never raises — callers should treat False as "database unavailable".
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
