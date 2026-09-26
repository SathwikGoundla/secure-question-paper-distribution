import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../../components/common/Button";
import { Input } from "../../components/common/Input";
import { ErrorBanner } from "../../components/common/ErrorBanner";
import { PageContainer } from "../../components/layout/PageContainer";

/**
 * Fields are limited to exactly what the backend's LoginRequest
 * accepts (backend/app/schemas/auth.py): username, password. No
 * additional field is invented.
 */
export function LoginPage() {
  const { status, error, login, clearError } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  if (status === "otp_required") {
    return <Navigate to="/otp" replace />;
  }
  if (status === "authenticated") {
    return <Navigate to="/" replace />;
  }

  const isSubmitting = status === "authenticating";

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    clearError();

    if (!username.trim() || !password) {
      setValidationError("Username and password are both required.");
      return;
    }
    setValidationError(null);
    void login(username.trim(), password);
  }

  return (
    <PageContainer>
      <div className="auth-card">
        <h1>Sign in</h1>
        <p className="auth-subtitle">Examination Question Paper Distribution System</p>

        <form onSubmit={handleSubmit} noValidate>
          <Input
            id="username"
            label="Username"
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={isSubmitting}
            required
          />
          <Input
            id="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isSubmitting}
            required
          />

          <ErrorBanner message={validationError ?? error} />

          <Button type="submit" isLoading={isSubmitting}>
            Sign in
          </Button>
        </form>
      </div>
    </PageContainer>
  );
}
