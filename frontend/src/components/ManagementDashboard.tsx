"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getInsights, getKpiSuggestions } from "@/lib/api";
import type { DatasetSummary, Insight, KPISuggestion } from "@/lib/types";
import { Card, EmptyState, ErrorBanner, SectionHeading, SourceLabelBadge, Spinner, formatCurrency, formatNumber } from "./ui";

const MAX_KPIS = 6;
const MAX_FINDINGS = 5;

function isMonetary(label: string): boolean {
  return /revenue|sales|profit|margin|price|cost|amount|spend|value/i.test(label);
}

function recommendationFor(insight: Insight): string {
  switch (insight.category) {
    case "concentration_risk":
      return "Protect the leading contributor and build a plan to reduce reliance on a single segment.";
    case "significant_change":
      return "Review the period-over-period drivers with the responsible team before committing resources.";
    case "anomaly":
      return "Investigate the unusual records to confirm whether they are data issues or operational exceptions.";
    case "data_quality":
      return "Resolve the data-quality issue before using affected fields for management targets or forecasts.";
    case "top_performer":
      return "Study the leading contributor's drivers and test whether the approach can be applied elsewhere.";
    default:
      return "Review this pattern with the business owner and use it to prioritize the next analysis.";
  }
}

export function ManagementDashboard({ datasets, currency, decimalPlaces }: { datasets: DatasetSummary[]; currency: string; decimalPlaces: number }) {
  const [kpis, setKpis] = useState<KPISuggestion[] | null>(null);
  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all(datasets.map((dataset) => getKpiSuggestions(dataset.id)))
      .then((results) => !cancelled && setKpis(results.flat().filter((kpi) => kpi.preview_value !== null)))
      .catch(() => !cancelled && setError("DataWise could not calculate dashboard KPIs."));
    Promise.all(datasets.map((dataset) => getInsights(dataset.id)))
      .then((results) => !cancelled && setInsights(results.flat()))
      .catch(() => !cancelled && setError("DataWise could not generate business findings."));
    return () => {
      cancelled = true;
    };
  }, [datasets]);

  if (datasets.length === 0) {
    return (
      <EmptyState
        title="Load your business data to begin"
        description="Upload the Case Study 4 business dataset, then DataWise will calculate KPIs, findings, and recommendations from the actual records."
        action={<Link className="text-sm font-medium text-[var(--series-1)] hover:underline" href="/my-data">Upload dataset</Link>}
      />
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {error && <ErrorBanner message={error} />}
      <section>
        <SectionHeading title="Management Dashboard" subtitle="Calculated from the loaded dataset. Values are never invented." />
        {kpis === null ? (
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]"><Spinner /> Calculating KPIs…</div>
        ) : kpis.length === 0 ? (
          <EmptyState title="No KPI values available" description="The loaded data does not contain a reliable numeric or identifier field to summarize." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {kpis.slice(0, MAX_KPIS).map((kpi, index) => (
              <Card key={`${kpi.dataset_id}-${kpi.name}-${index}`} className="p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">{kpi.name}</p>
                <p className="mt-2 text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                  {isMonetary(kpi.name)
                    ? formatCurrency(kpi.preview_value ?? 0, currency, decimalPlaces)
                    : formatNumber(kpi.preview_value ?? 0)}
                </p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{kpi.rationale}</p>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionHeading title="AI Business Findings" subtitle="Each finding is calculated from your data; recommendations are clearly marked as management guidance." />
        {insights === null ? (
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]"><Spinner /> Identifying findings…</div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {insights.slice(0, MAX_FINDINGS).map((insight) => (
              <Card key={insight.id} className="border-l-4 border-l-[var(--series-1)]">
                <div className="mb-3 flex items-center justify-between gap-3"><p className="text-sm font-semibold text-[var(--text-primary)]">Finding</p><SourceLabelBadge label={insight.confidence_label} /></div>
                <p className="text-sm font-medium text-[var(--text-primary)]">{insight.finding}</p>
                <dl className="mt-4 flex flex-col gap-3 text-xs text-[var(--text-secondary)]">
                  <div><dt className="font-semibold uppercase tracking-wide text-[var(--text-muted)]">Evidence</dt><dd className="mt-1">{insight.evidence.description}</dd></div>
                  <div><dt className="font-semibold uppercase tracking-wide text-[var(--text-muted)]">Business impact</dt><dd className="mt-1">{insight.interpretation}</dd></div>
                  <div><dt className="font-semibold uppercase tracking-wide text-[var(--text-muted)]">Recommended action</dt><dd className="mt-1">{recommendationFor(insight)} <span className="italic text-[var(--text-muted)]">(AI interpretation)</span></dd></div>
                </dl>
              </Card>
            ))}
          </div>
        )}
      </section>

      <Card className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div><p className="text-sm font-semibold text-[var(--text-primary)]">Ask DataWise for the evidence behind any decision</p><p className="mt-1 text-sm text-[var(--text-secondary)]">Questions use the existing deterministic analysis, verification, and chart system.</p></div>
        <Link href="/ask" className="shrink-0 rounded-lg bg-[var(--series-1)] px-3.5 py-2 text-center text-sm font-medium text-white hover:opacity-90">Ask a business question</Link>
      </Card>
    </div>
  );
}
