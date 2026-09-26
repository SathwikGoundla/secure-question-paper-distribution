/**
 * Typed functions for the backend endpoints actually consumed by
 * Phase 6A. Every path/method/shape below was verified directly
 * against the backend source during Phase 6A inspection:
 *
 *   backend/app/api/v1/auth.py   (route definitions)
 *   backend/app/schemas/auth.py  (request/response models)
 *
 * No endpoint here is invented. Endpoints that exist in the backend
 * but are not needed by this phase (papers, admin, audit,
 * exam-session, health) are intentionally NOT wrapped here yet — they
 * belong to later phases (Admin Portal / Exam Centre Portal) and will
 * be added when those phases actually consume them.
 */
import { apiRequest } from "./client";
import type {
  CurrentUserResponse,
  LoginRequest,
  LoginResponse,
  OtpVerifyRequest,
  OtpVerifyResponse,
} from "../types/auth";

/** POST /api/v1/auth/login — first factor (username + password). */
export function login(payload: LoginRequest): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: payload,
    authenticated: false,
  });
}

/** POST /api/v1/auth/otp/verify — second factor (OTP), issues the session JWT. */
export function verifyOtp(payload: OtpVerifyRequest): Promise<OtpVerifyResponse> {
  return apiRequest<OtpVerifyResponse>("/auth/otp/verify", {
    method: "POST",
    body: payload,
    authenticated: false,
  });
}

/** POST /api/v1/auth/logout — revokes the current session. Requires a valid JWT. */
export function logout(): Promise<{ detail: string }> {
  return apiRequest<{ detail: string }>("/auth/logout", { method: "POST" });
}

/** GET /api/v1/auth/me — canonical current-user identity. Requires a valid JWT. */
export function getCurrentUser(): Promise<CurrentUserResponse> {
  return apiRequest<CurrentUserResponse>("/auth/me", { method: "GET" });
}
