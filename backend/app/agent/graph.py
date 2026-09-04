"""Bounded, inspectable LangGraph workflow: QUESTION -> ROUTER -> GATHER &
ANSWER -> END.

This graph orchestrates the existing Phase 3 tool-calling loop
(app/agent/planner.run_agent) -- it does not reimplement dataset
inspection, document retrieval, tool selection, calculation, evidence
verification, or synthesis, all of which stay exactly as Phase 3/3A built
them (same LLM gateway, same verification engine, same tools). What this
graph adds is the ROUTER step: deciding up front which resource
categories (data / documents / web) a question actually needs, so the
agent loop that follows is scoped to only the relevant tools instead of
always exposing every tool. Two nodes, no cycles, a hard recursion limit --
"a small graph, not many agents."
"""

import re
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.agent.memory import ConversationMemory
from app.agent.planner import MAX_TOOL_ITERATIONS_DEFAULT, run_agent
from app.agent.schemas import AgentAnswer, TraceStep
from app.ai.base import LLMProvider
from app.ai.types import ConversationTurn
from app.config import get_settings
from app.documents.store import DocumentStore
from app.semantic.store import DatasetStore

RouteCategory = Literal[
    "GENERAL_OR_GREETING",
    "DATA_ONLY",
    "DOCUMENTS_ONLY",
    "DATA_AND_DOCUMENTS",
    "DATA_AND_WEB",
    "DOCUMENTS_AND_WEB",
    "DATA_AND_DOCUMENTS_AND_WEB",
]

DATA_TOOLS = {
    "list_datasets", "inspect_dataset", "inspect_schema", "find_relationships", "join_datasets",
    "calculate_metric", "group_and_aggregate", "compare_periods", "detect_anomalies", "correlate",
    "generate_chart", "generate_dashboard",
}
DOCUMENT_TOOLS = {"search_documents", "retrieve_document_evidence"}
WEB_TOOLS = {"web_research"}
ALWAYS_AVAILABLE = {"verify_claim"}

ROUTE_TOOLS: dict[RouteCategory, set[str]] = {
    # A greeting or a general/conceptual question not about the user's own
    # data (e.g. "what is RAG?") never needs data-analysis tools -- keeping
    # DATA_TOOLS out structurally is what stops the model from "helpfully"
    # profiling an unrelated dataset when it can't find anything else to
    # do with the tools it's been given. Document search stays available
    # since the system prompt's own rule still requires checking whether
    # an uploaded document happens to cover the concept before falling
    # back to general knowledge.
    "GENERAL_OR_GREETING": DOCUMENT_TOOLS | ALWAYS_AVAILABLE,
    "DATA_ONLY": DATA_TOOLS | ALWAYS_AVAILABLE,
    "DOCUMENTS_ONLY": DOCUMENT_TOOLS | ALWAYS_AVAILABLE,
    "DATA_AND_DOCUMENTS": DATA_TOOLS | DOCUMENT_TOOLS | ALWAYS_AVAILABLE,
    "DATA_AND_WEB": DATA_TOOLS | WEB_TOOLS | ALWAYS_AVAILABLE,
    "DOCUMENTS_AND_WEB": DOCUMENT_TOOLS | WEB_TOOLS | ALWAYS_AVAILABLE,
    "DATA_AND_DOCUMENTS_AND_WEB": DATA_TOOLS | DOCUMENT_TOOLS | WEB_TOOLS | ALWAYS_AVAILABLE,
}

ROUTER_SYSTEM_PROMPT = """Classify what resources are needed to answer the user's question about \
their uploaded business data. Reply with EXACTLY ONE of these seven words and nothing else:

GENERAL_OR_GREETING - a greeting/small talk (e.g. "hi", "thanks"), or a general conceptual \
question that is not asking about the user's OWN uploaded data or business (e.g. "what is RAG?", \
"how do you calculate gross margin?", "what's a healthy inventory turnover ratio?"). Pick this \
even when datasets are uploaded -- answering it never requires calculating anything from them. \
Only pick a data/document category instead if the question asks about the user's own numbers, \
records, or business (e.g. "what is OUR gross margin", "what is our churn rate").
DATA_ONLY - only needs calculations/analysis over uploaded datasets (CSV/XLSX).
DOCUMENTS_ONLY - only needs retrieval from uploaded documents (PDF/DOCX/PPTX/TXT/MD/PY).
DATA_AND_DOCUMENTS - needs both, e.g. comparing a document's claim against calculated data.
DATA_AND_WEB - needs dataset calculations plus external/public web context.
DOCUMENTS_AND_WEB - needs document retrieval plus external/public web context.
DATA_AND_DOCUMENTS_AND_WEB - needs all three.

Only pick a _WEB category if the question explicitly asks about something external to the \
uploaded data/documents (e.g. "industry benchmark", "competitor", "current market conditions", \
"latest news") -- never pick a _WEB category just because web research happens to be available.
If unsure between GENERAL_OR_GREETING and a data/document category: pick GENERAL_OR_GREETING \
unless the question clearly references the user's own data/business specifically. Otherwise, if \
unsure: prefer DATA_AND_DOCUMENTS when both datasets and documents are uploaded, DATA_ONLY when \
only datasets are uploaded, DOCUMENTS_ONLY when only documents are uploaded.

Datasets uploaded: {has_datasets}
Documents uploaded: {has_documents}
Web research available: {has_web}
"""

_ROUTE_WORD_RE = re.compile(r"[A-Z_]+")


def _llm_route(llm: LLMProvider, question: str, has_datasets: bool, has_documents: bool, has_web: bool) -> RouteCategory | None:
    """One bounded, cheap classification call -- never a loop. Returns None
    (never raises) on any failure so routing always has a fallback."""
    prompt = ROUTER_SYSTEM_PROMPT.format(has_datasets=has_datasets, has_documents=has_documents, has_web=has_web)
    try:
        turn = llm.send(prompt, [ConversationTurn(role="user", text=question)], tools=[])
    except Exception:  # noqa: BLE001 -- routing must never crash the question
        return None
    if turn.stop_reason == "error" or not turn.text:
        return None
    for candidate in _ROUTE_WORD_RE.findall(turn.text.upper()):
        if candidate in ROUTE_TOOLS:
            return candidate
    return None


_GREETING_PHRASES = frozenset({
    "hi", "hello", "hey", "hiya", "yo",
    "good morning", "good afternoon", "good evening",
    "how are you", "how's it going", "hows it going", "what's up", "whats up",
    "thanks", "thank you", "thanks!", "thank you!", "ok", "okay", "cool",
})


def _looks_like_a_greeting(question: str) -> bool:
    """Very conservative, false-positive-averse check for rule 1's exact
    case (a greeting/small-talk message with no question in it at all) --
    used only to skip the LLM router call for the unambiguous case; never
    used to override an LLM classification. A real data question never
    collapses to one of these bare phrases, so this cannot misroute one."""
    normalized = question.strip().lower().rstrip("!.?")
    return normalized in _GREETING_PHRASES


def _heuristic_route(question: str, has_datasets: bool, has_documents: bool, has_web: bool) -> RouteCategory:
    """Fallback when the LLM router is unavailable/unparseable. Defaults
    to the broadest available combination (matching Phase 3's original
    always-every-tool behavior) unless a web-ish term is clearly present,
    so this can only ever narrow scope on top of an explicit signal, never
    silently drop a resource category a question needed. The one exception
    is an unambiguous greeting, which never needs any resource category."""
    if _looks_like_a_greeting(question):
        return "GENERAL_OR_GREETING"

    q = question.lower()
    web_terms = (
        "industry benchmark", "competitor", "market trend", "current market",
        "latest news", "public web", "external benchmark", "market conditions",
    )
    wants_web = has_web and any(t in q for t in web_terms)

    if has_datasets and has_documents:
        base: RouteCategory = "DATA_AND_DOCUMENTS"
    elif has_documents:
        base = "DOCUMENTS_ONLY"
    else:
        base = "DATA_ONLY"

    if not wants_web:
        return base
    escalation: dict[RouteCategory, RouteCategory] = {
        "DATA_AND_DOCUMENTS": "DATA_AND_DOCUMENTS_AND_WEB",
        "DOCUMENTS_ONLY": "DOCUMENTS_AND_WEB",
        "DATA_ONLY": "DATA_AND_WEB",
    }
    return escalation[base]


def _web_research_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.tavily_api_key
        or settings.exa_api_key
        or settings.firecrawl_api_key
        or settings.serpapi_api_key
        or (settings.google_cse_id and settings.google_cse_api_key)
    )


class GraphState(TypedDict, total=False):
    question: str
    session_id: str | None
    route: RouteCategory
    route_source: str
    answer: AgentAnswer


def _build_graph(
    llm: LLMProvider,
    dataset_store: DatasetStore,
    document_store: DocumentStore,
    memory: ConversationMemory,
    max_iterations: int,
    currency: str | None = None,
    decimal_places: int | None = None,
):
    has_datasets = bool(dataset_store.list_summaries())
    has_documents = bool(document_store.list_summaries())
    has_web = _web_research_configured()

    def route_node(state: GraphState) -> dict:
        # A single-resource workspace (data XOR documents, no web) still
        # needs classification, not just resource-availability lookup --
        # the question itself might not be about that resource at all
        # (a greeting, or a general/conceptual question like "what is
        # RAG?"). Skipping the LLM router there previously meant every
        # such question was silently forced onto DATA_ONLY, which cannot
        # ever produce a GENERAL_OR_GREETING route: the model was left
        # with only data-analysis tools for a question that had nothing
        # to do with the data, and would resort to "helpfully" profiling
        # it instead of just answering directly. The one case still safe
        # to resolve without an LLM call is an unambiguous bare greeting,
        # caught by _looks_like_a_greeting -- anything else always goes
        # through the LLM classifier, which knows the seventh option.
        if _looks_like_a_greeting(state["question"]):
            return {"route": "GENERAL_OR_GREETING", "route_source": "heuristic (unambiguous greeting, no LLM call needed)"}

        route = _llm_route(llm, state["question"], has_datasets, has_documents, has_web)
        source = "llm"
        if route is None:
            route = _heuristic_route(state["question"], has_datasets, has_documents, has_web)
            source = "heuristic"
        return {"route": route, "route_source": source}

    def gather_and_answer_node(state: GraphState) -> dict:
        route = state["route"]
        tool_names = ROUTE_TOOLS[route]
        answer = run_agent(
            question=state["question"],
            session_id=state["session_id"],
            llm=llm,
            dataset_store=dataset_store,
            document_store=document_store,
            memory=memory,
            max_iterations=max_iterations,
            tool_names=tool_names,
            currency=currency,
            decimal_places=decimal_places,
        )
        answer.trace.insert(
            1,
            TraceStep(
                stage="routing",
                label=f"Routed to {route}",
                detail=f"({state['route_source']}) tools in scope: {', '.join(sorted(tool_names))}",
            ),
        )
        return {"answer": answer}

    graph = StateGraph(GraphState)
    graph.add_node("route", route_node)
    graph.add_node("gather_and_answer", gather_and_answer_node)
    graph.set_entry_point("route")
    graph.add_edge("route", "gather_and_answer")
    graph.add_edge("gather_and_answer", END)
    return graph.compile()


def run_agentic_graph(
    *,
    question: str,
    session_id: str | None,
    llm: LLMProvider | None,
    dataset_store: DatasetStore,
    document_store: DocumentStore,
    memory: ConversationMemory,
    max_iterations: int = MAX_TOOL_ITERATIONS_DEFAULT,
    currency: str | None = None,
    decimal_places: int | None = None,
) -> AgentAnswer:
    """Public entry point: routes, then runs the existing Phase 3 agent
    loop scoped to the routed tool set. Degrades exactly like a direct
    run_agent() call when no LLM is configured -- routing needs an LLM
    (or falls back to the heuristic; with no LLM at all there's nothing to
    route to anyway, since the whole agent is unavailable). currency/
    decimal_places are the user's Settings presentation preference, passed
    through so the synthesized prose formats monetary figures the same way
    the UI does instead of the model defaulting to "$"."""
    if llm is None:
        return run_agent(
            question=question, session_id=session_id, llm=None,
            dataset_store=dataset_store, document_store=document_store, memory=memory,
            max_iterations=max_iterations, currency=currency, decimal_places=decimal_places,
        )

    compiled = _build_graph(llm, dataset_store, document_store, memory, max_iterations, currency, decimal_places)
    result = compiled.invoke(
        {"question": question, "session_id": session_id},
        config={"recursion_limit": 10},
    )
    return result["answer"]
