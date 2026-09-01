"""
Request/response schemas for authentication (LLD API-01, API-02, API-03).

Response models are deliberately narrow: password hashes, OTP hashes,
and raw JWTs are never echoed back except the one token each endpoint
is explicitly supposed to issue (SEC-010 — "never expose secrets in
API responses").
"""

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


class OtpVerifyRequest(BaseModel):
    """LLD API-02 request body: pre_auth_token, otp_code."""
    pre_auth_token: str
    otp_code: str = Field(min_length=1, max_length=10)


class OtpVerifyResponse(BaseModel):
    """LLD API-02 response: "On success: JWT (session token) and role claim." """
    access_token: str
    token_type: str = "bearer"
    role: str


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
