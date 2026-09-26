import { useAuth } from "../../hooks/useAuth";
import { Button } from "../common/Button";

export function AppHeader() {
  const { status, user, logout } = useAuth();

  return (
    <header className="app-header">
      <span className="app-title">Secure Question Paper Distribution</span>
      {status === "authenticated" && user && (
        <div className="app-header-user">
          <span>
            {user.username} <span className="role-badge">{user.role}</span>
          </span>
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
