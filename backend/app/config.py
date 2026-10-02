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

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_FABRIC_VERIFICATION_MODES = ("best_effort", "strict")


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
    # Phase 6E-1: bounds how many FAILED verification attempts a single
    # OTP challenge tolerates before it is treated as exhausted/locked
    # (app/services/auth_service.verify_otp_step2). A correct code
    # submitted after the limit is reached is still rejected — the
    # user must start a new /auth/login to obtain a fresh challenge.
    OTP_MAX_ATTEMPTS: int = Field(default=5)

    # --- Phase 6E-2: authentication rate limiting ---
    # Applies ONLY to POST /auth/login and POST /auth/otp/verify (never
    # the whole API — see app/api/v1/auth.py). Independent of, and
    # checked strictly BEFORE, the Phase 6E-1 OTP failed-attempt
    # counter: a 429 here never touches otp_codes.failed_attempts.
    # In-process only (app/security/rate_limiter.py) — see that
    # module's docstring for the documented single-instance limitation.
    AUTH_LOGIN_RATE_LIMIT: int = Field(default=5)
    AUTH_LOGIN_RATE_WINDOW_SECONDS: int = Field(default=60)
    # Deliberately NOT the same "5" suggested as a generic starting
    # point: this endpoint already has an independent, lower-level
    # control at exactly 5 (OTP_MAX_ATTEMPTS, above) that bounds WRONG
    # GUESSES against one specific challenge. This rate limit instead
    # bounds RAW REQUEST VOLUME against the endpoint — a coarser,
    # complementary flood/automation guard, not a duplicate of the
    # attempt counter. Setting it to the same value as OTP_MAX_ATTEMPTS
    # would make the two controls collide on ordinary, legitimate
    # sequences (e.g. a user who exhausts one challenge via 5 wrong
    # guesses, sees the generic failure message, and immediately starts
    # a fresh login) — the rate limiter would then trigger first and
    # mask the real OTP_CHALLENGE_LOCKED behaviour behind a generic 429
    # instead. 15 gives comfortable headroom above the 5-attempt lock
    # (and the few additional requests a legitimate recovery sequence
    # needs) while still meaningfully throttling abuse: a genuine
    # attacker would additionally need fresh pre-auth tokens to get
    # more budget per challenge, and minting those is independently
    # bounded by AUTH_LOGIN_RATE_LIMIT above.
    AUTH_OTP_RATE_LIMIT: int = Field(default=15)
    AUTH_OTP_RATE_WINDOW_SECONDS: int = Field(default=60)

    # --- Storage (LLD Section 21; DD-13: provider NOT YET DETERMINED) ---
    # STORAGE_BACKEND selects the StorageService implementation (see services/storage_service.py).
    STORAGE_BACKEND: str = Field(default="local")  # local (dev-only) | (future: cloud provider)
    STORAGE_LOCAL_PATH: str = Field(default="./storage_data")

    # --- Phase 3: paper encryption (SRS FR-008/FR-009; LLD Section 12/13) ---
    # Base64-encoded 32-byte (256-bit) master key used to wrap each paper's
    # per-paper AES-256-GCM data-encryption key (see services/crypto_service.py).
    # Deliberately has NO safe default and is NOT validated here — validation
    # happens lazily in crypto_service._load_master_key(), only when a paper
    # is actually encrypted/decrypted. This keeps Phase 1/2 functionality
    # (auth, RBAC — neither of which touches this key) working in any
    # environment where Phase 3 has not been configured yet (SEC-010: never
    # hard-coded; generate with:
    #   python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
    # ).
    QUESTION_PAPER_MASTER_KEY: str = Field(default="")

    # Maximum accepted upload size for a question-paper PDF. Default: 20 MB.
    PAPER_MAX_UPLOAD_SIZE_BYTES: int = Field(default=20 * 1024 * 1024)

    # --- Blockchain / Hyperledger Fabric (LLD Section 9-10) ---
    # BLOCKCHAIN_BACKEND selects the BlockchainService implementation
    # (see app/services/blockchain_service.py get_blockchain_service()):
    #   "stub"   Phase 1 in-memory placeholder (default).
    #   "fabric" Phase 5C real integration — talks to the Phase 5B
    #            Fabric Gateway Adapter (blockchain/gateway-adapter/)
    #            over HTTP. Requires FABRIC_GATEWAY_ENDPOINT.
    BLOCKCHAIN_BACKEND: str = Field(default="stub")
    # Base URL of the running Fabric Gateway Adapter, e.g.
    # http://127.0.0.1:8081 (matches the adapter's ADAPTER_PORT / bind
    # address — see blockchain/gateway-adapter/src/server.ts). Only
    # required when BLOCKCHAIN_BACKEND=fabric.
    FABRIC_GATEWAY_ENDPOINT: str = Field(default="")
    # How long the backend waits for a single Fabric Gateway Adapter
    # HTTP call before treating it as unavailable (Phase 5C addition).
    FABRIC_GATEWAY_TIMEOUT_SECONDS: float = Field(default=5.0)
    # NOTE (Phase 5C): the two settings below are NOT currently read by
    # the backend. The Fabric channel name and chaincode name are
    # connection details owned entirely by the Node.js Gateway Adapter
    # process (blockchain/gateway-adapter/.env) — the backend only ever
    # talks to the adapter's HTTP API, never to Fabric directly, so it
    # has no need for these values itself. Left in place (unused,
    # harmless) rather than removed, in case a future phase adds a
    # backend-side use for them; removing unused-but-harmless settings
    # is out of Phase 5C's scope.
    FABRIC_CHANNEL_NAME: str = Field(default="")
    FABRIC_CHAINCODE_NAME: str = Field(default="")

    # --- Phase 5E: blockchain-backed retrieval-time integrity verification ---
    # (SRS FR-010/FR-011 extended with an independent ledger check; see
    # PROJECT_STATE.md Phase 5E section for the full design/trade-off
    # discussion). Only consulted when BLOCKCHAIN_BACKEND=fabric AND the
    # configured backend actually supports verify_paper_hash() (StubBlockchainService
    # does not — see blockchain_service.py — so under BLOCKCHAIN_BACKEND=stub this
    # setting has no effect at all: paper_service.retrieve_paper() never calls
    # verify_paper_hash() in that case).
    #
    #   "best_effort" (default) — if the Fabric Gateway Adapter/network cannot be
    #       reached, or this paper has no ledger record at all (e.g. its Phase 5D
    #       registration-time ledger write itself failed/was skipped), retrieval
    #       proceeds on the strength of the already-passed local AES-256-GCM +
    #       SHA-256 checks alone. A BLOCKCHAIN_VERIFICATION_UNAVAILABLE/DEGRADED
    #       audit event is recorded so this is visible, never silent.
    #   "strict" — the same two conditions instead reject retrieval with 503.
    #
    # In BOTH modes, an explicit Fabric match=False (a genuine, positive ledger
    # disagreement — not an availability problem) ALWAYS fails retrieval with 409.
    # This distinction is deliberate: this setting governs what happens when a
    # comparison could not be obtained, never what happens when one WAS obtained
    # and disagreed.
    FABRIC_VERIFICATION_MODE: str = Field(default="best_effort")

    @field_validator("FABRIC_VERIFICATION_MODE")
    @classmethod
    def _validate_fabric_verification_mode(cls, value: str) -> str:
        """
        Fails fast (at settings-construction time, i.e. app startup) rather
        than silently accepting an unrecognized value and falling back to
        some default behaviour deep inside paper_service.py — a typo here
        must be loud, not swallowed (same discipline already applied to
        get_blockchain_service()'s BLOCKCHAIN_BACKEND handling).
        """
        if value not in _VALID_FABRIC_VERIFICATION_MODES:
            raise ValueError(
                f"FABRIC_VERIFICATION_MODE must be one of {_VALID_FABRIC_VERIFICATION_MODES}, got {value!r}."
            )
        return value

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
