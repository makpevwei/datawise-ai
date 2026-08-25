"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, deleteReport, emailReport, getReportPdf, listReports, type ReportOut } from "@/lib/api";
import { Card, EmptyState, ErrorBanner, SectionHeading } from "@/components/ui";

const EMAIL_STATUS_STYLES: Record<ReportOut["email_status"], string> = {
  not_sent: "bg-[var(--text-muted)]/15 text-[var(--text-muted)]",
  pending: "bg-[var(--status-warning)]/20 text-[var(--status-warning)]",
  sent: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  failed: "bg-[var(--status-critical)]/15 text-[var(--status-critical)]",
};

export default function ReportsPage() {
  const [reports, setReports] = useState<ReportOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [emailingId, setEmailingId] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // isCancelled guards against React Strict Mode's dev-only double-effect
  // invocation clobbering live state with a stale/aborted request's result
  // -- see src/lib/auth-context.tsx for the same pattern.
  const refresh = useCallback((isCancelled: () => boolean = () => false) => {
    listReports()
      .then((r) => !isCancelled() && setReports(r))
      .catch(() => !isCancelled() && setReports([]))
      .finally(() => !isCancelled() && setLoaded(true));
  }, []);

  useEffect(() => {
    let cancelled = false;
    refresh(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  async function handleOpen(report: ReportOut) {
    const blob = await getReportPdf(report.id);
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this report? This cannot be undone.")) return;
    setDeleteError(null);
    try {
      await deleteReport(id);
      refresh();
    } catch {
      setDeleteError("We couldn't delete this item. Please try again.");
    }
  }

  async function handleEmail(report: ReportOut) {
    const recipient = window.prompt(`Send "${report.title}" to which email address?`, report.email_recipient ?? "");
    if (!recipient) return;
    setEmailingId(report.id);
    setEmailError(null);
    try {
      await emailReport(report.id, recipient);
      refresh();
    } catch (e) {
      setEmailError(
        e instanceof ApiError && e.status === 503
          ? "Email delivery is not configured for this DataWise deployment yet."
          : e instanceof Error
            ? e.message
            : "Could not send the report.",
      );
    } finally {
      setEmailingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading title="Reports" subtitle="PDF exports you've generated. Opening one reuses the saved file — nothing is regenerated." />

      {emailError && (
        <p className="rounded-lg border border-[var(--status-warning)]/40 bg-[var(--status-warning)]/10 px-4 py-2 text-sm text-[var(--status-warning)]">
          {emailError}
        </p>
      )}
      {deleteError && <ErrorBanner message={deleteError} />}

      {loaded && reports.length === 0 ? (
        <EmptyState
          title="No reports have been generated yet."
          description="Export a PDF from an Ask DataWise answer to see it here."
          action={
            <Link href="/ask" className="text-sm font-medium text-[var(--series-1)] hover:underline">
              Go to Ask DataWise
            </Link>
          }
        />
      ) : (
        <Card>
          <div className="flex flex-col divide-y divide-[var(--border)]">
            {reports.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-4 py-3.5 first:pt-0 last:pb-0">
                <div>
                  <p className="text-sm font-medium text-[var(--text-primary)]">{r.title}</p>
                  <p className="mt-0.5 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                    {new Date(r.created_at).toLocaleString()}
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${EMAIL_STATUS_STYLES[r.email_status]}`}>
                      {r.email_status === "not_sent" ? "not emailed" : r.email_status}
                    </span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-4">
                  <button onClick={() => handleOpen(r)} className="text-xs font-medium text-[var(--series-1)] hover:underline">
                    Open
                  </button>
                  {r.session_id && (
                    <Link href={`/ask?session=${r.session_id}`} className="text-xs font-medium text-[var(--series-1)] hover:underline">
                      Continue Analysis
                    </Link>
                  )}
                  <button onClick={() => handleOpen(r)} className="text-xs font-medium text-[var(--text-secondary)] hover:underline">
                    Export Again
                  </button>
                  <button
                    onClick={() => handleEmail(r)}
                    disabled={emailingId === r.id}
                    className="text-xs font-medium text-[var(--series-1)] hover:underline disabled:opacity-40"
                  >
                    {emailingId === r.id ? "Sending…" : "Email"}
                  </button>
                  <button
                    onClick={() => handleDelete(r.id)}
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
