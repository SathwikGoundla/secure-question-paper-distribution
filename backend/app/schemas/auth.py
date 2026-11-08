"""
Request/response schemas for authentication (LLD API-01, API-02, API-03).

Response models are deliberately narrow: password hashes, OTP hashes,
and raw JWTs are never echoed back except the one token each endpoint
is explicitly supposed to issue (SEC-010 — "never expose secrets in
API responses").
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """LLD API-01 request body: username, password."""
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    """
    LLD API-01 response: "On success: otp_required flag + a short-lived
    pre-auth token."
    """
    otp_required: bool
    pre_auth_token: str
    # Phase 7A: which second factor the next step expects ("totp" = authenticator
    # app). Omitted from the JSON for the legacy development flow so that
    # response is byte-for-byte what it was (route uses response_model_exclude_none).
    second_factor: str | None = None


class OtpVerifyRequest(BaseModel):
    """LLD API-02 request body: pre_auth_token, otp_code."""
    pre_auth_token: str
    otp_code: str = Field(min_length=1, max_length=10)


class OtpVerifyResponse(BaseModel):
    """LLD API-02 response: "On success: JWT (session token) and role claim." """
    access_token: str
    token_type: str = "bearer"
    role: str
    # Phase 7B: present ONLY when the session was obtained with a recovery code.
    recovery_codes_remaining: int | None = None


class LogoutResponse(BaseModel):
    """LLD API-03 response: "Confirmation of logout." """
    detail: str = "Logged out successfully."


class CurrentUserResponse(BaseModel):
    """
    Not an LLD-numbered endpoint — a small identity-check endpoint
    (GET /auth/me) added in Phase 2 so RBAC/JWT verification can be
    demonstrated and tested end-to-end. Returns no sensitive fields.
    """
    user_id: str
    username: str
    role: str
    centre_id: str | None = None


# --------------------------------------------------------------------------- Phase 7A: TOTP enrollment


class TotpEnrollStartRequest(BaseModel):
    """Proof of identity for enrollment: password + the one-time enrollment code issued by an Admin/operator."""

    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=256)
    enrollment_code: str = Field(min_length=1, max_length=64)


class TotpEnrollStartResponse(BaseModel):
    """
    Returned ONCE. `secret` and the QR carry the TOTP secret; they are never
    returned again (not after confirmation, not on a later call). The
    enrollment_token is accepted only by /auth/totp/enroll/confirm.
    """

    enrollment_token: str
    provisioning_uri: str
    secret: str
    qr_svg_data_uri: str
    expires_in_seconds: int


class TotpEnrollConfirmRequest(BaseModel):
    enrollment_token: str = Field(min_length=1, max_length=4096)
    otp_code: str = Field(min_length=1, max_length=10)


class TotpEnrollConfirmResponse(BaseModel):
    enrolled: bool


class AdminEnrollmentCodeRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)


class AdminEnrollmentCodeResponse(BaseModel):
    """The enrollment code is shown exactly once, to the Admin, to hand to the user out-of-band."""

    username: str
    enrollment_code: str
    expires_at: datetime


# --------------------------------------------------------------------------- Phase 7B: recovery codes


class RecoveryCodeVerifyRequest(BaseModel):
    """Second-factor step using a one-time recovery code instead of an authenticator code."""

    pre_auth_token: str = Field(min_length=1, max_length=4096)
    recovery_code: str = Field(min_length=1, max_length=64)


class RecoveryCodeRegenerateRequest(BaseModel):
    """Step-up: the current password is required to (re)generate codes, on top of a normal MFA session."""

    password: str = Field(min_length=1, max_length=256)


class RecoveryCodesResponse(BaseModel):
    """Returned ONCE. These plaintext codes are never retrievable again."""

    codes: list[str]
    count: int
    generated_at: datetime


class RecoveryCodeStatusResponse(BaseModel):
    """Counts only; never any code material."""

    unused_count: int
    generated_at: datetime | None = None
    authenticator_active: bool


# --------------------------------------------------------------------------- Phase 7B: admin enrollment management


class AdminTotpUserItem(BaseModel):
    """
    One user's authenticator-enrollment STATE, for administration. Deliberately minimal: no secret,
    no code (plain or hashed), no recovery-code material, no password hash, no tokens.

    totp_status:
      not_enrolled          no enrollment code was ever issued
      code_issued           a code is waiting (unexpired); the user has not started
      enrollment_in_progress the user scanned the QR but has not confirmed yet (unexpired)
      code_expired          a code/enrollment exists but its time ran out
      needs_new_code        the pending enrollment was destroyed (too many wrong attempts); issue a new code
      active                authenticator confirmed and usable
    """

    user_id: uuid.UUID
    username: str
    role: str
    centre_name: str | None = None
    totp_status: str
    confirmed_at: datetime | None = None
    code_issued_at: datetime | None = None
    code_expires_at: datetime | None = None
    is_self: bool


class AdminTotpUserListResponse(BaseModel):
    items: list[AdminTotpUserItem]
    total: int
    page: int
    page_size: int
