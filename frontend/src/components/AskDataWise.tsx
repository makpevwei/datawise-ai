"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { askAgent, createReport, exportAnalysisPdf, getAgentStatus, getKpiSuggestions, getReportPdf, getSession } from "@/lib/api";
import type { AgentAnswer, AgentFinding, ClaimComparison, DatasetSummary, KPISuggestion, TraceStep } from "@/lib/types";
import { buildStarterQuestions, BUSINESS_STARTER_QUESTIONS, GENERIC_STARTER_QUESTIONS } from "@/lib/starterQuestions";
import { useAuth } from "@/lib/auth-context";
import { ChartFromSpec } from "./charts";
import { DatasetPicker } from "./DatasetPicker";
import {
  Button,
  Card,
  CrossCheckBadge,
  ErrorBanner,
  SectionHeading,
  SourceLabelBadge,
  Spinner,
} from "./ui";

const UNSET = Symbol("unset");

const STAGE_LABELS: Record<TraceStep["stage"], string> = {
  understanding_question: "UNDERSTANDING QUESTION",
  routing: "ROUTING",
  datasets: "DATASETS",
  documents: "DOCUMENTS",
  relationships: "RELATIONSHIPS",
  analysis: "ANALYSIS",
  document_research: "DOCUMENT RESEARCH",
  web_research: "WEB RESEARCH",
  verification: "VERIFICATION",
  answer: "ANSWER",
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
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[] | null>(null);

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

  const starterQuestions = datasets.length > 0
    ? [...BUSINESS_STARTER_QUESTIONS, ...buildStarterQuestions(starterKpis)].slice(0, 12)
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
            className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--series-1)]"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1.5">
              {starterQuestions.map((q) => (
                <button
                  key={q}
                  onClick={() => setQuestion(q)}
                  disabled={loading}
                  className="rounded-full border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--text-secondary)] hover:border-[var(--series-1)] hover:text-[var(--series-1)] disabled:opacity-40"
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
                    <ChartFromSpec spec={chart} currency={currency} decimalPlaces={decimalPlaces} />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <button
              onClick={() => setShowTrace((v) => !v)}
              className="text-xs font-medium text-[var(--series-1)] hover:underline"
            >
              {showTrace ? "Hide" : "Show"} how DataWise worked ({answer.tool_invocations.length} tool call
              {answer.tool_invocations.length === 1 ? "" : "s"})
            </button>
            {showTrace && <AgentTrace trace={answer.trace} />}
          </div>

          <FindingList title="Key Findings" findings={answer.key_findings} />
          <FindingList title="Risks" findings={answer.risks} />
          <FindingList title="Recommended Areas to Investigate" findings={answer.recommendations} />

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
              <ul className="flex flex-col gap-1.5 text-xs text-[var(--text-secondary)]">
                {answer.citations.map((c) => (
                  <li key={`${c.document_id}-${c.chunk_id}`}>
                    <span className="font-medium text-[var(--text-primary)]">{c.document_name}</span>
                    {Object.entries(c.location)
                      .filter(([, v]) => v !== null && v !== undefined)
                      .map(([k, v]) => ` (${k}: ${v})`)
                      .join("")}
                    : &ldquo;{c.excerpt.slice(0, 160)}
                    {c.excerpt.length > 160 ? "…" : ""}&rdquo;
                  </li>
                ))}
              </ul>
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

function FindingList({ title, findings }: { title: string; findings: AgentFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</p>
      <ul className="flex flex-col gap-2">
        {findings.map((f, i) => (
          <li key={i} className="flex flex-col gap-1">
            <div className="flex items-start gap-2">
              <SourceLabelBadge label={f.label} />
              <span className="text-sm text-[var(--text-primary)]">{f.text}</span>
            </div>
            {f.verification_note && (
              <p className="ml-1 text-xs italic text-[var(--text-muted)]">{f.verification_note}</p>
            )}
          </li>
        ))}
      </ul>
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

function AgentTrace({ trace }: { trace: TraceStep[] }) {
  return (
    <div className="mt-2 flex flex-col gap-1 rounded-lg bg-[var(--background)] p-3 font-mono text-xs">
      {trace.map((step, i) => (
        <div key={i}>
          <span className="text-[var(--text-muted)]">{STAGE_LABELS[step.stage]}</span>
          <div className="ml-2 text-[var(--text-primary)]">✓ {step.label}</div>
        </div>
      ))}
    </div>
  );
}
