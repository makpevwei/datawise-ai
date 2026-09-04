"use client";

import { useEffect, useState } from "react";
import { getDataset, getKpiSuggestions, runAnalysis } from "@/lib/api";
import { compatibleChartTypes } from "@/lib/chartCompatibility";
import { useAuth } from "@/lib/auth-context";
import type {
  Aggregation,
  AnalysisResult,
  ChartType,
  DatasetProfile,
  DatasetSummary,
  FilterCondition,
  KPISuggestion,
} from "@/lib/types";
import { BarChart, ChartFromSpec, DonutChart, LineChart, StatCard } from "./charts";
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  SectionHeading,
  SourceLabelBadge,
  Spinner,
  Table,
} from "./ui";

const AGGREGATIONS: Aggregation[] = ["sum", "mean", "median", "min", "max", "count", "nunique"];

type FilterRow = { column: string; operator: FilterCondition["operator"]; value: string };

export function AnalysisWorkspace({ datasets }: { datasets: DatasetSummary[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const effectiveId = selectedId ?? datasets[0]?.id ?? null;

  if (datasets.length === 0 || !effectiveId) {
    return (
      <EmptyState
        title="No datasets yet"
        description="Upload a dataset first, then come back here to build KPIs and charts."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading
        title="Analysis workspace"
        subtitle="Choose a dataset, metric, dimension, aggregation, date field, and filters. Every number is computed by the backend from the actual data."
      />

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-[var(--text-secondary)]">Dataset</label>
        <select
          value={effectiveId}
          onChange={(e) => setSelectedId(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
        >
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>

      <DatasetAnalysisPanel key={effectiveId} datasetId={effectiveId} />
    </div>
  );
}

function DatasetAnalysisPanel({ datasetId }: { datasetId: string }) {
  // Keyed by datasetId in the parent, so switching datasets remounts this
  // panel and all its state resets naturally -- no reset-then-fetch effect.
  const { user } = useAuth();
  const currency = user?.currency ?? "USD";
  const decimalPlaces = user?.decimal_places ?? 2;
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [kpis, setKpis] = useState<KPISuggestion[] | null>(null);

  const [metric, setMetric] = useState<string>("");
  const [aggregation, setAggregation] = useState<Aggregation>("sum");
  const [dimension, setDimension] = useState<string>("");
  const [secondDimension, setSecondDimension] = useState<string>("");
  const [dateColumn, setDateColumn] = useState<string>("");
  const [chartTypeChoice, setChartTypeChoice] = useState<string>("");
  const [topN, setTopN] = useState<string>("");
  const [sort, setSort] = useState<"desc" | "asc">("desc");
  const [filters, setFilters] = useState<FilterRow[]>([]);
  const [drillPath, setDrillPath] = useState<{ column: string; label: string }[]>([]);
  const [baseDimension, setBaseDimension] = useState<string>("");

  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getDataset(datasetId), getKpiSuggestions(datasetId)]).then(([p, k]) => {
      if (cancelled) return;
      setProfile(p);
      setKpis(k);
      if (p.numeric_columns[0]) setMetric(p.numeric_columns[0]);
    });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  async function handleRun(
    overrides?: Partial<KPISuggestion> & { dimension_column?: string | null; second_dimension_column?: string | null },
    filterOverride?: FilterRow[],
  ) {
    setLoading(true);
    setError(null);
    try {
      const res = await runAnalysis({
        dataset_id: datasetId,
        metric_column: overrides?.metric_column ?? (metric || null),
        aggregation: overrides?.aggregation ?? aggregation,
        dimension_column: "dimension_column" in (overrides ?? {}) ? overrides!.dimension_column : dimension || null,
        second_dimension_column:
          "second_dimension_column" in (overrides ?? {}) ? overrides!.second_dimension_column : secondDimension || null,
        date_column: overrides?.date_column ?? (dateColumn || null),
        top_n: topN ? Number(topN) : null,
        sort,
        chart_type: (chartTypeChoice || null) as ChartType | null,
        filters: (filterOverride ?? filters)
          .filter((f) => f.column && f.value !== "")
          .map((f) => ({ column: f.column, operator: f.operator, value: f.value })),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function runKpi(kpi: KPISuggestion) {
    setMetric(kpi.metric_column ?? "");
    setAggregation(kpi.aggregation);
    setDimension(kpi.dimension_column ?? "");
    setSecondDimension("");
    setDateColumn(kpi.date_column ?? "");
    setChartTypeChoice("");
    setDrillPath([]);
    setBaseDimension(kpi.dimension_column ?? "");
    handleRun(kpi);
  }

  function nextDrillDimension(profile: DatasetProfile, used: Set<string>): string | null {
    const candidates = [...profile.categorical_columns, ...profile.identifier_columns, ...profile.text_columns];
    return candidates.find((c) => !used.has(c)) ?? null;
  }

  function handleDrillDown(dimensionColumn: string, label: string, currentProfile: DatasetProfile) {
    if (drillPath.length === 0) setBaseDimension(dimensionColumn);
    const nextFilters = [...filters, { column: dimensionColumn, operator: "eq" as const, value: label }];
    const newPath = [...drillPath, { column: dimensionColumn, label }];
    const used = new Set([dimensionColumn, ...drillPath.map((p) => p.column)]);
    const next = nextDrillDimension(currentProfile, used);

    setFilters(nextFilters);
    setDrillPath(newPath);
    setDimension(next ?? "");
    handleRun({ dimension_column: next ?? null }, nextFilters);
  }

  function handleBreadcrumbClick(index: number) {
    // index -1 means "All" (reset entirely); otherwise jump back to that level.
    const newPath = index < 0 ? [] : drillPath.slice(0, index + 1);
    const newFilters = filters.filter(
      (f) => !drillPath.some((p, i) => i > (index < 0 ? -1 : index) && p.column === f.column && p.label === f.value),
    );
    const usedColumns = new Set(newPath.map((p) => p.column));
    const targetDimension =
      index < 0 ? baseDimension : (profile ? nextDrillDimension(profile, usedColumns) : null) ?? baseDimension;
    setDrillPath(newPath);
    setFilters(newFilters);
    setDimension(targetDimension);
    handleRun({ dimension_column: targetDimension || null }, newFilters);
  }

  function resetDrillDown() {
    const clearedFilters = filters.filter((f) => !drillPath.some((p) => p.column === f.column && p.label === f.value));
    setDrillPath([]);
    setFilters(clearedFilters);
    setDimension(baseDimension);
    handleRun({ dimension_column: baseDimension || null }, clearedFilters);
  }

  return (
    <div className="flex flex-col gap-6">
      {kpis && kpis.length > 0 && (
        <Card>
          <SectionHeading
            title="Suggested KPIs"
            subtitle="Computed from this dataset's actual columns — accept one to run it."
          />
          <div className="flex flex-wrap gap-2">
            {kpis.map((kpi) => (
              <button
                key={kpi.name}
                onClick={() => runKpi(kpi)}
                title={kpi.rationale}
                className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:border-[var(--brand)] hover:text-[var(--brand)]"
              >
                {kpi.name}
                {kpi.preview_value !== null && (
                  <span className="ml-1.5 text-[var(--text-muted)]">
                    ({kpi.preview_value.toLocaleString(undefined, { maximumFractionDigits: 1 })})
                  </span>
                )}
              </button>
            ))}
          </div>
        </Card>
      )}

      {profile && (
        <Card>
          <SectionHeading title="Build your own analysis" />
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Field label="Metric">
              <Select
                value={metric}
                onChange={setMetric}
                options={["", ...profile.numeric_columns, ...profile.identifier_columns]}
              />
            </Field>
            <Field label="Aggregation">
              <Select value={aggregation} onChange={(v) => setAggregation(v as Aggregation)} options={AGGREGATIONS} />
            </Field>
            <Field label="Dimension">
              <Select
                value={dimension}
                onChange={setDimension}
                options={[
                  "",
                  ...profile.categorical_columns,
                  ...profile.identifier_columns,
                  ...profile.text_columns,
                ]}
              />
            </Field>
            <Field label="Second Dimension">
              <Select
                value={secondDimension}
                onChange={setSecondDimension}
                options={[
                  "",
                  ...[...profile.categorical_columns, ...profile.identifier_columns, ...profile.text_columns].filter(
                    (c) => c !== dimension,
                  ),
                ]}
              />
            </Field>
            <Field label="Date field">
              <Select value={dateColumn} onChange={setDateColumn} options={["", ...profile.date_columns]} />
            </Field>
            <Field label="Top N">
              <input
                type="number"
                min={1}
                value={topN}
                onChange={(e) => setTopN(e.target.value)}
                placeholder="all"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
              />
            </Field>
            <Field label="Sort">
              <Select value={sort} onChange={(v) => setSort(v as "desc" | "asc")} options={["desc", "asc"]} />
            </Field>
            <Field label="Chart type">
              <Select
                value={chartTypeChoice}
                onChange={setChartTypeChoice}
                options={[
                  "",
                  ...compatibleChartTypes(profile, {
                    metricColumn: metric,
                    dimensionColumn: dimension,
                    secondDimensionColumn: secondDimension,
                    dateColumn: dateColumn,
                  }),
                ]}
              />
            </Field>
          </div>

          <FilterBuilder profile={profile} filters={filters} setFilters={setFilters} />

          {drillPath.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5 text-xs">
              <button onClick={() => handleBreadcrumbClick(-1)} className="text-[var(--brand)] hover:underline">
                All
              </button>
              {drillPath.map((p, i) => (
                <span key={i} className="flex items-center gap-1.5">
                  <span className="text-[var(--text-muted)]">›</span>
                  <button
                    onClick={() => handleBreadcrumbClick(i)}
                    className={i === drillPath.length - 1 ? "font-medium text-[var(--text-primary)]" : "text-[var(--brand)] hover:underline"}
                  >
                    {p.label}
                  </button>
                </span>
              ))}
              <button onClick={resetDrillDown} className="ml-3 text-[var(--status-critical)] hover:underline">
                Reset Drill-down
              </button>
            </div>
          )}

          <div className="mt-4 flex items-center gap-3">
            <Button onClick={() => handleRun()} disabled={loading}>
              {loading ? <Spinner /> : null} Run analysis
            </Button>
            {filters.length > 0 && (
              <Button
                variant="ghost"
                onClick={() => {
                  setFilters([]);
                  handleRun(undefined, []);
                }}
                disabled={loading}
              >
                Clear filters
              </Button>
            )}
          </div>
        </Card>
      )}

      {error && <ErrorBanner message={error} />}

      {result && profile && (
        <ResultView
          result={result}
          onDrillDown={(col, label) => handleDrillDown(col, label, profile)}
          currency={currency}
          decimalPlaces={decimalPlaces}
        />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-[var(--text-secondary)]">{label}</label>
      {children}
    </div>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
    >
      {options.map((opt) => (
        <option key={opt || "none"} value={opt}>
          {opt || "(none)"}
        </option>
      ))}
    </select>
  );
}

function FilterBuilder({
  profile,
  filters,
  setFilters,
}: {
  profile: DatasetProfile;
  filters: FilterRow[];
  setFilters: (f: FilterRow[]) => void;
}) {
  const allColumns = profile.columns.map((c) => c.name);

  function update(i: number, patch: Partial<FilterRow>) {
    setFilters(filters.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }

  return (
    <div className="mt-4 flex flex-col gap-2">
      <label className="text-xs font-medium text-[var(--text-secondary)]">Filters</label>
      {filters.map((f, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <Select value={f.column} onChange={(v) => update(i, { column: v })} options={["", ...allColumns]} />
          <Select
            value={f.operator}
            onChange={(v) => update(i, { operator: v as FilterRow["operator"] })}
            options={["eq", "ne", "gt", "gte", "lt", "lte", "contains"]}
          />
          <input
            value={f.value}
            onChange={(e) => update(i, { value: e.target.value })}
            placeholder="value"
            className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)]"
          />
          <button
            onClick={() => setFilters(filters.filter((_, idx) => idx !== i))}
            className="text-xs text-[var(--status-critical)] hover:underline"
          >
            remove
          </button>
        </div>
      ))}
      {filters.length < 3 && (
        <button
          onClick={() => setFilters([...filters, { column: "", operator: "eq", value: "" }])}
          className="w-fit text-xs text-[var(--brand)] hover:underline"
        >
          + add filter
        </button>
      )}
    </div>
  );
}

function ResultView({
  result,
  onDrillDown,
  currency,
  decimalPlaces,
}: {
  result: AnalysisResult;
  onDrillDown: (dimensionColumn: string, label: string) => void;
  currency: string;
  decimalPlaces: number;
}) {
  const chart = result.chart_recommendation;
  const dimensionColumn = result.request.dimension_column;

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <SectionHeading title="Result" subtitle={result.calculation_description} />
        <SourceLabelBadge label={result.source} />
      </div>

      {result.result_type === "insufficient_data" && (
        <EmptyState title="Insufficient data to determine this." description={result.calculation_description} />
      )}

      {result.result_type === "scalar" && result.scalar_value !== null && (
        <StatCard
          label={result.request.metric_column ?? "records"}
          value={result.scalar_value}
          currency={currency}
          decimalPlaces={decimalPlaces}
        />
      )}

      {result.result_type === "table" && result.table && (
        <div className="flex flex-col gap-6">
          {dimensionColumn && !result.request.second_dimension_column && (
            <p className="text-xs text-[var(--text-muted)]">
              Click the chart to drill down into that {dimensionColumn}.
            </p>
          )}
          {chart && (chart.chart_type === "grouped_bar" || chart.chart_type === "stacked_bar" || chart.chart_type === "scatter" || chart.chart_type === "map") ? (
            <ChartFromSpec spec={chart} currency={currency} decimalPlaces={decimalPlaces} />
          ) : chart?.chart_type === "donut" || chart?.chart_type === "pie" ? (
            <DonutChart
              data={result.table.map((row) => {
                const keys = Object.keys(row);
                const valueKey = keys.find(
                  (k) => k !== result.request.dimension_column && k !== "percentage_of_total",
                );
                return {
                  label: String(row[result.request.dimension_column ?? keys[0]]),
                  value: Number(row[valueKey ?? keys[1]] ?? 0),
                };
              })}
              onSliceClick={dimensionColumn && !result.request.second_dimension_column ? (label) => onDrillDown(dimensionColumn, label) : undefined}
            />
          ) : (
            <BarChart
              data={result.table.map((row) => {
                const keys = Object.keys(row);
                const valueKey = keys.find(
                  (k) => k !== result.request.dimension_column && k !== "percentage_of_total",
                );
                return {
                  label: String(row[result.request.dimension_column ?? keys[0]]),
                  value: Number(row[valueKey ?? keys[1]] ?? 0),
                };
              })}
              onBarClick={dimensionColumn && !result.request.second_dimension_column ? (label) => onDrillDown(dimensionColumn, label) : undefined}
              valueLabel={result.request.metric_column ?? undefined}
              currency={currency}
              decimalPlaces={decimalPlaces}
            />
          )}
          <Table columns={Object.keys(result.table[0])} rows={result.table} currency={currency} decimalPlaces={decimalPlaces} />
        </div>
      )}

      {result.result_type === "timeseries" && result.table && (
        <div className="flex flex-col gap-6">
          <LineChart
            data={result.table.map((row) => ({ label: String(row.period), value: Number(row.value) }))}
            valueLabel={result.request.metric_column ?? undefined}
            currency={currency}
            decimalPlaces={decimalPlaces}
          />
          <Table columns={Object.keys(result.table[0])} rows={result.table} currency={currency} decimalPlaces={decimalPlaces} />
        </div>
      )}

      {chart && chart.chart_type !== "insufficient_data" && (
        <p className="mt-4 text-xs text-[var(--text-muted)]">Chart choice: {chart.reason}</p>
      )}
    </Card>
  );
}
