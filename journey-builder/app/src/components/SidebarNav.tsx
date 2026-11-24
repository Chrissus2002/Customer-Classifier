import { NavLink } from "react-router-dom";
import { routes } from "../routes";

export function SidebarNav() {
  return (
    <nav className="workspace-nav" aria-label="Journey Builder workspace">
      <NavLink
        to={routes.journeys}
        className={({ isActive }) => (isActive ? "nav-chip is-active" : "nav-chip")}
      >
        Journeys
      </NavLink>
    </nav>
  );
}
