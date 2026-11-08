import { Link } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../common/Button";

export function AppHeader() {
  const { status, user, logout, recoveryCodesRemaining } = useAuth();

  return (
    <header className="app-header">
      <span className="app-title">Secure Question Paper Distribution</span>
      {status === "authenticated" && user && (
        <div className="app-header-user">
          <span>
            {user.username} <span className="role-badge">{user.role}</span>
          </span>
          {recoveryCodesRemaining !== null && (
            <span role="status" className="status-badge">
              Signed in with a recovery code — {recoveryCodesRemaining} left
            </span>
          )}
          <Link to="/security">Security</Link>
          <Button
            type="button"
            variant="secondary"
            isLoading={false}
            onClick={() => {
              void logout();
            }}
          >
            Log out
          </Button>
        </div>
      )}
    </header>
  );
}
