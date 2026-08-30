import { Link, NavLink, Outlet } from "react-router-dom";
import { ArrowRight } from "lucide-react";

const REPO = "https://github.com/AllergySnipe/runbook";

const links = [
  { to: "/", label: "Overview", end: true },
  { to: "/how-it-works", label: "How it works" },
  { to: "/decisions", label: "Decisions" },
];

export default function EditorialLayout() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b bg-[var(--color-bg)]/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
          <Link to="/" className="flex items-center gap-2">
            <Logo />
            <span className="font-display text-lg font-medium">Runbook</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) =>
                  `rounded px-2.5 py-1.5 transition-colors ${
                    isActive
                      ? "text-[var(--color-ink)]"
                      : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
            <a
              href={REPO}
              target="_blank"
              rel="noreferrer"
              className="ml-1 rounded p-1.5 text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
              aria-label="Source on GitHub"
            >
              <GithubMark />
            </a>
            <Link
              to="/incidents"
              className="ml-2 inline-flex items-center gap-1.5 rounded-md border border-[var(--color-accent)] px-3 py-1.5 font-mono text-xs font-medium uppercase tracking-wide text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)]"
            >
              Console <ArrowRight size={13} />
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-14">
        <Outlet />
      </main>

      <footer className="mt-24 border-t">
        <div className="mx-auto flex max-w-5xl flex-col gap-1 px-6 py-8 text-xs text-[var(--color-ink-faint)]">
          <p>
            The environment is <span className="term">simulated</span> — a fixture-backed stand-in
            for real infrastructure. No production systems are touched.
          </p>
          <p>
            <a href={REPO} target="_blank" rel="noreferrer" className="hover:text-[var(--color-ink-muted)]">
              github.com/AllergySnipe/runbook
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}

export function GithubMark({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export function Logo({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="1" y="1" width="22" height="22" rx="6" stroke="var(--color-accent)" strokeWidth="1.5" />
      <path
        d="M7 12h3l2 5 3-10 2 5h1"
        stroke="var(--color-accent)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
