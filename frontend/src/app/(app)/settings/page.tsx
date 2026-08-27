"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ApiError,
  deleteSession,
  listDatasetLibrary,
  listReports,
  listSessions,
  updateUserSettings,
  type CurrencyCode,
  type DatasetLibraryItem,
  type ReportOut,
  type SessionOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button, Card, ErrorBanner, SectionHeading, Spinner } from "@/components/ui";

const CURRENCY_OPTIONS: { code: CurrencyCode; label: string }[] = [
  { code: "NGN", label: "₦ Nigerian Naira" },
  { code: "USD", label: "$ US Dollar" },
  { code: "EUR", label: "€ Euro" },
  { code: "GBP", label: "£ British Pound" },
  { code: "JPY", label: "¥ Japanese Yen" },
  { code: "INR", label: "₹ Indian Rupee" },
  { code: "CAD", label: "C$ Canadian Dollar" },
  { code: "AUD", label: "A$ Australian Dollar" },
];

const DECIMAL_OPTIONS = [0, 1, 2, 3, 4];

type SettingsTab = "profile" | "preferences" | "workspace";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "preferences", label: "Preferences" },
  { id: "workspace", label: "Workspace & Sessions" },
];

export default function SettingsPage() {
  const { user, setUser } = useAuth();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

  // Preferences state
  const [currency, setCurrency] = useState<CurrencyCode>(user?.currency ?? "USD");
  const [decimalPlaces, setDecimalPlaces] = useState<number>(user?.decimal_places ?? 2);
  const [saving, setSaving] = useState(false);
  const [prefError, setPrefError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Workspace state
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [datasets, setDatasets] = useState<DatasetLibraryItem[]>([]);
  const [reports, setReports] = useState<ReportOut[]>([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [clearConfirm, setClearConfirm] = useState<string | null>(null); // session id to confirm clear
  const [clearingId, setClearingId] = useState<string | null>(null);

  const refreshWorkspace = useCallback((isCancelled: () => boolean = () => false) => {
    setWorkspaceLoading(true);
    Promise.all([
      listSessions().catch(() => []),
      listDatasetLibrary().catch(() => []),
      listReports().catch(() => []),
    ]).then(([s, d, r]) => {
      if (isCancelled()) return;
      setSessions(s);
      setDatasets(d);
      setReports(r);
      setWorkspaceLoading(false);
    });
  }, []);

  useEffect(() => {
    if (activeTab !== "workspace") return;
    let cancelled = false;
    // Defer to avoid synchronous setState inside an effect body
    // (react-hooks/set-state-in-effect rule).
    Promise.resolve().then(() => {
      if (!cancelled) refreshWorkspace(() => cancelled);
    });
    return () => { cancelled = true; };
  }, [activeTab, refreshWorkspace]);

  if (!user) return null;

  const dirty = currency !== user.currency || decimalPlaces !== user.decimal_places;

  async function handleSavePrefs() {
    setSaving(true);
    setPrefError(null);
    setSaved(false);
    try {
      const updated = await updateUserSettings({ currency, decimal_places: decimalPlaces });
      setUser(updated);
      setSaved(true);
    } catch (e) {
      setPrefError(e instanceof ApiError ? e.message : "We couldn't save your settings. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteSession(id: string) {
    setClearingId(id);
    setWorkspaceError(null);
    try {
      await deleteSession(id);
      setClearConfirm(null);
      refreshWorkspace();
    } catch {
      setWorkspaceError("Could not delete this session. Please try again.");
    } finally {
      setClearingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading title="Settings" subtitle="Manage your profile, display preferences, and workspace." />

      {/* Tab nav */}
      <div className="flex gap-1 border-b border-[var(--border)]">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${activeTab === tab.id
              ? "border-b-2 border-[var(--series-1)] text-[var(--series-1)]"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Profile tab */}
      {activeTab === "profile" && (
        <Card>
          <SectionHeading title="Profile" />
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs font-medium text-[var(--text-secondary)]">Full Name</label>
              <p className="mt-1 text-sm text-[var(--text-primary)]">{user.full_name}</p>
            </div>
            <div>
              <label className="text-xs font-medium text-[var(--text-secondary)]">Email</label>
              <p className="mt-1 text-sm text-[var(--text-primary)]">{user.email}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Preferences tab */}
      {activeTab === "preferences" && (
        <Card>
          <SectionHeading
            title="Preferences"
            subtitle="Currency and decimal formatting are display-only — they never change the underlying calculated values."
          />
          {prefError && <ErrorBanner message={prefError} />}
          {saved && <p className="mb-4 text-sm text-[var(--status-good)]">Settings saved.</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label htmlFor="settings-currency" className="text-xs font-medium text-[var(--text-secondary)]">
                Currency
              </label>
              <select
                id="settings-currency"
                value={currency}
                onChange={(e) => { setCurrency(e.target.value as CurrencyCode); setSaved(false); }}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
              >
                {CURRENCY_OPTIONS.map((c) => (
                  <option key={c.code} value={c.code}>{c.label}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="settings-decimal-places" className="text-xs font-medium text-[var(--text-secondary)]">
                Decimal Places
              </label>
              <select
                id="settings-decimal-places"
                value={decimalPlaces}
                onChange={(e) => { setDecimalPlaces(Number(e.target.value)); setSaved(false); }}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
              >
                {DECIMAL_OPTIONS.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="mt-4">
            <Button onClick={handleSavePrefs} disabled={saving || !dirty}>
              {saving ? "Saving…" : "Save Settings"}
            </Button>
          </div>
        </Card>
      )}

      {/* Workspace & Sessions tab */}
      {activeTab === "workspace" && (
        <div className="flex flex-col gap-6">
          {workspaceError && <ErrorBanner message={workspaceError} />}

          {/* Summary */}
          <Card>
            <SectionHeading
              title="Workspace Summary"
              subtitle="Everything in your DataWise workspace — datasets, analyses, and reports."
            />
            {workspaceLoading ? (
              <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
                <Spinner /> Loading workspace…
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-3">
                {[
                  { label: "Datasets", value: datasets.length, href: "/my-data" },
                  { label: "Analyses", value: sessions.length, href: "/analyses" },
                  { label: "Reports", value: reports.length, href: "/reports" },
                ].map((item) => (
                  <Link
                    key={item.label}
                    href={item.href}
                    className="flex flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 hover:border-[var(--series-1)]/50"
                  >
                    <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">{item.label}</p>
                    <p className="text-2xl font-semibold tabular-nums text-[var(--text-primary)]">{item.value}</p>
                  </Link>
                ))}
              </div>
            )}
          </Card>

          {/* Sessions list */}
          <Card>
            <div className="mb-4 flex items-center justify-between gap-3">
              <SectionHeading title="Analysis Sessions" subtitle="Your saved conversation threads and analyses." />
              <Link
                href="/ask"
                className="shrink-0 rounded-lg bg-[var(--series-1)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
              >
                + New Analysis
              </Link>
            </div>
            {workspaceLoading ? (
              <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]"><Spinner /></div>
            ) : sessions.length === 0 ? (
              <p className="text-sm text-[var(--text-secondary)]">No analyses yet. Start by asking DataWise a business question.</p>
            ) : (
              <div className="flex flex-col divide-y divide-[var(--border)]">
                {sessions.map((s) => (
                  <div key={s.id} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-[var(--text-primary)]">{s.title}</p>
                        <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                          {s.message_count} message{s.message_count === 1 ? "" : "s"} · last active{" "}
                          {new Date(s.last_activity_at).toLocaleString()}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-3 text-xs">
                        <Link href={`/ask?session=${s.id}`} className="font-medium text-[var(--series-1)] hover:underline">
                          Continue
                        </Link>
                        {clearConfirm === s.id ? (
                          <div className="flex items-center gap-2">
                            <span className="text-[var(--text-muted)]">Delete?</span>
                            <button
                              onClick={() => handleDeleteSession(s.id)}
                              disabled={clearingId === s.id}
                              className="font-medium text-[var(--status-critical)] hover:underline disabled:opacity-40"
                            >
                              {clearingId === s.id ? "Deleting…" : "Yes, delete"}
                            </button>
                            <button
                              onClick={() => setClearConfirm(null)}
                              className="font-medium text-[var(--text-secondary)] hover:underline"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setClearConfirm(s.id)}
                            className="font-medium text-[var(--text-secondary)] hover:underline"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Start fresh */}
          <Card>
            <SectionHeading title="Start Fresh" subtitle="Begin a new analysis without deleting your existing work." />
            <p className="mb-4 text-sm text-[var(--text-secondary)]">
              Your existing sessions, datasets, and reports will remain available. A new conversation starts immediately.
            </p>
            <Button
              variant="secondary"
              onClick={() => router.push("/ask")}
            >
              + Start New Analysis
            </Button>
          </Card>

          {/* Danger zone */}
          <Card>
            <SectionHeading title="Danger Zone" />
            <div className="rounded-xl border border-[var(--status-critical)]/20 bg-[var(--status-critical)]/5 p-4">
              <p className="text-sm font-medium text-[var(--text-primary)]">Clear all sessions</p>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                This will permanently delete all your analysis sessions and conversation history.
                Uploaded datasets and reports are not affected.
              </p>
              <div className="mt-3">
                <ClearAllSessions
                  sessions={sessions}
                  onCleared={() => refreshWorkspace()}
                />
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

/** Inline component that manages the "clear all sessions" confirmation flow. */
function ClearAllSessions({
  sessions,
  onCleared,
}: {
  sessions: SessionOut[];
  onCleared: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClearAll() {
    setClearing(true);
    setError(null);
    try {
      await Promise.all(sessions.map((s) => deleteSession(s.id)));
      setConfirming(false);
      onCleared();
    } catch {
      setError("Some sessions could not be deleted. Please try again.");
    } finally {
      setClearing(false);
    }
  }

  if (!confirming) {
    return (
      <Button
        variant="secondary"
        onClick={() => setConfirming(true)}
        disabled={sessions.length === 0}
      >
        Clear All Sessions
      </Button>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <ErrorBanner message={error} />}
      <p className="text-sm font-medium text-[var(--status-critical)]">
        This will permanently delete all {sessions.length} session{sessions.length === 1 ? "" : "s"}. This cannot be undone.
      </p>
      <div className="flex gap-2">
        <Button onClick={handleClearAll} disabled={clearing}>
          {clearing ? <Spinner /> : null} {clearing ? "Clearing…" : "Yes, clear all"}
        </Button>
        <Button variant="secondary" onClick={() => setConfirming(false)} disabled={clearing}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
