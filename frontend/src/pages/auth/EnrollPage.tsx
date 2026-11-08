import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { totpEnrollConfirm, totpEnrollStart } from "../../api/endpoints";
import { ApiError } from "../../types/api";
import type { TotpEnrollStartResponse } from "../../types/auth";
import { Button } from "../../components/common/Button";
import { Input } from "../../components/common/Input";
import { ErrorBanner } from "../../components/common/ErrorBanner";
import { PageContainer } from "../../components/layout/PageContainer";

type Step = "form" | "scan" | "done";

/**
 * Phase 7A — authenticator (TOTP) enrollment.
 *
 * Three steps: (1) prove identity with username + password + the one-time enrollment code an
 * Admin or the server operator gave you; (2) scan the QR (or type the key) into an authenticator
 * app and confirm with a code from it; (3) done — sign in normally.
 *
 * Security notes: the secret/QR exists only in this component's state (never storage, never the
 * URL, never logged), is cleared on success, and is never fetchable again. The password is dropped
 * from state as soon as step 1 succeeds. The page performs no authorization itself; the backend
 * decides every outcome and this page only displays its (deliberately generic) messages.
 */
export function EnrollPage() {
  const [step, setStep] = useState<Step>("form");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [enrollmentCode, setEnrollmentCode] = useState("");
  const [started, setStarted] = useState<TotpEnrollStartResponse | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function reset(message: string | null = null) {
    setStep("form");
    setStarted(null);
    setPassword("");
    setOtpCode("");
    setError(message);
  }

  async function handleStart(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!username.trim() || !password || !enrollmentCode.trim()) {
      setError("Username, password and enrollment code are all required.");
      return;
    }
    setIsSubmitting(true);
    try {
      const response = await totpEnrollStart({
        username: username.trim(),
        password,
        enrollment_code: enrollmentCode.trim(),
      });
      setStarted(response);
      setPassword(""); // no longer needed; do not keep it in memory
      setStep("scan");
    } catch (err) {
      setError(err instanceof ApiError ? err.userMessage : "Unable to start enrollment. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirm(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!started) return;
    if (!/^[0-9]{6}$/.test(otpCode.trim())) {
      setError("Enter the 6-digit code shown in your authenticator app.");
      return;
    }
    setIsSubmitting(true);
    try {
      await totpEnrollConfirm({ enrollment_token: started.enrollment_token, otp_code: otpCode.trim() });
      setStarted(null); // discard the secret and QR
      setOtpCode("");
      setStep("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.userMessage : "Unable to confirm. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageContainer>
      <div className="auth-card">
        <h1>Set up authenticator</h1>

        {step === "form" && (
          <>
            <p className="auth-subtitle">
              Enter your username, password and the one-time enrollment code from your administrator.
            </p>
            <form onSubmit={handleStart} noValidate>
              <Input
                id="enroll-username"
                label="Username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={isSubmitting}
                required
              />
              <Input
                id="enroll-password"
                label="Password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isSubmitting}
                required
              />
              <Input
                id="enroll-code"
                label="Enrollment code"
                type="text"
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                placeholder="XXXX-XXXX-XXXX"
                value={enrollmentCode}
                onChange={(e) => setEnrollmentCode(e.target.value)}
                disabled={isSubmitting}
                required
              />
              <ErrorBanner message={error} />
              <Button type="submit" isLoading={isSubmitting}>
                Continue
              </Button>
            </form>
          </>
        )}

        {step === "scan" && started && (
          <>
            <ol className="auth-subtitle">
              <li>Open an authenticator app (for example Google Authenticator, Microsoft Authenticator or FreeOTP).</li>
              <li>Scan this QR code, or choose “enter a setup key” and type the key below.</li>
              <li>Type the 6-digit code the app shows to finish.</li>
            </ol>
            <img
              src={started.qr_svg_data_uri}
              alt="QR code to add this account to your authenticator app"
              width={200}
              height={200}
            />
            <p className="auth-subtitle">
              Setup key (shown only once): <code data-testid="setup-key">{started.secret}</code>
            </p>
            <p className="auth-subtitle">
              Keep this key private. Anyone with it can generate your codes. It will not be shown again.
            </p>
            <form onSubmit={handleConfirm} noValidate>
              <Input
                id="enroll-otp"
                label="6-digit code from the app"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value)}
                disabled={isSubmitting}
                required
              />
              <ErrorBanner message={error} />
              <Button type="submit" isLoading={isSubmitting}>
                Activate authenticator
              </Button>
            </form>
            <p className="auth-subtitle">
              Code expired or lost the page?{" "}
              <button type="button" className="link-button" onClick={() => reset()}>
                Start over
              </button>
            </p>
          </>
        )}

        {step === "done" && (
          <div role="status">
            <p>Your authenticator is active. You can now sign in with your password and a code from the app.</p>
            <p>
              <Link to="/login">Go to sign in</Link>
            </p>
          </div>
        )}
      </div>
    </PageContainer>
  );
}
