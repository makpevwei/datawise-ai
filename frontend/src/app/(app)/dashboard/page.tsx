"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listDatasetLibrary,
  listReports,
  listSessions,
  type DatasetLibraryItem,
  type ReportOut,
  type SessionOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Card, EmptyState, SectionHeading } from "@/components/ui";
import { ManagementDashboard } from "@/components/ManagementDashboard";

export default function DashboardPage() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [datasets, setDatasets] = useState<DatasetLibraryItem[]>([]);
  const [reports, setReports] = useState<ReportOut[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listSessions().catch(() => []),
      listDatasetLibrary().catch(() => []),
      listReports().catch(() => []),
    ]).then(([s, d, r]) => {
      if (cancelled) return;
      setSessions(s);
      setDatasets(d);
      setReports(r);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const continueSession = sessions[0];
  const currency = user?.currency ?? "USD";
  const decimalPlaces = user?.decimal_places ?? 2;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-[var(--text-primary)]">
          Welcome back{user ? `, ${user.full_name.split(" ")[0]}` : ""}
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--text-secondary)]">
          DataWise AI turns business data and documents into clear, evidence-backed decisions. Upload your
          data, ask questions in natural language, and let DataWise analyze, visualize and explain what the
          evidence shows.
        </p>
      </div>

      <ManagementDashboard datasets={datasets.map((dataset) => ({
        id: dataset.id,
        name: dataset.display_name,
        source_file: dataset.display_name,
        sheet_name: null,
        row_count: dataset.row_count ?? 0,
        column_count: 0,
        kind: "uploaded" as const,
        quality_rating: "good" as const,
        created_at: dataset.created_at ?? new Date().toISOString(),
      }))} currency={currency} decimalPlaces={decimalPlaces} />

      <section>
        <SectionHeading title="Continue Analysis" />
        {continueSession ? (
          <Card className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">{continueSession.title}</p>
              <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                Last activity {new Date(continueSession.last_activity_at).toLocaleString()}
              </p>
            </div>
            <Link
              href={`/ask?session=${continueSession.id}`}
              className="rounded-lg bg-[var(--brand)] px-3.5 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              Continue
            </Link>
          </Card>
        ) : (
          loaded && (
            <EmptyState
              title="No analyses yet."
              description="Ask DataWise a question to start your first analysis."
              action={
                <Link href="/ask" className="text-sm font-medium text-[var(--brand)] hover:underline">
                  Start an Analysis
                </Link>
              }
            />
          )
        )}
      </section>

      <section>
        <SectionHeading title="Recent Data" />
        {datasets.length === 0 ? (
          loaded && (
            <EmptyState
              title="No datasets uploaded yet."
              description="Upload a dataset to start analyzing your business data."
              action={
                <Link href="/my-data" className="text-sm font-medium text-[var(--brand)] hover:underline">
                  Upload Dataset
                </Link>
              }
            />
          )
        ) : (
          <Card>
            <div className="flex flex-col divide-y divide-[var(--border)]">
              {datasets.slice(0, 5).map((d) => (
                <div key={d.id} className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
                  <span className="text-sm text-[var(--text-primary)]">{d.display_name}</span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {new Date(d.created_at).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </section>

      <section>
        <SectionHeading title="Recent Analyses" />
        {sessions.length === 0 ? (
          loaded && <EmptyState title="No analyses yet." description="Ask DataWise a question to get started." />
        ) : (
          <Card>
            <div className="flex flex-col divide-y divide-[var(--border)]">
              {sessions.slice(0, 5).map((s) => (
                <Link
                  key={s.id}
                  href={`/ask?session=${s.id}`}
                  className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0 hover:opacity-80"
                >
                  <span className="text-sm text-[var(--text-primary)]">{s.title}</span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {new Date(s.last_activity_at).toLocaleDateString()}
                  </span>
                </Link>
              ))}
            </div>
          </Card>
        )}
      </section>

      <section>
        <SectionHeading title="Recent Reports" />
        {reports.length === 0 ? (
          loaded && <EmptyState title="No reports yet." description="Export a PDF from an Ask DataWise answer to see it here." />
        ) : (
          <Card>
            <div className="flex flex-col divide-y divide-[var(--border)]">
              {reports.slice(0, 5).map((r) => (
                <div key={r.id} className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
                  <span className="text-sm text-[var(--text-primary)]">{r.title}</span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {new Date(r.created_at).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}
