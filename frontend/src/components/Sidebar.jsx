import { NavLink } from "react-router-dom";

const navItems = [
  { label: "Dashboard", path: "/dashboard" },
  { label: "Requests", path: "/requests" },
  { label: "Dispatch", path: "/dispatch" },
  { label: "Crews", path: "/crews" },
  { label: "Reports", path: "/reports" },
];

function Sidebar() {
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border bg-sidebar text-white">
      <div className="border-b border-white/15 px-5 py-6">
        <img
          src="/logo.png"
          alt="City of Calgary"
          className="mb-4 h-12 w-auto object-contain"
        />
        <h1 className="mt-1 text-base font-semibold leading-tight">
          311 Operations
        </h1>
      </div>

      <nav
        className="flex flex-1 flex-col gap-1 px-3 py-4"
        aria-label="Main navigation"
      >
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              [
                "rounded-sm px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "border-l-4 border-calgary-red bg-white/10 pl-2 text-white"
                  : "border-l-4 border-transparent text-white/75 hover:bg-white/5 hover:text-white",
              ].join(" ")
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-white/15 px-5 py-4 text-xs text-white/50">
        Internal use only
      </div>
    </aside>
  );
}

export default Sidebar;
