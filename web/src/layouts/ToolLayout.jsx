import { Link, NavLink, Outlet } from "react-router-dom";
import { ListTree, FlaskConical, ShieldAlert, ArrowLeft } from "lucide-react";
import { Logo } from "./EditorialLayout.jsx";

const nav = [
  { to: "/incidents", label: "incidents", icon: ListTree },
  { to: "/evals", label: "evals", icon: FlaskConical },
  { to: "/security", label: "security", icon: ShieldAlert },
];

export default function ToolLayout() {
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b bg-[var(--color-surface)] md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:border-b-0 md:border-r">
        <div className="flex h-full flex-col px-3 py-4">
          <Link to="/" className="mb-6 flex items-center gap-2 px-2">
            <Logo />
            <span className="font-display text-[1.05rem] font-medium">Runbook</span>
          </Link>
          <nav className="flex gap-1 md:flex-col">
            {nav.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-md px-2.5 py-1.5 font-mono text-xs uppercase tracking-wide transition-colors ${
                    isActive
                      ? "bg-[var(--color-surface-2)] text-[var(--color-ink)]"
                      : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
                  }`
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto hidden md:block">
            <Link
              to="/"
              className="flex items-center gap-1.5 px-2.5 py-1.5 font-mono text-[0.7rem] uppercase tracking-wide text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
            >
              <ArrowLeft size={12} /> overview
            </Link>
            <p className="mt-2 px-2.5 text-[0.7rem] leading-relaxed text-[var(--color-ink-faint)]">
              Simulated environment — a fixture-backed stand-in. No production systems are touched.
            </p>
          </div>
        </div>
      </aside>

      <main className="console-grid min-w-0 flex-1">
        <div className="mx-auto max-w-4xl px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
