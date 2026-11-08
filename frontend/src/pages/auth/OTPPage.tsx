import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../../components/common/Button";
import { Input } from "../../components/common/Input";
import { ErrorBanner } from "../../components/common/ErrorBanner";
import { PageContainer } from "../../components/layout/PageContainer";

/**
 * The backend's authentication flow requires a second factor
 * (POST /auth/otp/verify — backend/app/api/v1/auth.py, SRS FR-002),
 * so this page is genuinely required, not speculative.
 *
 * There is no resend endpoint in the backend today (confirmed by
 * inspecting app/api/v1/auth.py and app/schemas/auth.py) — an OTP is
 * only ever issued as part of a fresh POST /auth/login call. So no
 * "resend" button is implemented here; the user instead returns to
 * the login form ("Start over") to obtain a new OTP.
 */
export function OTPPage() {
  const { status, error, verifyOtp, cancelOtp, clearError } = useAuth();
  const [otpCode, setOtpCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  if (status === "authenticated") {
    return <Navigate to="/" replace />;
  }
  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  function switchMode(recovery: boolean) {
    setUseRecovery(recovery);
    setOtpCode("");
    setValidationError(null);
    clearError();
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    clearError();

    const value = otpCode.trim();
    if (!value) {
      setValidationError(
        useRecovery ? "Please enter one of your recovery codes." : "Please enter the one-time passcode.",
      );
      return;
    }
    if (useRecovery && value.replace(/[\s-]/g, "").length !== 16) {
      setValidationError("A recovery code has 16 letters and numbers, for example ABCD-EFGH-JKMN-PQRS.");
      return;
    }
    setValidationError(null);
    // Never logged: the code is used only in this in-memory submit call and is never written to
    // console/log output anywhere in the frontend.
    void verifyOtp(value, { recovery: useRecovery });
  }

  return (
    <PageContainer>
      <div className="auth-card">
        <h1>{useRecovery ? "Use a recovery code" : "Enter verification code"}</h1>
        <p className="auth-subtitle">
          {useRecovery
            ? "Enter one of the one-time recovery codes you saved. Each code works only once."
            : "Enter the 6-digit code from your authenticator app to complete sign-in."}
        </p>

        <form onSubmit={handleSubmit} noValidate>
          {useRecovery ? (
            <Input
              id="recovery-code"
              label="Recovery code"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              maxLength={32}
              required
            />
          ) : (
            <Input
              id="otp-code"
              label="One-time passcode"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              maxLength={10}
              required
            />
          )}

          <ErrorBanner message={validationError ?? error} />

          <Button type="submit">{useRecovery ? "Sign in with recovery code" : "Verify"}</Button>
          <Button type="button" variant="secondary" onClick={cancelOtp}>
            Start over
          </Button>
        </form>

        <p className="auth-subtitle">
          {useRecovery ? (
            <button type="button" className="link-button" onClick={() => switchMode(false)}>
              Back to authenticator code
            </button>
          ) : (
            <button type="button" className="link-button" onClick={() => switchMode(true)}>
              Use a recovery code
            </button>
          )}
        </p>
        {useRecovery && (
          <p className="auth-subtitle">
            A used, mistyped or replaced code is rejected with the same message. If none of your codes work, ask
            your administrator for a new enrollment code.
          </p>
        )}
      </div>
    </PageContainer>
  );
}
