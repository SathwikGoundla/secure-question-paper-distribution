"""
Shared pytest fixtures for the automated Phase 3 test suite.

Design choice: these tests do NOT require a running PostgreSQL server.
They use a temporary file-based SQLite database instead (fixture
`db_engine` below) so the full stack — models, services, and API layer
— can be exercised in any environment (including CI / this sandbox),
while backend/tests/test_phase2_manual.py remains the separate,
existing "real Postgres + real running server" verification path
(unchanged, not replaced).

A file-based SQLite DB (not ":memory:") is used deliberately: FastAPI
runs synchronous ("def", not "async def") route handlers in a worker
thread pool, and SQLite's ":memory:" database is private to the
connection that created it — a request handled on a different thread
would otherwise see an empty database. A temp file avoids that
entirely without needing StaticPool tricks.

Nothing here modifies application source code — these are test-only
fixtures using the app's real public interfaces (real password
hashing, real JWT issuance via the real /auth/login + /auth/otp/verify
endpoints, real SQLAlchemy models).
"""

import base64
import os
import secrets
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# --- Environment MUST be set before any `app.*` module is imported, ---
# --- since app/config.py reads it at Settings() construction time.  ---
_TEST_DB_FILE = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_TEST_DB_FILE.close()
_TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="qpaper_test_storage_")

os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_FILE.name}")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-used-anywhere-real")
os.environ.setdefault(
    "QUESTION_PAPER_MASTER_KEY",
    base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
)
os.environ.setdefault("STORAGE_LOCAL_PATH", _TEST_STORAGE_DIR)
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("BLOCKCHAIN_BACKEND", "stub")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.exam_centre import ExamCentre  # noqa: E402
from app.models.user import User  # noqa: E402
from app.security.password import hash_password  # noqa: E402
import app.services.auth_service as auth_service_module  # noqa: E402

from sqlalchemy import DateTime as _SA_DateTime
from sqlalchemy import event as _sa_event
from sqlalchemy import inspect as _sa_inspect
from sqlalchemy.orm import Session as _SA_Session


def _make_tz_aware_columns_tz_aware_on_load(session, instance) -> None:
    """
    TEST-ONLY compatibility shim, registered on SQLAlchemy's base Session
    class (this file only — never imported by application code).

    Root cause: SQLite has no native timezone-aware timestamp type.
    SQLAlchemy's generic DateTime(timezone=True) columns (used throughout
    app/models/*.py, correctly, for the real target database —
    PostgreSQL, which DOES preserve tzinfo) silently round-trip as
    NAIVE datetimes when the backing database is SQLite. This is a
    well-known SQLAlchemy+SQLite limitation, not an application bug —
    the historical Phase 2 test run (docs/PHASE2_IMPLEMENTATION_STATUS.md,
    28/28) executed against real PostgreSQL, where this does not occur.

    Rather than weaken app/services/auth_service.py's correct
    (Postgres-correct) naive/aware comparison to work around a
    SQLite-only artifact, this test-only hook re-attaches UTC tzinfo to
    every DateTime(timezone=True) column immediately after each object
    is loaded from the TEST database, so the application code under
    test sees exactly the tz-aware values it would see against real
    PostgreSQL.
    """
    mapper = _sa_inspect(instance).mapper
    for column in mapper.columns:
        if isinstance(column.type, _SA_DateTime) and column.type.timezone:
            value = getattr(instance, column.key, None)
            if value is not None and value.tzinfo is None:
                setattr(instance, column.key, value.replace(tzinfo=timezone.utc))


_sa_event.listen(_SA_Session, "loaded_as_persistent", _make_tz_aware_columns_tz_aware_on_load)


def _make_tz_aware_on_refresh(instance, context, attrs):
    """
    Phase 6G addition to the same test-only SQLite compensation: the
    "loaded_as_persistent" hook above fires only when an object is
    first loaded. A later db.refresh(obj) (or reload of expired
    attributes) re-reads the row and SQLite hands the naive value back
    again, so application code comparing a refreshed release_timestamp
    against an aware "now" raised TypeError — on SQLite only; real
    PostgreSQL always returns aware values. Still test-level only: no
    normalisation was added to application code.
    """
    _make_tz_aware_columns_tz_aware_on_load(None, instance)  # session arg is unused


from sqlalchemy.orm import Mapper as _SA_Mapper  # noqa: E402

_sa_event.listen(_SA_Mapper, "refresh", _make_tz_aware_on_refresh)


@pytest.fixture(scope="session")
def db_engine():
    url = os.environ["DATABASE_URL"]
    # check_same_thread=False is a SQLite-only pysqlite connect option
    # (needed because FastAPI runs sync routes in a worker thread pool);
    # it is invalid for other DBAPIs (e.g. psycopg2), so it is only
    # passed when actually testing against SQLite. Running this same
    # suite against PostgreSQL (DATABASE_URL=postgresql+psycopg2://...)
    # works with no connect_args at all.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    if url.startswith("sqlite"):
        os.unlink(_TEST_DB_FILE.name)


@pytest.fixture()
def db_session(db_engine):
    """
    One session per test. Tables are shared (created once per session-scoped
    engine) but each test runs inside its own transaction-like session and
    commits are visible to the app via the dependency override below, since
    the override creates a NEW session bound to the SAME engine per request
    (matching how the real app.database.get_db behaves) rather than reusing
    this exact session object.
    """
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_engine):
    """
    TestClient wired to the SAME SQLite engine as db_session, via a
    real dependency override of get_db (the officially-supported
    FastAPI testing pattern) — no application code is bypassed or
    mocked; every request goes through real routing, real RBAC, real
    services.
    """
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def _override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _get_or_create_role(db_session, role_name: str) -> Role:
    role = db_session.query(Role).filter(Role.role_name == role_name).first()
    if role is None:
        role = Role(role_name=role_name)
        db_session.add(role)
        db_session.commit()
        db_session.refresh(role)
    return role


@dataclass
class TestPrincipal:
    """A created user plus a valid access token for it."""

    user_id: uuid.UUID
    username: str
    password: str
    access_token: str
    centre_id: uuid.UUID | None = None


def _login_and_capture_token(client: TestClient, monkeypatch, username: str, password: str) -> str:
    """
    Drives the REAL /auth/login -> /auth/otp/verify flow. The OTP is
    never persisted or transmitted in plaintext by the application (by
    design — see security/otp.py), so this test helper monkeypatches
    ONLY the OTP delivery call (which in production just logs the OTP)
    to also capture the raw value for the test to read back — this
    does not change, weaken, or bypass any authentication check.
    """
    captured: dict[str, str] = {}

    original_deliver = auth_service_module._otp_provider.deliver

    def _capturing_deliver(user_identifier: str, otp: str) -> None:
        captured["otp"] = otp
        original_deliver(user_identifier, otp)

    monkeypatch.setattr(auth_service_module._otp_provider, "deliver", _capturing_deliver)

    login_resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    pre_auth_token = login_resp.json()["pre_auth_token"]

    otp_resp = client.post(
        "/api/v1/auth/otp/verify",
        json={"pre_auth_token": pre_auth_token, "otp_code": captured["otp"]},
    )
    assert otp_resp.status_code == 200, otp_resp.text
    return otp_resp.json()["access_token"]


@pytest.fixture()
def admin_principal(client, db_session, monkeypatch) -> TestPrincipal:
    role = _get_or_create_role(db_session, "Admin")
    username = f"admin_{uuid.uuid4().hex[:8]}"
    password = "Test-Admin-Password-123!"
    user = User(username=username, password_hash=hash_password(password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = _login_and_capture_token(client, monkeypatch, username, password)
    return TestPrincipal(user_id=user.user_id, username=username, password=password, access_token=token)


@pytest.fixture()
def exam_centre_principal(client, db_session, monkeypatch) -> TestPrincipal:
    role = _get_or_create_role(db_session, "Examination Centre")
    admin_role = _get_or_create_role(db_session, "Admin")

    # exam_centres.created_by has a REAL foreign key to users.user_id
    # (enforced by PostgreSQL; SQLite does not enforce FKs by default,
    # which is why this needs a genuine user row rather than a random
    # placeholder UUID — a gap only caught by testing against real
    # PostgreSQL, matching real-world provisioning: an actual Admin
    # account creates every exam centre).
    provisioning_admin = User(
        username=f"provisioning_admin_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("not-used-in-this-fixture"),
        role_id=admin_role.role_id,
    )
    db_session.add(provisioning_admin)
    db_session.commit()
    db_session.refresh(provisioning_admin)

    centre = ExamCentre(
        centre_name=f"Test Centre {uuid.uuid4().hex[:6]}",
        created_by=provisioning_admin.user_id,
    )
    db_session.add(centre)
    db_session.commit()
    db_session.refresh(centre)

    username = f"centre_{uuid.uuid4().hex[:8]}"
    password = "Test-Centre-Password-123!"
    user = User(
        username=username,
        password_hash=hash_password(password),
        role_id=role.role_id,
        centre_id=centre.centre_id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = _login_and_capture_token(client, monkeypatch, username, password)
    return TestPrincipal(
        user_id=user.user_id,
        username=username,
        password=password,
        access_token=token,
        centre_id=centre.centre_id,
    )


@pytest.fixture()
def auditor_principal(client, db_session, monkeypatch) -> TestPrincipal:
    """
    Phase 6C addition. Auditor (LLD Section 15: read-only audit/
    security-monitoring access) — needed to test GET /audit/logs and
    GET /monitoring/security-events, which are Admin-OR-Auditor per
    the existing (Phase 2, unmodified) RBAC wiring in
    app/api/v1/audit.py.
    """
    role = _get_or_create_role(db_session, "Auditor")
    username = f"auditor_{uuid.uuid4().hex[:8]}"
    password = "Test-Auditor-Password-123!"
    user = User(username=username, password_hash=hash_password(password), role_id=role.role_id)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = _login_and_capture_token(client, monkeypatch, username, password)
    return TestPrincipal(user_id=user.user_id, username=username, password=password, access_token=token)


def auth_header(principal: TestPrincipal) -> dict:
    return {"Authorization": f"Bearer {principal.access_token}"}


SAMPLE_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nDEMO EXAM PAPER - NOT A REAL QUESTION PAPER\n%%EOF"
