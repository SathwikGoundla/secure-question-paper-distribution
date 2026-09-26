import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";

interface NavItem {
  to: string;
  label: string;
  /** Roles allowed to see this nav item, mirroring the backend RBAC table (LLD Section 15). */
  roles: Array<"Admin" | "Auditor">;
  end?: boolean;
}

/**
 * Nav items and their role visibility mirror the backend's real RBAC
 * table exactly (backend/app/api/deps.py `require_role` calls in
 * papers.py / admin.py / audit.py — see PROJECT_STATE.md Section 17):
 * an Auditor genuinely cannot register/view papers or manage
 * examination centres, so those links are not shown to that role at
 * all. This is a UX convenience only — the backend independently
 * enforces every one of these checks regardless of what the sidebar
 * shows.
 */
const NAV_ITEMS: NavItem[] = [
  { to: "/admin", label: "Dashboard", roles: ["Admin", "Auditor"], end: true },
  { to: "/admin/papers", label: "Question Papers", roles: ["Admin"] },
  { to: "/admin/exam-centres", label: "Exam Centres", roles: ["Admin"] },
  { to: "/admin/audit-logs", label: "Audit Logs", roles: ["Admin", "Auditor"] },
  { to: "/admin/security-events", label: "Security Events", roles: ["Admin", "Auditor"] },
];

export function AdminLayout() {
  const { user } = useAuth();
  const role = user?.role;

  const visibleItems = NAV_ITEMS.filter(
    (item) => role === "Admin" || role === "Auditor" ? item.roles.includes(role) : false,
  );

  return (
    <div className="admin-shell">
      <nav className="admin-sidebar" aria-label="Admin navigation">
        <ul>
          {visibleItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? "admin-nav-link active" : "admin-nav-link")}
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="admin-content">
        <Outlet />
      </div>
    </div>
  );
}
