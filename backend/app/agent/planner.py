"""Agent orchestration: intent -> tool selection -> evidence -> verification -> answer.

A manual tool-calling loop (not the SDK's beta tool runner) so every
iteration is explicit and inspectable, and so the same loop works
uniformly across both LLM providers via app/ai's normalized types. The
loop only ever affects the world through app/agent/tools.py -- the LLM
never receives raw dataset rows or filesystem access, only schemas,
summaries, calculated results, and retrieved document chunks.
"""

import json
import re
import time
import uuid
from datetime import UTC, datetime

from app.agent.memory import ConversationMemory
from app.agent.schemas import (
    AgentAnswer,
    Citation,
    ClaimComparison,
    CrossCheckLabel,
    EvidenceLabel,
    Finding,
    LLMMetadata,
    ToolInvocation,
    TraceStep,
)
from app.agent.tools import TOOLS, ResearchBudget, ToolContext, ToolExecutionError, verify_claim_tool
from app.agent.verification import (
    verify_claim_comparison,
    verify_document_grounding,
    verify_finding_label,
)
from app.ai.base import LLMProvider
from app.ai.types import ConversationTurn, LLMCallMetadata, ToolResult
from app.config import get_settings
from app.documents.store import DocumentStore
from app.semantic.store import DatasetStore

MAX_TOOL_ITERATIONS_DEFAULT = 8
MAX_OUTPUT_CHARS = 4000

SYSTEM_PROMPT_TEMPLATE = """You are DataWise AI, an AI business analyst investigating the user's \
uploaded business datasets and documents{web_clause}.

CORE RULE: you never invent numbers, dates, percentages, relationships, company facts, or \
document quotes. Every number you state about the data must come from calling a tool \
(calculate_metric, group_and_aggregate, compare_periods, detect_anomalies, correlate, \
generate_chart, generate_dashboard) -- never compute it yourself. Every claim about what a \
document says must come from search_documents / retrieve_document_evidence -- never paraphrase \
from memory.{web_rule} Do not guess at anything about the user's own business. A found passage \
must be cited -- never state its claim uncited. A specific factual question (date/name/number) is \
never GENERAL_ANSWER when a document might contain it -- search first.

QUESTION TYPE: before calling any tools, decide which kind of question this is --

1. A GREETING or small-talk message with no question in it at all (e.g. "Hi", "Hello", "Good \
morning", "How are you?", "Thanks"). This is NOT a failed lookup and NEVER produces "insufficient \
evidence" -- respond with a brief, friendly greeting that says what you can help with (e.g. "Hi! \
I'm DataWise AI. Ask me a general business question, or upload your data and I can calculate real \
answers from it."). Label it GENERAL_ANSWER -- it is not a business fact of any kind.
2. A GENERAL business/conceptual question (e.g. "what is customer churn?", "how do you calculate \
gross margin?", "what's a healthy inventory turnover ratio?", "what is RAG?"). FIRST check the \
uploaded document titles/topics listed below -- if one plausibly covers this exact concept (e.g. a \
document titled "RAG vs Fine-Tuning" when asked "what is RAG?"), call search_documents on it before \
answering; ground your answer in the retrieved passages and label those findings DOCUMENT_EVIDENCE \
with a real citation, same as any other document question. Only skip tool calls and answer from \
your own general knowledge (label GENERAL_ANSWER) when no uploaded document plausibly addresses the \
question -- never assume "conceptual-sounding question" alone means there is nothing to look up. \
Never label a GENERAL_ANSWER finding as CALCULATED/VERIFIED_FROM_DATA/DERIVED -- it is general \
knowledge, not a fact about this user's business, and must never be presented as if it came from \
their data.
3. A DATA-SPECIFIC question (e.g. "what were our total sales last month?", "which region grew \
fastest?") when relevant datasets/documents ARE available: investigate with tools as described \
below.
4. A DATA-SPECIFIC question when NO relevant dataset or document is available at all: do not \
call tools that have nothing to work with. Say plainly that you can't calculate it yet because \
there's no data in the workspace (e.g. "I can't calculate your actual sales yet because there are \
no datasets in your workspace. Upload your sales data and I can calculate it for you."), label it \
INSUFFICIENT_DATA, and do not guess a number.
5. An AMBIGUOUS or underspecified question (e.g. "show me something interesting", "do it", \
"which thing sold most" where revenue vs. quantity isn't specified) or a question with an obvious \
typo you can confidently interpret (e.g. "totl sales", "saless by region"): if you're confident \
what was meant, proceed and briefly note your interpretation in the executive summary (e.g. "I \
interpreted this as: ..."); if genuinely ambiguous in a way that would change the answer \
materially, ask a clarifying question instead of guessing, and label that finding GENERAL_ANSWER \
(a clarifying question is not a data fact).

If the tools genuinely cannot support a data-specific answer even though data exists (wrong \
columns, no matching records), say so plainly: "Insufficient evidence in the uploaded data."

Only call the tools that are actually relevant to this question -- do not call join_datasets, \
run_sql_query, search_documents, or web_research just because they exist. If join_datasets refuses \
a join as many-to-many, inspect cardinality (find_relationships/inspect_schema) before deciding \
whether to retry with allow_fan_out=true; do not retry blindly.

COLUMN NAMES: metric_column/dimension_column/date_column don't need to be the exact schema \
spelling -- pass the natural business term from the question ("product", "sales", "prodcut") and \
it is resolved against the real columns, preferring a descriptive column (product_name) over an \
identifier (product_id) unless the question explicitly asks for the id/code. You can still pass \
an exact column name when you already know it from inspect_schema/inspect_dataset -- both work.

CHART SELECTION: when calling generate_chart, decide the chart from the question's own analytical \
intent, not just how many categories the result has -- a plain "count/total X by Y" question \
should default to bar/column even with few categories, never a donut just because the category \
count happens to be small. Set generate_chart's optional chart_type only when the wording actually \
implies one: "what share/percentage of X is Y", "composition", "distribution by" imply donut/pie; \
"trend", "over time", "monthly/weekly/daily" imply a date_column (line follows automatically); \
"top N", "which X sold/performed the most/best", "highest", "ranking" imply setting top_n and \
sort="desc" (bar). A single aggregate with no dimension_column ("what was total X") is a KPI, not \
a chart at all -- no chart_type needed there. Leave chart_type unset when genuinely unsure; the \
engine's own data-shape default is a safe fallback. Explicitly-named chart words in the question \
("column chart", "bar chart", "line chart", "grouped chart") should be honored directly via \
chart_type unless the shape genuinely can't support it, in which case pick the closest valid chart \
and briefly say why in the executive summary rather than silently ignoring the request.

TWO DIMENSIONS: "X by A and B" (e.g. "sales by region and shipping mode") means setting both \
dimension_column and second_dimension_column on group_and_aggregate/generate_chart -- this produces \
a grouped/stacked breakdown, not two separate calls. "compare X and Y by Z" (two different metrics, \
e.g. "compare sales and cost by region") is different: call group_and_aggregate/generate_chart once \
per metric (X by Z, then Y by Z) and present them together, since a single AnalysisRequest only \
computes one metric at a time.

GEOGRAPHY: a "by country" question implies chart_type="map", but only renders as one when \
dimension_column resolves to a real country column (state/city aren't supported, no coordinate \
lookup exists for them) -- otherwise it falls back to the normal chart, so it's always safe to try.

RATE QUESTIONS ("return rate", "X percentage", "how often", incl. "unusually high rate" -- ignore \
"unusual" here, it does NOT mean detect_anomalies): these ask for matching-rows/total-rows, a \
proportion. "Return_Rate" etc. is not a real column -- never pass it to detect_anomalies (which \
scans one column's own value distribution and has no concept of "rate"; the resolver would silently \
substitute an unrelated column). No tool computes a proportion directly: call group_and_aggregate \
twice per grouping -- once count with a filter matching the condition, once count with no filter for \
the group's total -- state both as findings, then state the resulting percentage in your own answer \
text (safe to derive: it'll be labelled AI_INTERPRETATION unless it happens to match a tool number \
verbatim). Never substitute a different analysis just because no tool computes a rate in one call. \
NEVER guess a flag column's real values ("Yes"/"No" vs 1/0 vs True/False vs a custom word all vary by \
dataset) -- call inspect_dataset first and use its real values in the filter. If a filtered count comes \
back 0 while the unfiltered total is not, that means the filter value was wrong, not that no matching \
rows exist -- re-check inspect_dataset's real values before ever concluding "no such records." \
Self-check: does your last call's filter match the condition asked about (e.g. Return_Flag=="Yes" for \
"return rate")? A call with NO filter never answers a rate question, however confident it sounds.

"How many total X are there" / "how many X" asks for DISTINCT X entities (aggregation=nunique), not \
row count (aggregation=count) -- a fact table is very often one row per LINE ITEM, not one row per X \
(e.g. one order can span several product rows), so count(order_id) silently returns line-item rows, \
not orders. Use count only when the question is genuinely about rows/records themselves.

Available datasets:
{datasets}

Available documents:
{documents}
{memory_section}
When you believe you have gathered enough evidence, stop calling tools and write a short plain \
text summary of what you found (you will be asked to structure it afterwards -- this text is \
just your working summary, not the final answer format).

If asked to compare a document's claim against the data (e.g. "does the data support \
management's explanation?"), always: (1) calculate the relevant data facts with tools, \
(2) retrieve the specific document passage with search_documents/retrieve_document_evidence, \
(3) explicitly state whether the data supports, contradicts, or cannot verify the document's \
claim -- never blur a document's opinion into a verified data fact. This structured comparison \
is mandatory whenever the question invokes both a document claim and the data: you MUST populate \
claim_comparisons in your final structured answer, not just describe the comparison in prose. \
Do this even when the question already states the document's claim in its own wording -- you \
must still call search_documents/retrieve_document_evidence yourself to get the actual citation \
before writing the comparison; a comparison with no real citation can only ever be labelled \
INSUFFICIENT_EVIDENCE, never SUPPORTED_BY_DATA or CONTRADICTED_BY_DATA, no matter how confident \
you are that you already know what the document says.
"""

SYNTHESIS_SYSTEM_PROMPT = """You are formatting the results of a business-data investigation \
into a structured executive report. You already gathered evidence via tool calls; you are now \
given a digest of every tool call and its result. Produce ONLY a single JSON object (no prose, \
no markdown fences) with this exact shape:

{
  "executive_summary": "1-3 sentence plain-language summary of the key business finding. Do NOT mention chart types, chart creation, or visualization in the executive_summary -- the frontend renders charts automatically from chart_tool_call_ids. Focus on the business insight.",
  "key_findings": [ {"text": "...", "label": "VERIFIED_FROM_DATA|CALCULATED|DERIVED|DOCUMENT_EVIDENCE|VERIFIED_FROM_WEB|AI_INTERPRETATION|INSUFFICIENT_DATA|GENERAL_ANSWER", "citations": [{"document_id": "...", "chunk_id": "..."} or {"url": "..."}]} ],
  "risks": [ {"text": "...", "label": "...", "citations": [...]} ],
  "recommendations": [ {"text": "...", "label": "AI_INTERPRETATION", "citations": [...]} ],
  "claim_comparisons": [ {"document_claim": "...", "citation": {"document_id": "...", "chunk_id": "..."}, "data_finding": "...", "label": "SUPPORTED_BY_DATA|DOCUMENT_CLAIM|NOT_VERIFIED_BY_DATA|CONTRADICTED_BY_DATA|INSUFFICIENT_EVIDENCE", "explanation": "..."} ],
  "chart_tool_call_ids": ["<tool call id from the digest, for any generate_chart/generate_dashboard call worth showing>"]
}

Rules:
- label is REQUIRED on every finding/risk/recommendation. Recommendations are always \
"AI_INTERPRETATION" -- never state a recommendation as fact.
- Only use VERIFIED_FROM_DATA/CALCULATED/DERIVED when the exact number appears in a tool result \
in the digest below.
- Only use DOCUMENT_EVIDENCE when you have an actual chunk_id from a search_documents or \
retrieve_document_evidence result to cite. Only use VERIFIED_FROM_WEB when you have an actual url \
from a web_research result to cite.
- An empty tool digest does NOT automatically mean "INSUFFICIENT_DATA" -- it also happens for \
greetings, general/conceptual questions, and clarifying questions, none of which needed a tool \
call in the first place. Use "INSUFFICIENT_DATA" (text: "Insufficient evidence in the uploaded \
data.", or the friendlier no-data wording from the system prompt) ONLY when the question was \
actually asking about the user's own data/business and there was nothing to calculate it from. \
For a greeting, a general/conceptual question, or a clarifying question, label every finding \
"GENERAL_ANSWER" instead and answer/respond appropriately -- never claim insufficient evidence \
for a question that was never about the user's data.
- citations arrays may be empty. Omit chart_tool_call_ids entirely (empty array) if not applicable.
- CRITICAL: Never write phrases like "a bar chart was created", "a chart has been generated", \
"I've created a visualization", or any similar chart-creation narration in executive_summary, \
key_findings, or anywhere in the JSON. The UI renders charts automatically from chart_tool_call_ids. \
State the business finding directly (e.g. "Technology leads all categories with $X in sales").
- chart_tool_call_ids: list EVERY succeeded generate_chart and generate_dashboard tool call id \
from the digest -- do not omit any. The frontend relies on this list to display all computed visuals.

MANDATORY: if the digest contains BOTH a calculated/verified data fact AND a document passage \
making a related claim (e.g. the question asks whether the data supports, confirms, or matches \
something a document says), you MUST add a claim_comparisons entry -- do not fold that comparison \
into key_findings prose only, even if you also mention it there. Worked example: if a \
calculate_metric result shows a 14.7% revenue increase and a search_documents result quotes a \
document saying "revenue increased by 18%", output:
  "claim_comparisons": [ {
    "document_claim": "Revenue increased by 18%.",
    "citation": {"document_id": "doc_123", "chunk_id": "chunk_45"},
    "data_finding": "Calculated revenue increase was 14.7%.",
    "label": "CONTRADICTED_BY_DATA",
    "explanation": "The document claims an 18% increase, but the calculated figure from the data is 14.7% -- the two do not match."
  } ]
claim_comparisons must never be left empty when the digest has both a document claim and a \
matching/conflicting calculated figure to compare it against.

Output raw JSON only.
"""


def _format_datasets(dataset_store: DatasetStore) -> str:
    summaries = dataset_store.list_summaries()
    if not summaries:
        return "  (none uploaded yet)"
    lines = []
    for s in summaries:
        lines.append(f"  - id={s.id} name=\"{s.name}\" rows={s.row_count} columns={s.column_count} kind={s.kind.value}")
    return "\n".join(lines)


def _format_documents(document_store: DocumentStore) -> str:
    summaries = document_store.list_summaries()
    if not summaries:
        return "  (none uploaded yet)"
    lines = []
    for d in summaries:
        lines.append(f"  - id={d.id} filename=\"{d.filename}\" type={d.document_type.value} chunks={d.chunk_count}")
    return "\n".join(lines)


def _build_system_prompt(
    dataset_store: DatasetStore,
    document_store: DocumentStore,
    memory_context: str | None,
    web_enabled: bool = False,
) -> str:
    memory_section = ""
    if memory_context:
        memory_section = f"\nRecent conversation in this session (use it for context on follow-up questions):\n{memory_context}\n"
    web_clause = " and, when useful, researching the public web" if web_enabled else ""
    web_rule = (
        " Every claim sourced from the web must come from web_research -- never state external "
        "facts (market data, competitor info, news) from memory."
        if web_enabled
        else ""
    )
    return SYSTEM_PROMPT_TEMPLATE.format(
        datasets=_format_datasets(dataset_store),
        documents=_format_documents(document_store),
        memory_section=memory_section,
        web_clause=web_clause,
        web_rule=web_rule,
    )


def _trace_step_for_tool(inv: ToolInvocation) -> TraceStep:
    stage_map = {
        "list_datasets": "datasets",
        "inspect_dataset": "datasets",
        "inspect_schema": "datasets",
        "find_relationships": "relationships",
        "join_datasets": "relationships",
        "calculate_metric": "analysis",
        "group_and_aggregate": "analysis",
        "compare_periods": "analysis",
        "detect_anomalies": "analysis",
        "correlate": "analysis",
        "generate_chart": "analysis",
        "generate_dashboard": "analysis",
        "search_documents": "document_research",
        "retrieve_document_evidence": "document_research",
        "web_research": "web_research",
        "verify_claim": "verification",
    }
    stage = stage_map.get(inv.tool_name, "analysis")
    status = "✓" if inv.succeeded else "✗"
    return TraceStep(
        stage=stage,
        label=f"{status} {inv.tool_name}({', '.join(f'{k}={v}' for k, v in inv.input.items())})",
        detail=inv.output_summary[:280],
    )


def _execute_tool(name: str, args: dict, ctx: ToolContext, tool_invocations: list[ToolInvocation]) -> ToolInvocation:
    start = time.monotonic()
    try:
        if name == "verify_claim":
            output = verify_claim_tool(args, ctx, tool_invocations)
        else:
            tool = TOOLS.get(name)
            if tool is None or tool.handler is None:
                raise ToolExecutionError(f"Unknown tool '{name}'.")
            output = tool.handler(args, ctx)
        succeeded = True
        output_text = json.dumps(output, default=str)
    except ToolExecutionError as exc:
        succeeded = False
        output_text = f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 -- a tool bug must not crash the agent turn
        succeeded = False
        output_text = f"Error: unexpected tool failure -- {exc}"

    if len(output_text) > MAX_OUTPUT_CHARS:
        output_text = output_text[:MAX_OUTPUT_CHARS] + " ...[truncated]"

    duration_ms = int((time.monotonic() - start) * 1000)
    return ToolInvocation(
        id=str(uuid.uuid4())[:8], tool_name=name, input=args, output_summary=output_text,
        succeeded=succeeded, duration_ms=duration_ms,
    )


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _to_schema_metadata(md: LLMCallMetadata | None) -> LLMMetadata | None:
    if md is None:
        return None
    return LLMMetadata(
        provider=md.provider,
        model=md.model,
        fallback_used=md.fallback_used,
        attempt_count=md.attempt_count,
        latency_ms=md.latency_ms,
    )


def _synthesize_answer(
    llm: LLMProvider,
    question: str,
    tool_invocations: list[ToolInvocation],
    working_summary: str | None,
    currency: str | None = None,
    decimal_places: int | None = None,
) -> tuple[dict | None, LLMCallMetadata | None]:
    digest_lines = [f"Question: {question}", ""]
    if currency:
        # Presentation-only, matching the user's Settings choice -- the
        # underlying tool-result numbers are unchanged either way. Without
        # this the model has no signal at all and tends to default to "$",
        # which is wrong for every other configured currency.
        digest_lines.append(
            f"Presentation: when stating a genuinely monetary figure in prose (an amount of money -- "
            f"revenue, cost, profit, price, salary, spend -- never a count, id, percentage, rating, "
            f"score, index, or ratio; a 1-5 customer rating or a distinct-count is not money and must "
            f"never get a currency symbol), format it as {currency} with "
            f"{decimal_places if decimal_places is not None else 2} decimal place(s), e.g. the standard "
            f"Intl.NumberFormat currency rendering for {currency}. Never invent a different currency symbol, "
            f"and never apply one to a number that isn't actually money."
        )
        digest_lines.append("")
    if working_summary:
        digest_lines += ["Agent's working summary:", working_summary, ""]
    digest_lines.append("Tool calls made this turn:")
    for inv in tool_invocations:
        digest_lines.append(
            f"- id={inv.id} tool={inv.tool_name} input={json.dumps(inv.input, default=str)} "
            f"succeeded={inv.succeeded} result={inv.output_summary}"
        )
    digest = "\n".join(digest_lines)

    turn = llm.send(SYNTHESIS_SYSTEM_PROMPT, [ConversationTurn(role="user", text=digest)], tools=[])
    if turn.stop_reason == "error" or not turn.text:
        return None, turn.metadata
    return _parse_json_object(turn.text), turn.metadata


def _resolve_web_citation(url: str, tool_invocations: list[ToolInvocation]) -> Citation | None:
    """Unlike document citations, web results aren't pre-indexed anywhere
    to look up by id -- resolve by matching the cited url against this
    turn's own web_research tool results, so a web citation is always
    traceable to a real search result, never trusted from the LLM's raw
    claim alone."""
    for inv in tool_invocations:
        if inv.tool_name != "web_research" or not inv.succeeded:
            continue
        try:
            payload = json.loads(inv.output_summary)
        except json.JSONDecodeError:
            continue
        for r in payload.get("results", []) or []:
            if r.get("url") == url:
                return Citation(
                    document_id="",
                    document_name=r.get("title") or url,
                    chunk_id="",
                    location={},
                    excerpt=(r.get("snippet") or "")[:400],
                    relevance_score=1.0,
                    source_type="web",
                    url=url,
                )
    return None


def _resolve_citation(ref: dict, ctx: ToolContext, tool_invocations: list[ToolInvocation]) -> Citation | None:
    url = ref.get("url")
    if url:
        return _resolve_web_citation(url, tool_invocations)

    document_id = ref.get("document_id")
    chunk_id = ref.get("chunk_id")
    if not document_id or not chunk_id:
        return None
    chunk = ctx.document_store.get_chunk(document_id, chunk_id)
    if chunk is None:
        return None
    return Citation(
        document_id=document_id,
        document_name=chunk.document_name,
        chunk_id=chunk_id,
        location=chunk.location.model_dump(exclude_none=True),
        excerpt=chunk.text[:400],
        relevance_score=1.0,
    )


def _build_finding(raw: dict, ctx: ToolContext, tool_invocations: list[ToolInvocation]) -> Finding:
    text = str(raw.get("text", "")).strip()
    try:
        claimed_label = EvidenceLabel(raw.get("label", "AI_INTERPRETATION"))
    except ValueError:
        claimed_label = EvidenceLabel.AI_INTERPRETATION

    citations = [c for c in (_resolve_citation(r, ctx, tool_invocations) for r in raw.get("citations", []) or []) if c]

    # Any real citation only ever comes from a document/web chunk lookup
    # (_resolve_citation) -- a calculate_metric-style tabular claim never
    # has one, since there's no chunk to cite. So citations being
    # non-empty is, by construction, a document/web-grounded statement,
    # regardless of what label the LLM picked or whether the claim
    # happens to contain a number. Phase 4 spec: "a document-grounded
    # statement must not be labelled VERIFIED_FROM_DATA." (Baseline eval
    # known-issue #3.)
    #
    # Numeric claims used to be excluded from this check and fell back to
    # verify_finding_label instead (matching the claimed number against
    # ANY number in ANY of this turn's tool outputs, with a 2% tolerance)
    # -- found live (a RAG "not in the data" quality-bar test): that
    # let a fabricated number ("GPT-4 scored 86.5% on MMLU") get labelled
    # VERIFIED_FROM_DATA because a real search_documents call that turn
    # happened to retrieve a genuinely-cited passage (a hyperparameter
    # table) containing some unrelated number that was merely numerically
    # close -- topically irrelevant, but the tool-output check has no
    # concept of topic, only magnitude. verify_document_grounding's own
    # lexical-overlap check doesn't have that blind spot, and its
    # "if not claim_words: return True" fallback already handles the
    # legitimate bare-numeric-quote case (e.g. a citation whose claim
    # text is just "41.0") without a special-case here.
    # A claim self-labelled DOCUMENT_EVIDENCE/VERIFIED_FROM_WEB is, by
    # definition, claiming to be grounded in a document or web source --
    # so it goes through the same check even with zero citations attached
    # (verify_document_grounding's own "if not citation_excerpts" branch
    # correctly fails that case). Found live: VERIFIED_FROM_WEB with no
    # citations at all previously fell to the `else` branch below, which
    # only checks NUMERIC_LABELS (VERIFIED_FROM_WEB isn't one) and so
    # returned the self-claimed label completely unchecked -- a second,
    # distinct escape hatch from the one citations-with-a-real-chunk fixes.
    if citations or claimed_label in (EvidenceLabel.DOCUMENT_EVIDENCE, EvidenceLabel.VERIFIED_FROM_WEB):
        original_label = claimed_label
        target_label = (
            EvidenceLabel.VERIFIED_FROM_WEB
            if (citations and citations[0].source_type == "web") or claimed_label == EvidenceLabel.VERIFIED_FROM_WEB
            else EvidenceLabel.DOCUMENT_EVIDENCE
        )
        grounded, note = verify_document_grounding(text, [c.excerpt for c in citations])
        if not grounded:
            # Found live (a RAG quality-bar test's "not in the data" tier):
            # downgrading the label alone still left the original citation
            # attached to a claim this exact check just determined the
            # citation does NOT support -- a citation next to a claim
            # flagged as ungrounded is worse than no citation at all, since
            # it reads as evidence when it explicitly isn't. Clear it.
            claimed_label, note, citations = EvidenceLabel.AI_INTERPRETATION, note, []
        elif claimed_label not in (EvidenceLabel.DOCUMENT_EVIDENCE, EvidenceLabel.VERIFIED_FROM_WEB):
            claimed_label = target_label
            note = f"Reclassified from {original_label.value}: this is a document-grounded statement, not a calculated data fact."
        verification_note = note
    else:
        claimed_label, verification_note = verify_finding_label(text, claimed_label, tool_invocations)

    return Finding(text=text, label=claimed_label, verification_note=verification_note, citations=citations)


_GROUNDING_FAILURE_MARKERS = ("No citation was attached", "does not share enough wording")

INSUFFICIENT_EVIDENCE_TEXT = "Insufficient evidence in the uploaded data."


def _all_key_findings_failed_grounding(findings: list[Finding]) -> bool:
    """True only when every one of this turn's key findings was downgraded
    specifically because verify_document_grounding determined the cited
    evidence doesn't support it (see the two note strings it raises) --
    not merely "labelled AI_INTERPRETATION" in general, which is also the
    legitimate label for a safely-derived value (e.g. a rate-question
    percentage computed from two verified counts; see the RATE QUESTIONS
    system-prompt section). Only this specific, mechanical failure
    signature means the model attempted a document-grounded answer and
    produced nothing that actually checks out.

    Found live (a RAG "not in the data" quality-bar test): key_findings
    already caught and correctly downgraded this exact failure, but
    executive_summary -- the LLM's own freeform prose, and the first
    thing a user reads -- is taken verbatim from the model's raw output
    and was never checked against that outcome at all. Temperature is
    already 0 everywhere in this codebase (app/config.py's default);
    provider-level sampling isn't perfectly deterministic even at 0, so
    this is a mechanical backstop for exactly the turns where that
    non-determinism produces a confident-sounding but unverifiable claim,
    not a substitute for the verification that already runs -- it forces
    the one part of the answer that skipped it to agree with the part
    that didn't."""
    if not findings:
        return False
    return all(
        f.label == EvidenceLabel.AI_INTERPRETATION
        and f.verification_note is not None
        and any(marker in f.verification_note for marker in _GROUNDING_FAILURE_MARKERS)
        for f in findings
    )


def _build_claim_comparison(raw: dict, ctx: ToolContext, tool_invocations: list[ToolInvocation]) -> ClaimComparison:
    citation = _resolve_citation(raw.get("citation") or {}, ctx, tool_invocations)
    try:
        label = CrossCheckLabel(raw.get("label", "INSUFFICIENT_EVIDENCE"))
    except ValueError:
        label = CrossCheckLabel.INSUFFICIENT_EVIDENCE

    explanation = str(raw.get("explanation", "")).strip()
    if label in (CrossCheckLabel.SUPPORTED_BY_DATA, CrossCheckLabel.CONTRADICTED_BY_DATA):
        ok, note = verify_claim_comparison(raw.get("data_finding"), tool_invocations)
        if not ok:
            label = CrossCheckLabel.INSUFFICIENT_EVIDENCE
            explanation = note or explanation
    if label != CrossCheckLabel.DOCUMENT_CLAIM and citation is None:
        label = CrossCheckLabel.INSUFFICIENT_EVIDENCE

    return ClaimComparison(
        document_claim=str(raw.get("document_claim", "")).strip(),
        citation=citation,
        data_finding=raw.get("data_finding"),
        label=label,
        explanation=explanation,
    )


def run_agent(
    *,
    question: str,
    session_id: str | None,
    llm: LLMProvider | None,
    dataset_store: DatasetStore,
    document_store: DocumentStore,
    memory: ConversationMemory,
    max_iterations: int = MAX_TOOL_ITERATIONS_DEFAULT,
    tool_names: set[str] | None = None,
    currency: str | None = None,
    decimal_places: int | None = None,
) -> AgentAnswer:
    """tool_names restricts which tools the LLM may call this turn (None =
    all tools, the original Phase 3 behavior). Used by app/agent/graph.py's
    router to scope a question to only the resource categories (data/
    documents/web) it actually needs, per Phase 4's agentic-RAG routing.
    currency/decimal_places are the user's Settings presentation
    preference, passed through to synthesis so prose figures match what
    the UI renders instead of the model defaulting to "$"."""
    session_id = session_id or uuid.uuid4().hex
    created_at = datetime.now(UTC)
    trace: list[TraceStep] = [
        TraceStep(stage="understanding_question", label="Understanding question", detail=question)
    ]

    if llm is None:
        return AgentAnswer(
            question=question,
            session_id=session_id,
            configured=False,
            error="AI features are not configured: set LLM_PROVIDER and LLM_API_KEY to enable the "
            "AI analyst. Dataset upload, profiling, relationships, joins, KPIs, and insights all "
            "continue to work without an LLM.",
            trace=trace,
            created_at=created_at,
        )

    settings = get_settings()
    web_enabled = tool_names is None or "web_research" in tool_names
    ctx = ToolContext(
        dataset_store=dataset_store,
        document_store=document_store,
        settings=settings,
        llm_provider=llm,
        research_budget=ResearchBudget(
            max_queries=settings.max_research_queries, max_tool_calls=settings.max_research_tool_calls
        ),
    )
    memory_context = memory.format_for_prompt(session_id)
    system_prompt = _build_system_prompt(dataset_store, document_store, memory_context, web_enabled=web_enabled)

    trace.append(TraceStep(stage="datasets", label="Datasets in scope", detail=_format_datasets(dataset_store)))
    if document_store.list_summaries():
        trace.append(TraceStep(stage="documents", label="Documents in scope", detail=_format_documents(document_store)))

    tool_schemas = [t.schema for t in TOOLS.values() if tool_names is None or t.schema.name in tool_names]
    history: list[ConversationTurn] = [ConversationTurn(role="user", text=question)]
    tool_invocations: list[ToolInvocation] = []
    working_summary: str | None = None
    latest_metadata: LLMCallMetadata | None = None

    for _ in range(max_iterations):
        turn = llm.send(system_prompt, history, tool_schemas)
        latest_metadata = turn.metadata or latest_metadata

        if turn.stop_reason == "error":
            return AgentAnswer(
                question=question, session_id=session_id, configured=True,
                error=turn.text or "The LLM request failed.", trace=trace,
                tool_invocations=tool_invocations, llm_metadata=_to_schema_metadata(latest_metadata),
                created_at=created_at,
            )

        if not turn.tool_calls:
            working_summary = turn.text
            history.append(ConversationTurn(role="assistant", text=turn.text))
            break

        history.append(ConversationTurn(role="assistant", text=turn.text, tool_calls=turn.tool_calls))
        tool_results: list[ToolResult] = []
        for tc in turn.tool_calls:
            invocation = _execute_tool(tc.name, tc.input, ctx, tool_invocations)
            tool_invocations.append(invocation)
            trace.append(_trace_step_for_tool(invocation))
            tool_results.append(
                ToolResult(tool_call_id=tc.id, content=invocation.output_summary, is_error=not invocation.succeeded)
            )
        history.append(ConversationTurn(role="user", tool_results=tool_results))
    else:
        working_summary = working_summary or "Reached the maximum number of analysis steps."

    structured, synth_metadata = _synthesize_answer(
        llm, question, tool_invocations, working_summary, currency=currency, decimal_places=decimal_places
    )
    latest_metadata = synth_metadata or latest_metadata

    if structured is None:
        # Structured synthesis failed to parse -- degrade honestly rather than fabricate structure.
        answer = AgentAnswer(
            question=question, session_id=session_id, configured=True,
            executive_summary=working_summary,
            key_findings=[
                Finding(text=working_summary or "No answer could be produced.", label=EvidenceLabel.AI_INTERPRETATION)
            ],
            trace=trace, tool_invocations=tool_invocations, raw_answer_text=working_summary,
            llm_metadata=_to_schema_metadata(latest_metadata),
            created_at=created_at,
        )
    else:
        key_findings = [_build_finding(f, ctx, tool_invocations) for f in structured.get("key_findings", [])]
        if _all_key_findings_failed_grounding(key_findings):
            # executive_summary is the LLM's own raw prose and, unlike
            # key_findings, was never checked against the verification
            # outcome above -- without this, a user reads a confident
            # sentence with no sign anything was flagged, even though
            # every finding behind it just failed grounding. Force the
            # visible answer to agree with what verification already
            # found, rather than trusting synthesis to have gotten it
            # right the first time.
            structured["executive_summary"] = INSUFFICIENT_EVIDENCE_TEXT
        risks = [_build_finding(f, ctx, tool_invocations) for f in structured.get("risks", [])]
        recommendations = [_build_finding(f, ctx, tool_invocations) for f in structured.get("recommendations", [])]
        claim_comparisons = [
            _build_claim_comparison(c, ctx, tool_invocations) for c in structured.get("claim_comparisons", [])
        ]

        # Build the chart list from the synthesis LLM's explicit list of
        # chart_tool_call_ids -- but fall back to every succeeded
        # generate_chart / generate_dashboard invocation when that list is
        # empty or missing. The synthesis LLM sometimes omits call IDs from
        # chart_tool_call_ids even when the chart was computed correctly;
        # the fallback guarantees charts always appear rather than
        # silently disappearing.
        chart_call_ids: list[str] = structured.get("chart_tool_call_ids", []) or []

        if not chart_call_ids:
            # No IDs listed -- collect every succeeded chart/dashboard call.
            chart_call_ids = [
                inv.id
                for inv in tool_invocations
                if inv.succeeded and inv.tool_name in ("generate_chart", "generate_dashboard")
            ]

        charts: list[dict] = []
        seen_chart_ids: set[str] = set()
        for call_id in chart_call_ids:
            inv = next((t for t in tool_invocations if t.id == call_id and t.succeeded), None)
            if inv is None:
                continue
            try:
                payload = json.loads(inv.output_summary)
            except json.JSONDecodeError:
                continue
            if inv.tool_name == "generate_chart":
                chart = payload.get("chart")
                if chart:
                    # Deduplicate by dataset_id + chart_type + x_column + y_column
                    dedup_key = f"{chart.get('dataset_id')}|{chart.get('chart_type')}|{chart.get('x_column')}|{chart.get('y_column')}"
                    if dedup_key not in seen_chart_ids:
                        seen_chart_ids.add(dedup_key)
                        charts.append(chart)
            elif inv.tool_name == "generate_dashboard":
                for c in payload.get("charts", []):
                    chart = c.get("chart")
                    if chart:
                        dedup_key = f"{chart.get('dataset_id')}|{chart.get('chart_type')}|{chart.get('x_column')}|{chart.get('y_column')}"
                        if dedup_key not in seen_chart_ids:
                            seen_chart_ids.add(dedup_key)
                            charts.append(chart)

        # Secondary pass: if the LLM called group_and_aggregate,
        # calculate_metric, detect_anomalies, or correlate instead of
        # generate_chart, the deterministic engine already computed and
        # attached a chart_recommendation inside the tool result.
        # Promote it so the analysis is never text-only when a visual
        # was already calculated for free.
        if not charts:
            _ANALYSIS_TOOLS = ("group_and_aggregate", "calculate_metric", "detect_anomalies", "correlate")
            for inv in tool_invocations:
                if not inv.succeeded or inv.tool_name not in _ANALYSIS_TOOLS:
                    continue
                try:
                    payload = json.loads(inv.output_summary)
                except json.JSONDecodeError:
                    continue
                chart = payload.get("chart_recommendation")
                if chart and chart.get("chart_type") not in ("insufficient_data", None):
                    dedup_key = f"{chart.get('dataset_id')}|{chart.get('chart_type')}|{chart.get('x_column')}|{chart.get('y_column')}"
                    if dedup_key not in seen_chart_ids:
                        seen_chart_ids.add(dedup_key)
                        charts.append(chart)

        all_citations: list[Citation] = []
        seen = set()
        for f in [*key_findings, *risks, *recommendations]:
            for c in f.citations:
                key = (c.document_id, c.chunk_id, c.url)
                if key not in seen:
                    seen.add(key)
                    all_citations.append(c)
        for c in claim_comparisons:
            if c.citation:
                key = (c.citation.document_id, c.citation.chunk_id, c.citation.url)
                if key not in seen:
                    seen.add(key)
                    all_citations.append(c.citation)

        verified_count = sum(
            1 for f in [*key_findings, *risks, *recommendations] if f.verification_note is None
        )
        downgraded = [f for f in [*key_findings, *risks, *recommendations] if f.verification_note]
        trace.append(
            TraceStep(
                stage="verification",
                label=f"{verified_count} claim(s) verified, {len(downgraded)} downgraded",
                detail="; ".join(f.verification_note for f in downgraded[:5]) or "All claimed labels confirmed.",
            )
        )
        trace.append(
            TraceStep(
                stage="answer",
                label="Answer produced",
                detail=structured.get("executive_summary", "") or "",
            )
        )

        answer = AgentAnswer(
            question=question, session_id=session_id, configured=True,
            executive_summary=structured.get("executive_summary"),
            key_findings=key_findings, risks=risks, recommendations=recommendations,
            claim_comparisons=claim_comparisons, charts=charts, citations=all_citations,
            trace=trace, tool_invocations=tool_invocations, raw_answer_text=working_summary,
            llm_metadata=_to_schema_metadata(latest_metadata),
            created_at=created_at,
        )

    memory.append(session_id, question, answer.executive_summary or (working_summary or "")[:300])
    return answer
