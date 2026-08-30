import { Link, Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="mx-auto max-w-4xl px-5 py-8">
      <header className="mb-8 flex items-baseline justify-between border-b border-zinc-800 pb-4">
        <Link to="/" className="text-lg font-semibold text-zinc-100">
          Runbook
        </Link>
        <span className="text-xs text-zinc-500">on-call incident copilot · sim environment</span>
      </header>
      <Outlet />
    </div>
  );
}
