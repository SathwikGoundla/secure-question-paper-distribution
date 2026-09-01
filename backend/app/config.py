"""
Application configuration.

All secrets and environment-specific values are read from environment
variables (via a local .env file in development). Nothing sensitive is
hard-coded here, per SEC-010 (PRD Section 8 / SRS SEC-010) and per the
project rule: "NEVER hard-code passwords, JWT secrets, AES keys, OTP
secrets, or commit credentials."

Reference: LLD Section 25 (Configuration and Secrets Management).
"""

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralised, typed application settings.

    Every field below maps 1:1 to an environment variable of the same
    name (case-insensitive). See backend/.env.example for the full list
    with explanatory comments.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- General ---
    APP_NAME: str = "Secure Question Paper Distribution & Controlled Examination Access — Backend"
    APP_ENV: str = Field(default="development")  # development | staging | production
    DEBUG: bool = Field(default=True)
    API_V1_PREFIX: str = "/api/v1"

    # --- CORS (LLD Section 4.1: frontend never talks to DB/storage/Fabric directly) ---
    CORS_ORIGINS: str = Field(default="http://localhost:3000")

    # --- Database (LLD Section 7: PostgreSQL application/operational schema) ---
    # Example: postgresql+psycopg2://user:password@localhost:5432/qpaper_db
    DATABASE_URL: str = Field(..., description="PostgreSQL connection string — required, no default.")
    DB_ECHO: bool = Field(default=False)

    # --- JWT (SRS FR-003, SEC-004; LLD Section 14) ---
    JWT_SECRET_KEY: str = Field(..., description="JWT signing secret — required, no default, never hard-coded.")
    JWT_ALGORITHM: str = Field(default="HS256")
    # LLD Section 14.6: exact expiry duration is NOT YET DETERMINED in the approved docs.
    # A working development default is set here; this MUST be revisited before any
    # real deployment and is explicitly called out in docs/PHASE1_IMPLEMENTATION_STATUS.md.
    JWT_EXPIRE_MINUTES: int = Field(default=30)

    # --- Phase 2 addition: pre-auth token (LLD API-01: "a short-lived pre-auth
    # token" issued after password success, before OTP verification). This is a
    # short-lived, deliberately low-privilege token distinct from the full
    # session JWT above (SRS FR-001/FR-002 two-step flow).
    PRE_AUTH_TOKEN_EXPIRE_MINUTES: int = Field(default=5)

    # --- Password hashing (SRS FR-001; LLD 14.1: algorithm NOT YET DETERMINED) ---
    # bcrypt is used as the Phase-1 working default (industry-standard adaptive hash).
    PASSWORD_HASH_SCHEME: str = Field(default="bcrypt")

    # --- OTP (SRS FR-002; LLD 14.2: delivery channel NOT YET DETERMINED / OQ-4) ---
    # OTP_DELIVERY_CHANNEL intentionally has no safe default — it must be explicitly
    # set once the channel (email/authenticator app) is decided (see LLD DD-12).
    OTP_DELIVERY_CHANNEL: str = Field(default="NOT_YET_DETERMINED")
    OTP_EXPIRE_SECONDS: int = Field(default=300)

    # --- Storage (LLD Section 21; DD-13: provider NOT YET DETERMINED) ---
    # STORAGE_BACKEND selects the StorageService implementation (see services/storage_service.py).
    STORAGE_BACKEND: str = Field(default="local")  # local (dev-only) | (future: cloud provider)
    STORAGE_LOCAL_PATH: str = Field(default="./storage_data")

    # --- Blockchain / Hyperledger Fabric (LLD Section 9-10; abstraction only in Phase 1) ---
    BLOCKCHAIN_BACKEND: str = Field(default="stub")  # stub (Phase 1 placeholder) | fabric (future)
    FABRIC_GATEWAY_ENDPOINT: str = Field(default="")
    FABRIC_CHANNEL_NAME: str = Field(default="")
    FABRIC_CHAINCODE_NAME: str = Field(default="")

    # --- Logging ---
    LOG_LEVEL: str = Field(default="INFO")

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor. Using a function (rather than a module-level
    singleton constructed at import time) makes it possible to override
    environment variables cleanly in tests.
    """
    return Settings()
