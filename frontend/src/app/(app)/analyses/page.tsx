"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { deleteSession, listSessions, type SessionOut } from "@/lib/api";
import { Card, EmptyState, ErrorBanner, SectionHeading } from "@/components/ui";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  archived: "bg-[var(--text-muted)]/15 text-[var(--text-muted)]",
};

export default function AnalysesPage() {
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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
      refresh();
    } catch {
      setDeleteError("We couldn't delete this item. Please try again.");
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
            <Link href="/ask" className="text-sm font-medium text-[var(--series-1)] hover:underline">
              Start an Analysis
            </Link>
          }
        />
      ) : (
        <Card>
          <div className="flex flex-col divide-y divide-[var(--border)]">
            {sessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between gap-4 py-3.5 first:pt-0 last:pb-0">
                <div>
                  <p className="text-sm font-medium text-[var(--text-primary)]">{s.title}</p>
                  <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                    {s.message_count} message{s.message_count === 1 ? "" : "s"} · last activity{" "}
                    {new Date(s.last_activity_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-4">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[s.status] ?? STATUS_STYLES.active}`}
                  >
                    {s.status}
                  </span>
                  {/* View opens the session in read-only display mode —
                      the existing /ask?session= route already renders the
                      full conversation history; the textarea input allows
                      continuation so both "View" and "Edit / Continue" point
                      to the same URL, which is correct: the user can simply
                      read through the prior conversation or type a follow-up. */}
                  <Link
                    href={`/ask?session=${s.id}`}
                    className="text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:underline"
                  >
                    View
                  </Link>
                  <Link href={`/ask?session=${s.id}`} className="text-xs font-medium text-[var(--series-1)] hover:underline">
                    Edit / Continue
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
        </Card>
      )}
    </div>
  );
}
