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
  const [validationError, setValidationError] = useState<string | null>(null);

  if (status === "authenticated") {
    return <Navigate to="/" replace />;
  }
  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    clearError();

    if (!otpCode.trim()) {
      setValidationError("Please enter the one-time passcode.");
      return;
    }
    setValidationError(null);
    // Never logged: the OTP value is used only in this in-memory
    // submit call and is never written to console/log output anywhere
    // in the frontend.
    void verifyOtp(otpCode.trim());
  }

  return (
    <PageContainer>
      <div className="auth-card">
        <h1>Enter verification code</h1>
        <p className="auth-subtitle">
          Enter the 6-digit code from your authenticator app to complete sign-in.
        </p>

        <form onSubmit={handleSubmit} noValidate>
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

          <ErrorBanner message={validationError ?? error} />

          <Button type="submit">Verify</Button>
          <Button type="button" variant="secondary" onClick={cancelOtp}>
            Start over
          </Button>
        </form>
      </div>
    </PageContainer>
  );
}
