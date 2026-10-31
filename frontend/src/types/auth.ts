/**
 * Types mirroring the backend's actual auth schemas exactly
 * (backend/app/schemas/auth.py). Nothing here is invented — every
 * field name matches the Pydantic response models the backend
 * genuinely returns.
 */

/** Backend's fixed RBAC role set (backend/app/models/role.py). */
export type Role = "Admin" | "Examination Centre" | "Auditor";

/** POST /auth/login request body (LoginRequest). */
export interface LoginRequest {
  username: string;
  password: string;
}

/** POST /auth/login response body (LoginResponse). */
export interface LoginResponse {
  otp_required: boolean;
  pre_auth_token: string;
  /** Phase 7A: "totp" when the next step expects an authenticator-app code; absent in the development flow. */
  second_factor?: string;
}

/** Phase 7A — POST /auth/totp/enroll/start request body (TotpEnrollStartRequest). */
export interface TotpEnrollStartRequest {
  username: string;
  password: string;
  enrollment_code: string;
}

/**
 * Phase 7A — POST /auth/totp/enroll/start response. `secret` and the QR carry the TOTP secret:
 * they are returned exactly once and must only be held in component state, never persisted.
 */
export interface TotpEnrollStartResponse {
  enrollment_token: string;
  provisioning_uri: string;
  secret: string;
  qr_svg_data_uri: string;
  expires_in_seconds: number;
}

/** Phase 7A — POST /auth/totp/enroll/confirm request / response bodies. */
export interface TotpEnrollConfirmRequest {
  enrollment_token: string;
  otp_code: string;
}
export interface TotpEnrollConfirmResponse {
  enrolled: boolean;
}

/** POST /auth/otp/verify request body (OtpVerifyRequest). */
export interface OtpVerifyRequest {
  pre_auth_token: string;
  otp_code: string;
}

/** POST /auth/otp/verify response body (OtpVerifyResponse). */
export interface OtpVerifyResponse {
  access_token: string;
  token_type: string;
  role: Role | string;
}

/** GET /auth/me response body (CurrentUserResponse). */
export interface CurrentUserResponse {
  user_id: string;
  username: string;
  role: Role | string;
  centre_id: string | null;
}

/**
 * High-level authentication state machine used by AuthContext.
 * Distinguishes every state Phase 6A's prompt explicitly asked for.
 */
export type AuthStatus =
  | "unauthenticated"
  | "authenticating"
  | "otp_required"
  | "authenticated"
  | "logging_out";

export interface AuthUser {
  userId: string;
  username: string;
  role: Role | string;
  centreId: string | null;
}
