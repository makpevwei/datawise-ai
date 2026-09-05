"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getDashboardChartsMulti, getInsights, getKpiSuggestions } from "@/lib/api";
import { useSelectedDatasets } from "@/lib/useSelectedDatasets";
import type { ChartSpec, DatasetSummary, Insight, KPISuggestion } from "@/lib/types";
import { Card, EmptyState, ErrorBanner, formatSourceLabel, SectionHeading, SourceChip, SourceLabelBadge, Spinner } from "./ui";
import { DatasetPicker } from "./DatasetPicker";
import { ChartFromSpec, StatCard } from "./charts";

const MAX_KPIS = 6;
const MAX_FINDINGS = 5;

// Findings arrive one dataset at a time and are simply concatenated -- without
// this, whichever dataset's insights happen to resolve/appear first wins the
// top slots regardless of business importance (e.g. a sheet with no numeric
// metric surfacing a bare "50% of records share the same category value"
// frequency stat ahead of a genuine revenue-anomaly finding from a different
// sheet). Rank by category before slicing to MAX_FINDINGS instead: material
// business signals (trend changes, quantified anomalies, top performers)
// outrank concentration/frequency call-outs and data-quality housekeeping.
// A stable sort preserves each category's own dataset-arrival order.
const CATEGORY_PRIORITY: Record<Insight["category"], number> = {
  significant_change: 0,
  anomaly: 1,
  top_performer: 2,
  concentration_risk: 3,
  data_quality: 4,
  distribution: 4,
};

export function rankFindings(insights: Insight[]): Insight[] {
  return [...insights].sort((a, b) => CATEGORY_PRIORITY[a.category] - CATEGORY_PRIORITY[b.category]);
}

/** Return a clean source label: prefer sheet name, fall back to dataset name. */
function sourceLabel(kpi: KPISuggestion): string {
  return formatSourceLabel(kpi.dataset_name, kpi.dataset_sheet);
}

function chartSourceLabel(chart: ChartSpec): string {
  return formatSourceLabel(chart.dataset_name, chart.dataset_sheet);
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

/** KPI card with scaled value, source lineage, and full value on hover. */
function KpiCard({ kpi, currency, decimalPlaces }: { kpi: KPISuggestion; currency: string; decimalPlaces: number }) {
  return (
    <StatCard
      label={kpi.name}
      value={kpi.preview_value ?? 0}
      description={sourceLabel(kpi) || undefined}
      currency={currency}
      decimalPlaces={decimalPlaces}
      compact
    />
  );
}

export function ManagementDashboard({ datasets, currency, decimalPlaces }: {
  datasets: DatasetSummary[];
  currency: string;
  decimalPlaces: number;
}) {
  const [selectedDatasetIds, setSelectedDatasetIds] = useSelectedDatasets();
  const effectiveIds = selectedDatasetIds ?? datasets.map((d) => d.id);
  const activeDatasets = datasets.filter((d) => effectiveIds.includes(d.id));

  const [kpis, setKpis] = useState<KPISuggestion[] | null>(null);
  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [charts, setCharts] = useState<ChartSpec[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeDatasets.length === 0) {
      let cancelled = false;
      Promise.resolve().then(() => {
        if (!cancelled) { setKpis([]); setInsights([]); setCharts([]); setError(null); }
      });
      return () => { cancelled = true; };
    }
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) { setKpis(null); setInsights(null); setCharts(null); setError(null); }
    });

    Promise.all(activeDatasets.map((d) => getKpiSuggestions(d.id)))
      .then((results) => {
        if (cancelled) return;
        // Filter out Record Count when real metrics exist
        const all = results.flat().filter((k) => k.preview_value !== null);
        const hasRealMetric = all.some((k) => k.metric_column !== null && k.aggregation !== "count");
        setKpis(hasRealMetric ? all.filter((k) => k.name !== "Record Count") : all);
      })
      .catch(() => !cancelled && setError("DataWise could not calculate dashboard KPIs."));

    Promise.all(activeDatasets.map((d) => getInsights(d.id)))
      .then((results) => !cancelled && setInsights(results.flat()))
      .catch(() => !cancelled && setError("DataWise could not generate business findings."));

    getDashboardChartsMulti(activeDatasets.map((d) => d.id))
      .then((c) => !cancelled && setCharts(c))
      .catch(() => !cancelled && setCharts([]));

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveIds.join(",")]);

  if (datasets.length === 0) {
    return (
      <EmptyState
        title="Upload your business data to begin"
        description="DataWise will analyze your data, calculate KPIs, identify important findings, and generate evidence-backed recommendations."
        action={<Link className="text-sm font-medium text-[var(--brand)] hover:underline" href="/my-data">Upload dataset</Link>}
      />
    );
  }

  const confirmedFindings = rankFindings((insights ?? []).filter((i) => i.confidence_label !== "INSUFFICIENT_DATA"));

  return (
    <div className="flex flex-col gap-8">
      {error && <ErrorBanner message={error} />}

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <SectionHeading
          title="Management Dashboard"
          subtitle="Calculated from the selected datasets. Values are never invented."
        />
        <div className="shrink-0">
          <DatasetPicker datasets={datasets} selectedIds={selectedDatasetIds} onChange={setSelectedDatasetIds} />
        </div>
      </div>

      {activeDatasets.length === 0 ? (
        <EmptyState title="No datasets selected." description="Select at least one dataset to generate KPIs and findings." />
      ) : (
        <>
          {/* KPI Summary */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              Executive KPI Summary
            </h3>
            {kpis === null ? (
              <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
                <Spinner /> Calculating KPIs…
              </div>
            ) : kpis.length === 0 ? (
              <p className="text-sm text-[var(--text-secondary)]">
                No KPI values available — the selected data does not contain a reliable numeric field.
              </p>
            ) : (
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
                {kpis.slice(0, MAX_KPIS).map((kpi, i) => (
                  <KpiCard key={`${kpi.dataset_id}-${kpi.name}-${i}`} kpi={kpi} currency={currency} decimalPlaces={decimalPlaces} />
                ))}
              </div>
            )}
          </section>

          {/* Business Performance Charts */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              Business Performance
            </h3>
            {charts === null ? (
              <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
                <Spinner /> Building charts…
              </div>
            ) : charts.length === 0 ? (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
                <p className="text-sm font-medium text-[var(--text-primary)]">No default charts available.</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  The selected data does not have both a numeric metric and a date or category column.{" "}
                  <Link href="/ask" className="text-[var(--brand)] hover:underline">
                    Ask DataWise
                  </Link>{" "}
                  to create a custom analysis.
                </p>
              </div>
            ) : (
              <div className={`grid gap-6 ${charts.length === 1 ? "grid-cols-1" : "md:grid-cols-2"}`}>
                {charts.map((chart, i) => (
                  <Card key={i} className="p-4">
                    {/* Chart title -- line-clamp-2, not truncate: a long
                        title/source dataset name (e.g.
                        "NexaSphere_BI_Case_Study_Dataset.xlsx") was
                        getting cut off illegibly, worst on narrow
                        (mobile) cards. */}
                    {(chart.title || chart.reason) && (
                      <p className="mb-1 line-clamp-2 text-sm font-semibold text-[var(--text-primary)]" title={chart.title || chart.reason}>
                        {chart.title || chart.reason}
                      </p>
                    )}
                    {/* Source lineage */}
                    {chartSourceLabel(chart) && (
                      <div className="mb-3">
                        <SourceChip label={chartSourceLabel(chart)} />
                      </div>
                    )}
                    <div className="overflow-x-auto">
                      <ChartFromSpec spec={chart} currency={currency} decimalPlaces={decimalPlaces} />
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {/* AI Business Findings */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              Key Business Findings
            </h3>
            {insights === null ? (
              <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
                <Spinner /> Identifying findings…
              </div>
            ) : confirmedFindings.length === 0 ? (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
                <p className="text-sm font-medium text-[var(--text-primary)]">No confirmed business findings yet.</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  Upload or select a dataset with valid business metrics — revenue, cost, quantity, dates.
                </p>
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                {confirmedFindings.slice(0, MAX_FINDINGS).map((insight) => (
                  <Card key={insight.id} className="border-l-4 border-l-[var(--brand)]">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-[var(--text-primary)]">Finding</p>
                      <SourceLabelBadge label={insight.confidence_label} />
                    </div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">{insight.finding}</p>
                    <dl className="mt-3 flex flex-col gap-2 text-xs text-[var(--text-secondary)]">
                      <div>
                        <dt className="font-semibold uppercase tracking-wide text-[var(--text-muted)]">Evidence</dt>
                        <dd className="mt-0.5">{insight.evidence.description}</dd>
                      </div>
                      <div>
                        <dt className="font-semibold uppercase tracking-wide text-[var(--text-muted)]">Business impact</dt>
                        <dd className="mt-0.5">{insight.interpretation}</dd>
                      </div>
                      <div>
                        <dt className="font-semibold uppercase tracking-wide text-[var(--text-muted)]">Recommended action</dt>
                        <dd className="mt-0.5">{recommendationFor(insight)} <span className="italic text-[var(--text-muted)]">(AI interpretation)</span></dd>
                      </div>
                    </dl>
                  </Card>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {/* CTA */}
      <Card className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">
            Ask DataWise for the evidence behind any decision
          </p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Questions use the existing deterministic analysis, verification, and chart system.
          </p>
        </div>
        <Link
          href="/ask"
          className="shrink-0 rounded-lg bg-[var(--brand)] px-3.5 py-2 text-center text-sm font-medium text-[var(--brand-foreground)] hover:bg-[var(--brand-hover)]"
        >
          Ask a business question
        </Link>
      </Card>
    </div>
  );
}
