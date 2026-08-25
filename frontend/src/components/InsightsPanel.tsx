"use client";

import { askAgent, getDatasetSample, getInsights, getKpiSuggestions, runAnalysis } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { buildStarterQuestions, CASE_STUDY_STARTER_QUESTIONS } from "@/lib/starterQuestions";
import type { AgentAnswer, AgentFinding, AnalysisResult, DatasetSummary, Insight, KPISuggestion } from "@/lib/types";
import { useEffect, useState } from "react";
import { ChartFromSpec } from "./charts";
import { DatasetPicker } from "./DatasetPicker";
import { Button, Card, EmptyState, ErrorBanner, SectionHeading, SourceLabelBadge, Spinner, Table } from "./ui";

const CATEGORY_LABELS: Record<Insight["category"], string> = {
  top_performer: "Top Performer",
  concentration_risk: "Concentration Risk",
  significant_change: "Significant Change",
  anomaly: "Anomaly",
  data_quality: "Data Quality",
  distribution: "Distribution",
};

const CATEGORY_COLORS: Record<Insight["category"], string> = {
  top_performer: "border-l-[var(--series-3)]",
  concentration_risk: "border-l-[var(--status-serious)]",
  significant_change: "border-l-[var(--series-4)]",
  anomaly: "border-l-[var(--status-critical)]",
  data_quality: "border-l-[var(--text-muted)]",
  distribution: "border-l-[var(--series-1)]",
};

const MAX_INSIGHTS = 5;
const MAX_CHARTS = 5;
const MAX_RECOMMENDATIONS = 5;

export function InsightsPanel({ datasets }: { datasets: DatasetSummary[] }) {
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[] | null>(null);
  const effectiveIds = selectedDatasetIds ?? datasets.map((d) => d.id);
  const effectiveDatasets = datasets.filter((d) => effectiveIds.includes(d.id));
  const primaryDataset = effectiveDatasets[0] ?? null;

  if (datasets.length === 0) {
    return (
      <EmptyState
        title="No datasets available yet."
        description="Upload a dataset to get automatic insights, suggested charts, and AI-assisted Q&A."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading
        title="Visual Insights"
        subtitle="Automatic findings, suggested charts, and natural-language Q&A — every number here is calculated by the backend, never invented."
      />

      <div className="flex flex-wrap items-center gap-3">
        <DatasetPicker datasets={datasets} selectedIds={selectedDatasetIds} onChange={setSelectedDatasetIds} />
      </div>

      {effectiveDatasets.length === 0 ? (
        <EmptyState title="No datasets selected." description="Select at least one dataset to generate insights." />
      ) : (
        <InsightsWorkspace key={effectiveIds.join(",")} datasets={effectiveDatasets} primaryDataset={primaryDataset ?? effectiveDatasets[0]} />
      )}
    </div>
  );
}

function InsightsWorkspace({ datasets, primaryDataset }: { datasets: DatasetSummary[]; primaryDataset: DatasetSummary }) {
  const { user } = useAuth();
  const currency = user?.currency ?? "USD";
  const decimalPlaces = user?.decimal_places ?? 2;
  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [kpis, setKpis] = useState<KPISuggestion[] | null>(null);
  const [sample, setSample] = useState<Record<string, unknown>[] | null>(null);
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all(datasets.map((d) => getInsights(d.id)))
      .then((results) => !cancelled && setInsights(results.flat()))
      .catch((e) => !cancelled && setInsightsError(e instanceof Error ? e.message : "Failed to generate insights."));
    Promise.all(datasets.map((d) => getKpiSuggestions(d.id)))
      .then((results) => !cancelled && setKpis(results.flat()))
      .catch(() => !cancelled && setKpis([]));
    getDatasetSample(primaryDataset.id, 20)
      .then((s) => !cancelled && setSample(s))
      .catch(() => !cancelled && setSample([]));
    return () => {
      cancelled = true;
    };
  }, [datasets, primaryDataset.id]);

  return (
    <div className="flex flex-col gap-8">
      <AiDataAnalyst datasets={datasets} kpis={kpis ?? []} onAnswer={setAnswer} currency={currency} decimalPlaces={decimalPlaces} />

      <section>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">Key Insights</h3>
        {insightsError && <ErrorBanner message={insightsError} />}
        {!insightsError && insights === null && (
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
            <Spinner /> Generating insights…
          </div>
        )}
        {insights && insights.length === 0 && (
          <EmptyState title="No significant insights detected in this dataset." description="Try a dataset with more rows or variation across columns." />
        )}
        {insights && insights.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {insights.slice(0, MAX_INSIGHTS).map((insight) => (
              <Card key={insight.id} className={`border-l-4 ${CATEGORY_COLORS[insight.category]}`}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    {CATEGORY_LABELS[insight.category]}
                  </span>
                  <SourceLabelBadge label={insight.confidence_label} />
                </div>
                <p className="mb-3 text-sm font-medium text-[var(--text-primary)]">{insight.finding}</p>
                <dl className="flex flex-col gap-2 text-xs text-[var(--text-secondary)]">
                  <div>
                    <dt className="font-semibold text-[var(--text-muted)]">Evidence</dt>
                    <dd>{insight.evidence.description}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold text-[var(--text-muted)]">Calculation</dt>
                    <dd className="font-mono">{insight.calculation}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold text-[var(--text-muted)]">Interpretation</dt>
                    <dd>{insight.interpretation}</dd>
                  </div>
                </dl>
              </Card>
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Suggested Visualizations
        </h3>
        {kpis === null && (
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
            <Spinner /> Finding useful charts…
          </div>
        )}
        {kpis && kpis.length === 0 && (
          <EmptyState title="No chart suggestions available." description="This dataset doesn't have enough numeric or dimensional columns to suggest charts yet." />
        )}
        {kpis && kpis.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {kpis.slice(0, MAX_CHARTS).map((kpi, i) => (
              <ChartSuggestionCard key={`${kpi.name}-${i}`} kpi={kpi} currency={currency} decimalPlaces={decimalPlaces} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">Data Explorer</h3>
        {sample === null ? (
          <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-secondary)]">
            <Spinner /> Loading sample rows…
          </div>
        ) : sample.length === 0 ? (
          <EmptyState title="No data available." description="This dataset has no rows to preview." />
        ) : (
          <Card>
            <p className="mb-3 text-xs text-[var(--text-secondary)]">
              First {sample.length} rows of {primaryDataset.row_count.toLocaleString()} total.
            </p>
            <Table columns={Object.keys(sample[0])} rows={sample} currency={currency} decimalPlaces={decimalPlaces} />
          </Card>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Business Recommendations
        </h3>
        <RecommendationsSection answer={answer} />
      </section>
    </div>
  );
}

function ChartSuggestionCard({
  kpi,
  currency,
  decimalPlaces,
}: {
  kpi: KPISuggestion;
  currency: string;
  decimalPlaces: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleView() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (result) return;
    setLoading(true);
    setError(null);
    try {
      const r = await runAnalysis({
        dataset_id: kpi.dataset_id,
        metric_column: kpi.metric_column,
        aggregation: kpi.aggregation,
        dimension_column: kpi.dimension_column,
        date_column: kpi.date_column,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not calculate this chart.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <p className="text-sm font-medium text-[var(--text-primary)]">{kpi.name}</p>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">{kpi.rationale}</p>
      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
        <div>
          <dt className="inline font-semibold">Metric:</dt> <dd className="inline">{kpi.metric_column ?? "count"}</dd>
        </div>
        {kpi.dimension_column && (
          <div>
            <dt className="inline font-semibold">Dimension:</dt> <dd className="inline">{kpi.dimension_column}</dd>
          </div>
        )}
        {kpi.date_column && (
          <div>
            <dt className="inline font-semibold">Date field:</dt> <dd className="inline">{kpi.date_column}</dd>
          </div>
        )}
      </dl>
      <div className="mt-3">
        <Button variant="secondary" onClick={handleView} disabled={loading}>
          {loading ? <Spinner /> : null} {expanded ? "Hide" : "View"}
        </Button>
      </div>
      {expanded && (
        <div className="mt-4">
          {error && <ErrorBanner message={error} />}
          {result?.chart_recommendation && (
            <ChartFromSpec spec={result.chart_recommendation} currency={currency} decimalPlaces={decimalPlaces} />
          )}
          {result && !result.chart_recommendation && (
            <p className="text-sm text-[var(--text-secondary)]">{result.calculation_description}</p>
          )}
        </div>
      )}
    </Card>
  );
}

function AiDataAnalyst({
  datasets,
  kpis,
  onAnswer,
  currency,
  decimalPlaces,
}: {
  datasets: DatasetSummary[];
  kpis: KPISuggestion[];
  onAnswer: (a: AgentAnswer) => void;
  currency: string;
  decimalPlaces: number;
}) {
  const starterQuestions = [...CASE_STUDY_STARTER_QUESTIONS, ...buildStarterQuestions(kpis)].slice(0, 12);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAnswer, setLastAnswer] = useState<AgentAnswer | null>(null);

  async function handleAsk(q?: string) {
    const finalQuestion = (q ?? question).trim();
    if (!finalQuestion || loading) return;
    setLoading(true);
    setError(null);
    try {
      const answer = await askAgent({
        question: datasets.length > 1 ? `For the selected datasets: ${finalQuestion}` : `For the dataset "${datasets[0]?.name ?? "the data"}": ${finalQuestion}`,
        session_id: null,
        dataset_ids: datasets.length > 0 ? datasets.map((d) => d.id) : undefined,
      });
      setLastAnswer(answer);
      onAnswer(answer);
      setQuestion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">AI Data Analyst</h3>
      <p className="mb-3 text-sm text-[var(--text-secondary)]">Ask a question about this dataset</p>
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder="Ask anything about this dataset..."
          className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--series-1)]"
        />
        {question && (
          <Button variant="secondary" onClick={() => setQuestion("")} disabled={loading}>
            Clear
          </Button>
        )}
        <Button onClick={() => handleAsk()} disabled={loading || !question.trim()}>
          {loading ? <Spinner /> : null} Ask DataWise →
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {starterQuestions.map((q) => (
          <button
            key={q}
            onClick={() => setQuestion(q)}
            disabled={loading}
            className="rounded-full border border-[var(--border)] px-3 py-1 text-xs text-[var(--text-secondary)] hover:bg-[var(--background)] disabled:opacity-40"
          >
            {q}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {lastAnswer && (
        <div className="mt-5 border-t border-[var(--border)] pt-4">
          {lastAnswer.executive_summary && (
            <p className="text-sm text-[var(--text-primary)]">{lastAnswer.executive_summary}</p>
          )}
          {lastAnswer.key_findings.length > 0 && (
            <ul className="mt-3 flex flex-col gap-2">
              {lastAnswer.key_findings.map((f, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <SourceLabelBadge label={f.label} />
                  <span className="text-[var(--text-secondary)]">{f.text}</span>
                </li>
              ))}
            </ul>
          )}
          {lastAnswer.charts.length > 0 && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {lastAnswer.charts.slice(0, 2).map((c, i) => (
                <ChartFromSpec key={i} spec={c} currency={currency} decimalPlaces={decimalPlaces} />
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function RecommendationsSection({ answer }: { answer: AgentAnswer | null }) {
  const recommendations: AgentFinding[] = (answer?.recommendations ?? []).slice(0, MAX_RECOMMENDATIONS);

  if (recommendations.length === 0) {
    return (
      <EmptyState
        title="No recommendations yet."
        description="Ask the AI Data Analyst a question above — recommendations grounded in the findings will appear here."
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {recommendations.map((r, i) => (
        <Card key={i} className="flex items-start gap-3">
          <SourceLabelBadge label={r.label} />
          <p className="text-sm text-[var(--text-secondary)]">{r.text}</p>
        </Card>
      ))}
    </div>
  );
}
