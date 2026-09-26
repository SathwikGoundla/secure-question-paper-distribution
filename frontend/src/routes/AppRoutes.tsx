import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ProtectedRoute } from "./ProtectedRoute";
import { LoginPage } from "../pages/auth/LoginPage";
import { OTPPage } from "../pages/auth/OTPPage";
import { AdminPlaceholderPage } from "../pages/placeholder/AdminPlaceholderPage";
import { ExamCentrePlaceholderPage } from "../pages/placeholder/ExamCentrePlaceholderPage";
import { UnauthorizedPage } from "../pages/errors/UnauthorizedPage";
import { NotFoundPage } from "../pages/errors/NotFoundPage";
import { LoadingIndicator } from "../components/common/LoadingIndicator";

/**
 * Sends an authenticated user to the section matching their role.
 *
 * Role -> destination mapping is a Phase 6A navigation decision, not a
 * backend contract: the backend's fixed role set is Admin,
 * "Examination Centre", Auditor (backend/app/models/role.py). Admin
 * and Auditor are both routed to the Admin Portal placeholder because
 * Auditor is a read-only variant of the same administrative area
 * (SRS Section 4 / LLD Section 15 RBAC table — Auditor has read-only
 * access to audit logs and dashboard reports, which live in the same
 * portal as Admin's own dashboard). This is documented explicitly so
 * it can be revisited in Phase 6B once the Admin Portal's actual
 * per-role views are designed.
 */
function RoleHome() {
  const { user } = useAuth();
  if (user?.role === "Examination Centre") {
    return <Navigate to="/exam-centre" replace />;
  }
  return <Navigate to="/admin" replace />;
}

export function AppRoutes() {
  const { isInitializing } = useAuth();

  if (isInitializing) {
    return <LoadingIndicator label="Loading application…" />;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/otp" element={<OTPPage />} />
      <Route path="/unauthorized" element={<UnauthorizedPage />} />

      <Route
        path="/admin"
        element={
          <ProtectedRoute allowedRoles={["Admin", "Auditor"]}>
            <AdminPlaceholderPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/exam-centre"
        element={
          <ProtectedRoute allowedRoles={["Examination Centre"]}>
            <ExamCentrePlaceholderPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <RoleHome />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
