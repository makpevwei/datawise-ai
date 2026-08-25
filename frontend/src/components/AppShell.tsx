"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Spinner } from "@/components/ui";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/ask", label: "Ask DataWise" },
  { href: "/my-data", label: "My Data" },
  { href: "/analyses", label: "Analyses" },
  { href: "/reports", label: "Reports" },
  { href: "/insights", label: "Insights" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  // A route change is the natural signal a navigation just happened --
  // close the mobile drawer so it doesn't stay open over the new page.
  // Async even though the update is trivial -- setState synchronously
  // inside an effect body risks cascading renders (react-hooks/set-state-in-effect).
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => !cancelled && setMobileNavOpen(false));
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (loading) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (!user) {
    return null;
  }

  const sidebarContent = (
    <>
      <div className="mb-6 px-2">
        <p className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">DATAWISE AI</p>
        <p className="text-xs text-[var(--text-secondary)]">Your AI Business Analyst</p>
      </div>

      <Link
        href="/ask"
        className="mb-4 rounded-lg bg-[var(--series-1)] px-3 py-2 text-center text-sm font-medium text-white transition-colors hover:opacity-90"
      >
        + New Analysis
      </Link>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-[var(--series-1)]/10 text-[var(--series-1)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-1 border-t border-[var(--border)] pt-4">
        <p className="px-3 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Settings</p>
        <div className="px-3 py-1.5 text-sm text-[var(--text-secondary)]">{user.full_name}</div>
        <Link
          href="/settings"
          className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
            pathname === "/settings"
              ? "bg-[var(--series-1)]/10 text-[var(--series-1)]"
              : "text-[var(--text-secondary)] hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
          }`}
        >
          Preferences
        </Link>
        <button
          onClick={() => void logout()}
          className="rounded-lg px-3 py-2 text-left text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
        >
          Sign Out
        </button>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen w-full flex-col md:flex-row">
      {/* Desktop: always-visible sidebar. Below md, this is replaced by the
          top bar + off-canvas drawer below -- a fixed w-60 sidebar with no
          responsive handling was crushing page content into an unreadable
          sliver at phone widths. */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-1)] px-4 py-5 md:flex">
        {sidebarContent}
      </aside>

      {/* Mobile top bar with a menu toggle -- hidden on desktop, where the
          persistent sidebar above already shows this. */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-3 md:hidden">
        <p className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">DATAWISE AI</p>
        <button
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open menu"
          aria-expanded={mobileNavOpen}
          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
        >
          Menu
        </button>
      </div>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileNavOpen(false)} />
          <aside className="relative z-50 flex w-64 flex-col bg-[var(--surface-1)] px-4 py-5 shadow-xl">
            <button
              onClick={() => setMobileNavOpen(false)}
              aria-label="Close menu"
              className="mb-4 self-end rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--text-secondary)]"
            >
              Close
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-8">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  );
}
