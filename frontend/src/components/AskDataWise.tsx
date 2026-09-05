"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { askAgent, createReport, exportAnalysisPdf, getAgentStatus, getKpiSuggestions, getReportPdf, getSession } from "@/lib/api";
import type { AgentAnswer, AgentFinding, ClaimComparison, DatasetSummary, EvidenceLabel, KPISuggestion, TraceStep } from "@/lib/types";
import { buildStarterQuestions, BUSINESS_STARTER_QUESTIONS, GENERIC_STARTER_QUESTIONS } from "@/lib/starterQuestions";
import { useAuth } from "@/lib/auth-context";
import { useSelectedDatasets } from "@/lib/useSelectedDatasets";
import { ChartFromSpec } from "./charts";
import { DatasetPicker } from "./DatasetPicker";
import {
  Button,
  Card,
  CitationCard,
  CrossCheckBadge,
  ErrorBanner,
  formatSourceLabel,
  GROUNDED_EVIDENCE_LABELS,
  GroundedBadge,
  SectionHeading,
  SourceChip,
  SourceLabelBadge,
  Spinner,
} from "./ui";
import {
  IconChartBar,
  IconCheckCircle,
  IconDatabase,
  IconFileText,
  IconGear,
  IconGlobe,
  IconLink,
  IconShieldCheck,
  IconSparkles,
} from "./icons";
import type { ComponentType } from "react";

const UNSET = Symbol("unset");

const STAGE_LABELS: Record<TraceStep["stage"], string> = {
  understanding_question: "Understanding the question",
  routing: "Routing",
  datasets: "Checking datasets",
  documents: "Checking documents",
  relationships: "Checking relationships",
  analysis: "Running analysis",
  document_research: "Researching documents",
  web_research: "Researching the web",
  verification: "Verifying evidence",
  answer: "Composing the answer",
};

const STAGE_ICONS: Record<TraceStep["stage"], ComponentType<{ size?: number; className?: string }>> = {
  understanding_question: IconSparkles,
  routing: IconGear,
  datasets: IconDatabase,
  documents: IconFileText,
  relationships: IconLink,
  analysis: IconChartBar,
  document_research: IconFileText,
  web_research: IconGlobe,
  verification: IconShieldCheck,
  answer: IconCheckCircle,
};

export function AskDataWise({
  datasets,
  initialSessionId,
}: {
  datasets: DatasetSummary[];
  initialSessionId?: string;
}) {
  const { user } = useAuth();
  const currency = user?.currency ?? "USD";
  const decimalPlaces = user?.decimal_places ?? 2;
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId ?? null);
  const [exchanges, setExchanges] = useState<AgentAnswer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  // Tracks the session id this component itself last pushed to the URL, so
  // the restore effect below can tell "the URL changed because I just
  // synced it after getting an answer" (skip -- nothing to restore, state
  // is already correct) apart from "the URL changed because the user
  // navigated to a different session or a fresh /ask" (do restore/reset).
  // Starts at a sentinel that can never equal a real session id or
  // undefined, so the very first mount always runs the restore-from-URL
  // check when the URL already names a session (e.g. a "Continue" link).
  const syncedSessionRef = useRef<string | null | typeof UNSET>(UNSET);
  const [starterKpis, setStarterKpis] = useState<KPISuggestion[]>([]);
  // null = all of the user's datasets (unscoped, the default) -- matches
  // AskRequest.dataset_ids' own "omit for everything" semantics, so this
  // picker only changes behavior once the user actually narrows it.
  // Shared/persisted (not a plain useState) so the selection survives
  // navigating to Dashboard/Insights and back, instead of resetting to
  // "all selected" on every remount.
  const [selectedDatasetIds, setSelectedDatasetIds] = useSelectedDatasets();

  useEffect(() => {
    getAgentStatus()
      .then((s) => setConfigured(s.configured))
      .catch(() => setConfigured(false));
  }, []);

  useEffect(() => {
    // Most-recently-uploaded dataset grounds the starter questions -- these
    // are just suggestions, not a dataset selection, so picking one
    // reasonable dataset (rather than merging every dataset's KPIs) keeps
    // the list focused and fast.
    const primary = datasets[datasets.length - 1];
    let cancelled = false;
    if (!primary) {
      // Async even in the "nothing to fetch" case -- setState synchronously
      // inside an effect body risks cascading renders (react-hooks/set-state-in-effect).
      Promise.resolve().then(() => !cancelled && setStarterKpis([]));
      return () => {
        cancelled = true;
      };
    }
    getKpiSuggestions(primary.id)
      .then((k) => !cancelled && setStarterKpis(k))
      .catch(() => !cancelled && setStarterKpis([]));
    return () => {
      cancelled = true;
    };
  }, [datasets]);

  // Grounded/curated questions first, generic filler last -- see
  // InsightsPanel.tsx's identical fix for why.
  const starterQuestions = datasets.length > 0
    ? [...buildStarterQuestions(starterKpis), ...BUSINESS_STARTER_QUESTIONS].slice(0, 12)
    : GENERIC_STARTER_QUESTIONS;

  useEffect(() => {
    const urlSessionId = initialSessionId ?? null;
    if (urlSessionId === syncedSessionRef.current) return; // our own URL sync echoing back -- already up to date
    syncedSessionRef.current = urlSessionId;
    if (!urlSessionId) return; // plain /ask with no session param never clears an active conversation -- only New Chat does
    getSession(urlSessionId)
      .then((session) => {
        setSessionId(urlSessionId);
        const restored = session.messages
          .filter((m) => m.kind === "agent_answer" && m.role === "assistant")
          .map((m) => m.metadata as unknown as AgentAnswer)
          .reverse();
        setExchanges(restored);
        // Pre-fill the composer with the most recent user question so that
        // "Edit / Continue" opens with the previous question ready to edit.
        const lastUserMsg = session.messages.filter((m) => m.role === "user").at(-1);
        if (lastUserMsg?.content) {
          setQuestion(lastUserMsg.content);
        }
      })
      .catch(() => setError("Could not restore this session."));
  }, [initialSessionId]);

  async function handleAsk(q?: string) {
    const finalQuestion = (q ?? question).trim();
    if (!finalQuestion || loading) return;
    setLoading(true);
    setError(null);
    try {
      const answer = await askAgent({
        question: finalQuestion,
        session_id: sessionId,
        dataset_ids: selectedDatasetIds,
      });
      setSessionId(answer.session_id);
      setExchanges((prev) => [answer, ...prev]);
      setQuestion("");
      // Reflect the session in the URL *after* local state is already
      // correct, and mark it as self-originated first -- so a navigation
      // away and back (which remounts this component) has something to
      // restore from, without this same update wastefully re-fetching
      // the conversation we already have in memory.
      syncedSessionRef.current = answer.session_id;
      router.replace(`/ask?session=${answer.session_id}`, { scroll: false });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setLoading(false);
    }
  }

  function handleNewChat() {
    syncedSessionRef.current = null;
    setSessionId(null);
    setExchanges([]);
    setQuestion("");
    setError(null);
    router.replace("/ask");
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionHeading
          title="Ask DataWise"
          subtitle="DataWise investigates your uploaded data and documents, then explains the answer with verifiable evidence."
        />
        <div className="flex items-center gap-2">
          {datasets.length > 1 && (
            <DatasetPicker datasets={datasets} selectedIds={selectedDatasetIds} onChange={setSelectedDatasetIds} />
          )}
          {exchanges.length > 0 && (
            <Button variant="secondary" onClick={handleNewChat}>
              + New Chat
            </Button>
          )}
        </div>
      </div>

      <Card>
        <div className="flex flex-col gap-3">
          <textarea
            ref={textareaRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleAsk();
              }
            }}
            placeholder="Ask anything about your data..."
            rows={3}
            className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5">
              {starterQuestions.map((q) => (
                <button
                  key={q}
                  onClick={() => setQuestion(q)}
                  disabled={loading}
                  className="rounded-full border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--text-secondary)] hover:border-[var(--brand)] hover:text-[var(--brand)] disabled:opacity-40"
                >
                  {q}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              {question && (
                <Button variant="secondary" onClick={() => setQuestion("")} disabled={loading}>
                  Clear
                </Button>
              )}
              <Button onClick={() => handleAsk()} disabled={loading || !question.trim()}>
                {loading ? <Spinner /> : null} Analyze →
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {configured === false && (
        <ErrorBanner message="AI features are not configured: set LLM_PROVIDER and LLM_API_KEY on the backend to enable the AI analyst. Dataset upload, profiling, relationships, joins, KPIs, and insights all continue to work without an LLM." />
      )}
      {datasets.length === 0 && configured !== false && exchanges.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border)] px-6 py-10 text-center">
          <p className="text-sm font-medium text-[var(--text-primary)]">No data has been uploaded yet.</p>
          <p className="max-w-md text-sm text-[var(--text-secondary)]">
            Ask DataWise a general business question, or upload data or documents for evidence-backed analysis.
          </p>
          <div className="flex items-center gap-2">
            <Link href="/my-data">
              <Button variant="secondary">Upload Data</Button>
            </Link>
            <Button onClick={() => textareaRef.current?.focus()}>Ask a Question</Button>
          </div>
        </div>
      )}
      {error && <ErrorBanner message={error} />}

      <div className="flex flex-col gap-6">
        {exchanges.map((answer, i) => (
          <AnswerCard key={`${answer.session_id}-${i}`} answer={answer} currency={currency} decimalPlaces={decimalPlaces} />
        ))}
      </div>
    </div>
  );
}

function AnswerCard({
  answer,
  currency,
  decimalPlaces,
}: {
  answer: AgentAnswer;
  currency: string;
  decimalPlaces: number;
}) {
  const [showTrace, setShowTrace] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function handleExport() {
    setExporting(true);
    setExportError(null);
    try {
      let blob: Blob;
      if (answer.message_id) {
        // Persist it so it shows up under Reports and reopening it later
        // serves this same file instead of re-rendering.
        const report = await createReport({
          message_id: answer.message_id,
          title: answer.executive_summary?.slice(0, 80) || answer.question.slice(0, 80),
        });
        blob = await getReportPdf(report.id);
      } else {
        blob = await exportAnalysisPdf(answer);
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "datawise-analysis.pdf";
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <Card>
      <p className="mb-3 text-sm font-semibold text-[var(--text-primary)]">{answer.question}</p>

      {!answer.configured || answer.error ? (
        <ErrorBanner message={answer.error ?? "Something went wrong."} />
      ) : (
        <div className="flex flex-col gap-5">
          <AnswerProvenanceBar answer={answer} />

          {answer.executive_summary && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                Executive Summary
              </p>
              <p className="text-sm text-[var(--text-primary)]">{answer.executive_summary}</p>
              {answer.llm_metadata && (
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  Answered by {answer.llm_metadata.provider} · {answer.llm_metadata.model}
                  {answer.llm_metadata.fallback_used ? " (fallback used)" : ""}
                </p>
              )}
            </div>
          )}

          {/* Charts appear immediately after the executive summary so
              the visual is the first thing a judge/user sees, not buried
              after a wall of findings text. */}
          {answer.charts.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                Visual Analysis
              </p>
              <div className={`grid gap-4 ${answer.charts.length === 1 ? "grid-cols-1" : "sm:grid-cols-2"}`}>
                {answer.charts.map((chart, i) => (
                  <div key={i} className="rounded-xl border border-[var(--border)] bg-[var(--surface-1)] p-4">
                    {chart.reason && (
                      <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">{chart.reason}</p>
                    )}
                    <div className="overflow-x-auto">
                      <ChartFromSpec spec={chart} currency={currency} decimalPlaces={decimalPlaces} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <AgentReasoning trace={answer.trace} citationCount={answer.citations.length} showTrace={showTrace} setShowTrace={setShowTrace} />

          <FindingList title="Key Findings" findings={answer.key_findings} />
          <FindingList title="Risks" findings={answer.risks} />
          <RecommendationList findings={answer.recommendations} />

          {answer.claim_comparisons.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                Management Claims vs. Data
              </p>
              <div className="flex flex-col gap-2">
                {answer.claim_comparisons.map((c, i) => (
                  <ClaimComparisonRow key={i} comparison={c} />
                ))}
              </div>
            </div>
          )}

          {answer.citations.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                Sources
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {answer.citations.map((c) => (
                  <CitationCard
                    key={`${c.document_id}-${c.chunk_id}`}
                    documentName={c.document_name}
                    location={c.location}
                    excerpt={c.excerpt}
                  />
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={handleExport} disabled={exporting}>
              {exporting ? <Spinner /> : null} Export PDF
            </Button>
            {exportError && <span className="text-xs text-[var(--status-critical)]">{exportError}</span>}
          </div>
        </div>
      )}
    </Card>
  );
}

function FindingItem({ finding }: { finding: AgentFinding }) {
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-start gap-2">
        <SourceLabelBadge label={finding.label} />
        <span className="text-sm text-[var(--text-primary)]">{finding.text}</span>
      </div>
      {finding.verification_note && (
        <p className="ml-1 text-xs italic text-[var(--text-muted)]">{finding.verification_note}</p>
      )}
    </li>
  );
}

function FindingList({ title, findings }: { title: string; findings: AgentFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</p>
      <ul className="flex flex-col gap-2">
        {findings.map((f, i) => (
          <FindingItem key={i} finding={f} />
        ))}
      </ul>
    </div>
  );
}

// A recommendation grounded in this dataset (VERIFIED_FROM_DATA/CALCULATED/
// DERIVED/DOCUMENT_EVIDENCE) and one sourced from general/web knowledge
// (VERIFIED_FROM_WEB/AI_INTERPRETATION/GENERAL_ANSWER) look identical in a
// flat list -- only a small per-item badge tells them apart, easy to miss
// while skimming. Splitting into two visually distinct sections, the
// general-knowledge one explicitly disclaimed, makes that distinction hard
// to miss instead -- the underlying EvidenceLabel this reads is the same
// mechanically-verified label every other finding already carries, no new
// backend logic needed.
const GENERAL_KNOWLEDGE_LABELS: EvidenceLabel[] = [
  "VERIFIED_FROM_WEB",
  "AI_INTERPRETATION",
  "GENERAL_ANSWER",
  "INSUFFICIENT_DATA",
];

function RecommendationList({ findings }: { findings: AgentFinding[] }) {
  if (findings.length === 0) return null;
  const grounded = findings.filter((f) => !GENERAL_KNOWLEDGE_LABELS.includes(f.label));
  const general = findings.filter((f) => GENERAL_KNOWLEDGE_LABELS.includes(f.label));

  return (
    <div className="flex flex-col gap-4">
      {grounded.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
            Recommended Areas to Investigate
          </p>
          <ul className="flex flex-col gap-2">
            {grounded.map((f, i) => (
              <FindingItem key={i} finding={f} />
            ))}
          </ul>
        </div>
      )}
      {general.length > 0 && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">
              What Usually Works
            </p>
            <span className="text-[10px] text-[var(--text-muted)]">From outside sources, not from your data</span>
          </div>
          <p className="mb-2 text-[10px] italic text-[var(--text-muted)]">
            General practice for the pattern above, not specific to your business -- every figure elsewhere
            on this page still comes from your own data.
          </p>
          <ul className="flex flex-col gap-2">
            {general.map((f, i) => (
              <FindingItem key={i} finding={f} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ClaimComparisonRow({ comparison }: { comparison: ClaimComparison }) {
  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="mb-1 flex items-start justify-between gap-2">
        <p className="text-sm text-[var(--text-primary)]">&ldquo;{comparison.document_claim}&rdquo;</p>
        <CrossCheckBadge label={comparison.label} />
      </div>
      <p className="text-xs text-[var(--text-secondary)]">{comparison.explanation}</p>
    </div>
  );
}

/** Always-visible provenance strip -- rendered directly under the question,
 * above the executive summary, never behind a click. The direct fix for the
 * comparison-pass finding that DataWise's own (more rigorous, mechanically
 * verified) evidence system was invisible until a user opened the trace. */
function AnswerProvenanceBar({ answer }: { answer: AgentAnswer }) {
  const allFindings = [...answer.key_findings, ...answer.risks, ...answer.recommendations];
  const grounded = allFindings.some((f) => GROUNDED_EVIDENCE_LABELS.includes(f.label));

  const documentNames = Array.from(new Set(answer.citations.map((c) => c.document_name)));
  const datasetLabels = Array.from(
    new Set(
      answer.charts
        .map((c) => formatSourceLabel(c.dataset_name, c.dataset_sheet))
        .filter((label): label is string => Boolean(label))
    )
  );
  const sourceLabels = [...datasetLabels, ...documentNames].slice(0, 4);
  const extraCount = datasetLabels.length + documentNames.length - sourceLabels.length;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <GroundedBadge grounded={grounded} />
      {sourceLabels.map((label) => (
        <SourceChip key={label} label={label} />
      ))}
      {extraCount > 0 && (
        <span className="text-[10px] text-[var(--text-muted)]">+{extraCount} more</span>
      )}
    </div>
  );
}

/** Compact, always-visible summary of what the agent did this turn (step /
 * tool-call / citation counts), with the full step-by-step timeline still
 * available on demand -- the existence and scale of the reasoning is never
 * hidden, only its full detail. Replaces the previous all-or-nothing
 * "Show/Hide how DataWise worked" text toggle over a raw monospace log. */
function AgentReasoning({
  trace,
  citationCount,
  showTrace,
  setShowTrace,
}: {
  trace: TraceStep[];
  citationCount: number;
  showTrace: boolean;
  setShowTrace: (fn: (v: boolean) => boolean) => void;
}) {
  const toolCalls = trace.filter((s) => s.stage !== "understanding_question" && s.stage !== "answer").length;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--background)]">
      <button
        onClick={() => setShowTrace((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)]">
          <IconShieldCheck size={14} className="text-[var(--brand)]" />
          {trace.length} step{trace.length === 1 ? "" : "s"} · {toolCalls} tool call{toolCalls === 1 ? "" : "s"}
          {citationCount > 0 ? ` · ${citationCount} citation${citationCount === 1 ? "" : "s"} verified` : ""}
        </span>
        <span className="shrink-0 text-xs font-medium text-[var(--brand)]">
          {showTrace ? "Hide detail" : "Show detail"}
        </span>
      </button>
      {showTrace && <AgentTrace trace={trace} />}
    </div>
  );
}

function AgentTrace({ trace }: { trace: TraceStep[] }) {
  return (
    <div className="flex flex-col gap-2.5 border-t border-[var(--border)] px-3 py-3">
      {trace.map((step, i) => {
        const Icon = STAGE_ICONS[step.stage];
        return (
          <div key={i} className="flex items-start gap-2.5">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--brand-subtle)] text-[var(--brand)]">
              <Icon size={13} />
            </span>
            <div className="min-w-0 pt-0.5">
              <p className="text-xs font-semibold text-[var(--text-primary)]">{STAGE_LABELS[step.stage]}</p>
              <p className="text-xs text-[var(--text-secondary)]">{step.label}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
