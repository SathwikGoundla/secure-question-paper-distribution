import { NavLink, Outlet } from "react-router-dom";

/**
 * Shell for the Examination Centre Portal. Navigation is a UX
 * convenience only; the route guard in AppRoutes and (authoritatively)
 * the backend's require_role enforce who may see or call anything here.
 */
export function ExamCentreLayout() {
  return (
    <div className="centre-shell">
      <nav className="centre-nav" aria-label="Examination centre navigation">
        <NavLink
          to="/exam-centre"
          end
          className={({ isActive }) => (isActive ? "admin-nav-link active" : "admin-nav-link")}
        >
          My Papers
        </NavLink>
      </nav>
      <div className="centre-content">
        <Outlet />
      </div>
    </div>
  );
}
