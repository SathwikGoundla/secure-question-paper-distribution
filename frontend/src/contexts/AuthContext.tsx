import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getCurrentUser, login as loginRequest, logout as logoutRequest, verifyOtp as verifyOtpRequest } from "../api/endpoints";
import { setAuthToken } from "../api/client";
import { ApiError } from "../types/api";
import type { AuthStatus, AuthUser } from "../types/auth";

/**
 * sessionStorage (not localStorage) is used deliberately: it survives
 * a page refresh within the same tab (satisfying the "handle page
 * refresh appropriately" requirement) but is cleared when the tab or
 * browser closes, which is a more conservative default for a security
 * -sensitive examination system than a token that persists
 * indefinitely. This is a Phase 6A foundation decision — see
 * PROJECT_STATE.md "Known limitations" for the trade-off discussion
 * (no refresh-token/rotation exists yet on the backend either).
 *
 * Only the access token itself is persisted. Username/role/centre are
 * never trusted from storage — they are always re-fetched from the
 * backend's own GET /auth/me on load, because the backend remains the
 * sole source of truth for identity and role (frontend route
 * protection is a UX layer only, never an authorization boundary).
 */
const TOKEN_STORAGE_KEY = "qpaper_access_token";

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  /** True only while restoring a session from storage on initial load. */
  isInitializing: boolean;
  /** Login-flow error message (or OTP-flow error), safe to render directly. */
  error: string | null;
  login: (username: string, password: string) => Promise<void>;
  verifyOtp: (otpCode: string) => Promise<void>;
  /** Abandon an in-progress OTP step and return to the login form. */
  cancelOtp: () => void;
  logout: () => Promise<void>;
  clearError: () => void;
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function mapCurrentUser(response: {
  user_id: string;
  username: string;
  role: string;
  centre_id: string | null;
}): AuthUser {
  return {
    userId: response.user_id,
    username: response.username,
    role: response.role,
    centreId: response.centre_id,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("unauthenticated");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Held only in memory (never persisted) — it is short-lived (backend
  // default: 5 minutes) and is only needed to complete the OTP step
  // that immediately follows a successful login in the same session.
  const [preAuthToken, setPreAuthToken] = useState<string | null>(null);

  // Restore a session (if any) on initial load.
  useEffect(() => {
    const storedToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    if (!storedToken) {
      setIsInitializing(false);
      return;
    }

    setAuthToken(storedToken);
    getCurrentUser()
      .then((me) => {
        setUser(mapCurrentUser(me));
        setStatus("authenticated");
      })
      .catch(() => {
        // Token invalid/expired/revoked — do not trust it further.
        sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        setAuthToken(null);
        setStatus("unauthenticated");
      })
      .finally(() => setIsInitializing(false));
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const login = useCallback(async (username: string, password: string) => {
    setError(null);
    setStatus("authenticating");
    try {
      const result = await loginRequest({ username, password });
      if (result.otp_required) {
        setPreAuthToken(result.pre_auth_token);
        setStatus("otp_required");
      } else {
        // Defensive handling: the current backend contract only ever
        // issues an access token via /auth/otp/verify, so a
        // non-OTP-required login has no way to become authenticated
        // yet. This is not an invented endpoint/flow — it simply
        // surfaces the situation rather than silently failing.
        setError(
          "Additional verification is required but could not be started. Please contact the administrator.",
        );
        setStatus("unauthenticated");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.userMessage : "Login failed. Please try again.");
      setStatus("unauthenticated");
    }
  }, []);

  const verifyOtp = useCallback(
    async (otpCode: string) => {
      if (!preAuthToken) {
        setError("Your login attempt has expired. Please log in again.");
        setStatus("unauthenticated");
        return;
      }
      setError(null);
      try {
        const result = await verifyOtpRequest({ pre_auth_token: preAuthToken, otp_code: otpCode });
        setAuthToken(result.access_token);
        sessionStorage.setItem(TOKEN_STORAGE_KEY, result.access_token);
        setPreAuthToken(null);

        // The backend already returns `role` on this response, but
        // GET /auth/me is still called to obtain the full, canonical
        // identity (user_id, centre_id) from the single source of
        // truth rather than partially trusting this response alone.
        const me = await getCurrentUser();
        setUser(mapCurrentUser(me));
        setStatus("authenticated");
      } catch (err) {
        setError(err instanceof ApiError ? err.userMessage : "OTP verification failed. Please try again.");
        // Deliberately stay in "otp_required" so the user can retry
        // without re-entering their password, unless their pre-auth
        // token itself has now expired (a subsequent attempt will
        // surface that as a normal error from the backend).
        setStatus("otp_required");
      }
    },
    [preAuthToken],
  );

  const cancelOtp = useCallback(() => {
    setPreAuthToken(null);
    setError(null);
    setStatus("unauthenticated");
  }, []);

  const logout = useCallback(async () => {
    setStatus("logging_out");
    try {
      await logoutRequest();
    } catch {
      // Even if the server-side revocation call fails (e.g. network
      // issue, or the token was already invalid), the client must
      // still clear its own local state — a failed logout call must
      // never leave the user "stuck" logged in on this device.
    } finally {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      setAuthToken(null);
      setUser(null);
      setPreAuthToken(null);
      setError(null);
      setStatus("unauthenticated");
    }
  }, []);

  const value = useMemo(
    () => ({ status, user, isInitializing, error, login, verifyOtp, cancelOtp, logout, clearError }),
    [status, user, isInitializing, error, login, verifyOtp, cancelOtp, logout, clearError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
