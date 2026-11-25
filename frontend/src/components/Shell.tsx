import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { hasSession, signOut } from "@/api/session";
import { setUnauthorizedHandler } from "@/api/client";
import { cn } from "@/lib/cn";

const link = ({ isActive }: { isActive: boolean }) =>
  cn(
    "rounded px-3 py-1 text-sm",
    isActive ? "bg-accent text-white" : "text-ink-muted hover:bg-line",
  );

export function signInPath(pathname: string, search: string): string {
  return `/sign-in?return=${encodeURIComponent(pathname + search)}`;
}

/** Persistent chrome and session guard for every authenticated route. */
export function Shell() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    setUnauthorizedHandler(() => navigate(signInPath(location.pathname, location.search)));
    return () => setUnauthorizedHandler(null);
  }, [navigate, location.pathname, location.search]);

  const session = useQuery({ queryKey: ["session"], queryFn: hasSession, staleTime: 60_000 });
  useEffect(() => {
    if (session.data === false) navigate(signInPath(location.pathname, location.search));
  }, [session.data, navigate, location.pathname, location.search]);

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-2">
        <strong className="text-sm">Bird review</strong>
        <nav className="flex gap-1" aria-label="Main">
          <NavLink to="/review" className={link}>
            Review
          </NavLink>
          <NavLink to="/videos" className={link}>
            Videos
          </NavLink>
          <NavLink to="/search" className={link}>
            Search
          </NavLink>
        </nav>
        <span className="rounded-full bg-surface-muted px-3 py-1 text-xs text-ink-muted">
          Local · privacy-screened crops
        </span>
        <button
          type="button"
          className="ml-auto text-sm text-ink-muted underline"
          onClick={async () => {
            await signOut();
            navigate("/sign-in");
          }}
        >
          Sign out
        </button>
      </header>
      <main className="mx-auto max-w-6xl p-4">
        <Outlet />
      </main>
    </div>
  );
}

export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div
      role="alert"
      className="my-2 flex items-center gap-3 rounded border border-danger bg-red-50 p-3 text-sm text-danger"
    >
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="ml-auto underline" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function UnfilteredMarker() {
  return (
    <span className="inline-block rounded bg-warn px-2 py-0.5 text-xs font-semibold text-white">
      Unfiltered footage
    </span>
  );
}
