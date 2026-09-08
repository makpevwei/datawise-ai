"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Spinner } from "@/components/ui";
import { Logo } from "@/components/Logo";
import {
  IconLayoutDashboard,
  IconSparkles,
  IconDatabase,
  IconClock,
  IconFileText,
  IconTrendingUp,
  IconGear,
  IconPlus,
  IconMenu,
  IconX,
} from "@/components/icons";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: IconLayoutDashboard },
  { href: "/ask", label: "Ask DataWise", icon: IconSparkles },
  { href: "/my-data", label: "My Data", icon: IconDatabase },
  { href: "/analyses", label: "Analyses", icon: IconClock },
  { href: "/reports", label: "Reports", icon: IconFileText },
  { href: "/insights", label: "Insights", icon: IconTrendingUp },
];

/** Compact top-right account dropdown menu — stays accessible regardless
 * of scroll depth because it is part of the sticky main-area header. */
function AccountMenu({ userName, userEmail, mobileCompact = false }: { userName: string; userEmail: string; mobileCompact?: boolean }) {
  const { logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const initial = userName.charAt(0).toUpperCase();

  // Close on outside click
  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] transition-colors hover:border-[var(--brand)]/50 hover:bg-[var(--background)]"
      >
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--brand-subtle)] text-xs font-semibold text-[var(--brand)]"
          aria-hidden="true"
        >
          {initial}
        </span>
        {/* In mobile compact mode only the avatar initial is shown, so long
            names don't overflow the narrow top bar. The full name is always
            visible inside the dropdown itself. */}
        {!mobileCompact && <span>{userName}</span>}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`shrink-0 text-[var(--text-muted)] transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute right-0 z-50 mt-1.5 w-52 rounded-xl border border-[var(--border)] bg-[var(--surface-1)] py-1 shadow-lg"
          role="menu"
        >
          {/* Identity */}
          <div className="border-b border-[var(--border)] px-3 py-2.5">
            <p className="text-sm font-semibold text-[var(--text-primary)]">{userName}</p>
            <p className="text-xs text-[var(--text-muted)]">{userEmail}</p>
          </div>

          {/* Navigation items */}
          <div className="py-1">
            <Link
              href="/settings"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
            >
              Settings
            </Link>
            <Link
              href="/settings"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
            >
              Preferences
            </Link>
          </div>

          {/* Sign out */}
          <div className="border-t border-[var(--border)] py-1">
            <button
              type="button"
              role="menuitem"
              onClick={() => { setOpen(false); void logout(); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-[var(--status-critical)] hover:bg-[var(--background)]"
            >
              Sign Out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

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

  if (!user) return null;

  const sidebarContent = (
    <>
      <div className="mb-6 px-2">
        <Logo withTagline />
      </div>

      <Link
        href="/ask"
        className="mb-4 flex items-center justify-center gap-1.5 rounded-lg bg-[var(--brand)] px-3 py-2 text-center text-sm font-medium text-[var(--brand-foreground)] transition-colors hover:bg-[var(--brand-hover)]"
      >
        <IconPlus size={15} /> New Analysis
      </Link>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${active
                ? "bg-[var(--brand-subtle)] text-[var(--brand)]"
                : "text-[var(--text-secondary)] hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
                }`}
            >
              <Icon size={17} className="shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Sidebar bottom — secondary access path; primary is the top-right AccountMenu */}
      <div className="mt-auto flex flex-col gap-1 border-t border-[var(--border)] pt-4">
        <p className="px-3 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">Account</p>
        <div className="px-3 py-1.5 text-sm text-[var(--text-secondary)]">{user.full_name}</div>
        <Link
          href="/settings"
          className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${pathname === "/settings"
            ? "bg-[var(--brand-subtle)] text-[var(--brand)]"
            : "text-[var(--text-secondary)] hover:bg-[var(--background)] hover:text-[var(--text-primary)]"
            }`}
        >
          <IconGear size={17} className="shrink-0" />
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
      {/* Desktop sticky sidebar — stays fixed while main content scrolls */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-1)] px-4 py-5 md:flex md:sticky md:top-0 md:h-screen md:overflow-y-auto">
        {sidebarContent}
      </aside>

      {/* Mobile top bar */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-2 md:hidden">
        <Logo size={20} />
        <div className="flex items-center gap-1.5">
          {/* AccountMenu in the mobile bar only shows the avatar initial,
              not the full name — long names overflow the narrow top bar. */}
          <AccountMenu userName={user.full_name} userEmail={user.email} mobileCompact />
          {/* p-2.5 gives a ~44px tap target (10px pad + 18px icon + 10px pad).
              Was p-1.5 (~30px), which failed the WCAG 2.5.5 minimum. */}
          <button
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open menu"
            aria-expanded={mobileNavOpen}
            className="rounded-lg border border-[var(--border)] p-2.5 text-[var(--text-primary)]"
          >
            <IconMenu size={18} />
          </button>
        </div>
      </div>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileNavOpen(false)} />
          <aside className="relative z-50 flex w-64 flex-col bg-[var(--surface-1)] px-4 py-5 shadow-xl">
            {/* p-2.5 → ~44px tap target. Was p-1.5 (~26px). */}
            <button
              onClick={() => setMobileNavOpen(false)}
              aria-label="Close menu"
              className="mb-4 self-end rounded-lg border border-[var(--border)] p-2.5 text-[var(--text-secondary)]"
            >
              <IconX size={16} />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      {/* Main content area — scrollable, with sticky top bar containing account menu */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Sticky top bar — desktop only; keeps AccountMenu accessible at all scroll depths */}
        <header className="sticky top-0 z-30 hidden items-center justify-end border-b border-[var(--border)] bg-[var(--surface-1)]/95 px-8 py-2.5 backdrop-blur-sm md:flex">
          <AccountMenu userName={user.full_name} userEmail={user.email} />
        </header>

        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
