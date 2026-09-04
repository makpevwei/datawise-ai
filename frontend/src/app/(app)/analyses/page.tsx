"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { deleteSession, listSessions, type SessionOut } from "@/lib/api";
import { Button, Card, EmptyState, ErrorBanner, SectionHeading } from "@/components/ui";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  archived: "bg-[var(--text-muted)]/15 text-[var(--text-muted)]",
};

const DELETE_FAILED_MESSAGE = "We couldn't delete this item. Please try again.";

export default function AnalysesPage() {
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  // isCancelled guards against React Strict Mode's dev-only double-effect
  // invocation clobbering live state with a stale/aborted request's result
  // -- see src/lib/auth-context.tsx for the same pattern.
  const refresh = useCallback((isCancelled: () => boolean = () => false) => {
    listSessions()
      .then((s) => !isCancelled() && setSessions(s))
      .catch(() => !isCancelled() && setSessions([]))
      .finally(() => !isCancelled() && setLoaded(true));
  }, []);

  useEffect(() => {
    let cancelled = false;
    refresh(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  async function handleDelete(id: string) {
    if (!confirm("Delete this analysis? This cannot be undone.")) return;
    setDeleteError(null);
    try {
      await deleteSession(id);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      refresh();
    } catch {
      setDeleteError(DELETE_FAILED_MESSAGE);
    }
  }

  function toggleSelection(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelectedIds((prev) => (prev.size === sessions.length ? new Set() : new Set(sessions.map((s) => s.id))));
  }

  async function handleBulkDelete() {
    const count = selectedIds.size;
    if (count === 0) return;
    if (!confirm(`Delete ${count} analysis thread${count === 1 ? "" : "s"}? This cannot be undone.`)) return;
    setDeleteError(null);
    setBulkDeleting(true);
    try {
      const results = await Promise.allSettled([...selectedIds].map((id) => deleteSession(id)));
      if (results.some((r) => r.status === "rejected")) setDeleteError(DELETE_FAILED_MESSAGE);
      setSelectedIds(new Set());
      refresh();
    } finally {
      setBulkDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading title="Analyses" subtitle="Every question thread you've started with DataWise, saved so you can pick up where you left off." />

      {deleteError && <ErrorBanner message={deleteError} />}

      {loaded && sessions.length === 0 ? (
        <EmptyState
          title="No analyses yet."
          description="Ask DataWise a question to start your first analysis."
          action={
            <Link href="/ask" className="text-sm font-medium text-[var(--brand)] hover:underline">
              Start an Analysis
            </Link>
          }
        />
      ) : (
        <Card>
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                <input
                  type="checkbox"
                  checked={sessions.length > 0 && selectedIds.size === sessions.length}
                  ref={(el) => {
                    if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < sessions.length;
                  }}
                  onChange={toggleAll}
                  className="h-4 w-4 rounded border-[var(--border)]"
                />
                Select all
              </label>
              {selectedIds.size > 0 && (
                <>
                  <span className="text-xs text-[var(--text-secondary)]">{selectedIds.size} selected</span>
                  <Button variant="ghost" onClick={() => setSelectedIds(new Set())} disabled={bulkDeleting}>
                    Clear
                  </Button>
                  <button
                    onClick={handleBulkDelete}
                    disabled={bulkDeleting}
                    className="text-xs font-medium text-[var(--status-critical)] hover:underline disabled:opacity-40"
                  >
                    {bulkDeleting ? "Deleting…" : `Delete ${selectedIds.size} selected`}
                  </button>
                </>
              )}
            </div>

            <div className="flex flex-col divide-y divide-[var(--border)]">
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className="flex flex-col gap-2 py-3.5 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
                >
                  <div className="flex min-w-0 items-start gap-3 sm:items-center">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(s.id)}
                      onChange={() => toggleSelection(s.id)}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-[var(--border)] sm:mt-0"
                    />
                    <div className="min-w-0">
                      {/* The question itself is the "View" affordance now —
                          clicking it opens /ask?session= exactly like the old
                          separate "View" link did, just without a redundant
                          control next to an identically-destined "Edit /
                          Continue" link. line-clamp-2 (not truncate) so a
                          long question stays fully readable on narrow
                          screens, matching the mobile-truncation fix already
                          used for card/chart titles elsewhere in the app. */}
                      <Link
                        href={`/ask?session=${s.id}`}
                        title={s.title}
                        className="line-clamp-2 text-sm font-medium text-[var(--text-primary)] hover:text-[var(--brand)] hover:underline"
                      >
                        {s.title}
                      </Link>
                      <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                        {s.message_count} message{s.message_count === 1 ? "" : "s"} · last activity{" "}
                        {new Date(s.last_activity_at).toLocaleString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-4 pl-7 sm:pl-0">
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[s.status] ?? STATUS_STYLES.active}`}
                    >
                      {s.status}
                    </span>
                    {/* Same destination and behavior as before (pre-fills the
                        question box so the user can either type something
                        new or change this one and resubmit) — just relabeled
                        now that "View" no longer needs distinguishing from
                        it. */}
                    <Link href={`/ask?session=${s.id}`} className="text-xs font-medium text-[var(--brand)] hover:underline">
                      Edit
                    </Link>
                    <button
                      onClick={() => handleDelete(s.id)}
                      className="text-xs font-medium text-[var(--status-critical)] hover:underline"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
