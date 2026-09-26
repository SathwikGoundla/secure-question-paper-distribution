import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { LoadingIndicator } from "../components/common/LoadingIndicator";
import type { Role } from "../types/auth";

interface ProtectedRouteProps {
  children: ReactNode;
  /**
   * Roles permitted to view this route. If omitted, any authenticated
   * user may view it. This is a UX/navigation convenience ONLY — every
   * protected backend endpoint independently enforces its own RBAC
   * (backend/app/api/deps.py `require_role`), and a component behind
   * this guard must still handle a 403 from the API if it ever occurs.
   */
  allowedRoles?: Role[];
}

/**
 * Blocks unauthenticated users from reaching authenticated areas, and
 * (optionally) restricts a route to specific roles for navigation
 * purposes. This is explicitly NOT the authorization boundary — the
 * backend is (see class doc above and Phase 6A PROJECT_STATE.md
 * security decisions).
 */
export function ProtectedRoute({ children, allowedRoles }: ProtectedRouteProps) {
  const { status, user, isInitializing } = useAuth();

  if (isInitializing) {
    return <LoadingIndicator label="Checking your session…" />;
  }

  if (status !== "authenticated" || !user) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role as Role)) {
    return <Navigate to="/unauthorized" replace />;
  }

  return <>{children}</>;
}
