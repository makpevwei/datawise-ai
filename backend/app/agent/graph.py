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
    "DATA_ONLY",
    "DOCUMENTS_ONLY",
    "DATA_AND_DOCUMENTS",
    "DATA_AND_WEB",
    "DOCUMENTS_AND_WEB",
    "DATA_AND_DOCUMENTS_AND_WEB",
    # A question that has absolutely no connection to the user's uploaded
    # data, documents, or business -- e.g. "who is the president of Nigeria",
    # "what is the capital of France". Gets answered directly from general
    # knowledge, with no tool calls, labelled GENERAL_ANSWER throughout.
    # The router must be VERY conservative about assigning this category:
    # when genuinely unsure, route to DATA_ONLY (or whichever data/doc
    # category fits) rather than here. A real business question wrongly
    # routed to GENERAL_KNOWLEDGE would bypass all grounding verification
    # entirely -- that is worse than the problem this route is meant to fix.
    "GENERAL_KNOWLEDGE",
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
    "DATA_ONLY": DATA_TOOLS | ALWAYS_AVAILABLE,
    "DOCUMENTS_ONLY": DOCUMENT_TOOLS | ALWAYS_AVAILABLE,
    "DATA_AND_DOCUMENTS": DATA_TOOLS | DOCUMENT_TOOLS | ALWAYS_AVAILABLE,
    "DATA_AND_WEB": DATA_TOOLS | WEB_TOOLS | ALWAYS_AVAILABLE,
    "DOCUMENTS_AND_WEB": DOCUMENT_TOOLS | WEB_TOOLS | ALWAYS_AVAILABLE,
    "DATA_AND_DOCUMENTS_AND_WEB": DATA_TOOLS | DOCUMENT_TOOLS | WEB_TOOLS | ALWAYS_AVAILABLE,
    # No tools at all: the agent loop skips tool calls immediately and goes
    # straight to synthesis, which labels findings GENERAL_ANSWER when the
    # question is genuinely off-topic. verify_claim is excluded deliberately
    # -- it requires tool-invocation history to check against, and with no
    # data/doc/web tools in scope there is nothing to verify.
    "GENERAL_KNOWLEDGE": set(),
}

ROUTER_SYSTEM_PROMPT = """Classify what resources are needed to answer the user's question about \
their uploaded business data. Reply with EXACTLY ONE of these seven words and nothing else:

DATA_ONLY - only needs calculations/analysis over uploaded datasets (CSV/XLSX).
DOCUMENTS_ONLY - only needs retrieval from uploaded documents (PDF/DOCX/PPTX/TXT/MD/PY).
DATA_AND_DOCUMENTS - needs both, e.g. comparing a document's claim against calculated data.
DATA_AND_WEB - needs dataset calculations plus external/public web context.
DOCUMENTS_AND_WEB - needs document retrieval plus external/public web context.
DATA_AND_DOCUMENTS_AND_WEB - needs all three.
GENERAL_KNOWLEDGE - ONLY for questions that are pure general-world-knowledge facts with \
absolutely no connection to business data analysis, the user's uploaded files, or their own \
business at all (e.g. "who is the president of Nigeria", "what is the capital of France", \
"when was the Eiffel Tower built"). These are questions a printed encyclopedia would answer \
identically regardless of what data the user has uploaded. DO NOT use this for any business \
or analytical question, even a conceptual one (e.g. "what is customer churn?", "how do I \
calculate gross margin?" are business questions -- use DATA_ONLY or DOCUMENTS_ONLY). When in \
doubt, do NOT pick GENERAL_KNOWLEDGE -- default to DATA_ONLY instead. A real business question \
wrongly sent here bypasses all data verification.

Only pick a _WEB category if the question explicitly asks about something external to the \
uploaded data/documents (e.g. "industry benchmark", "competitor", "current market conditions", \
"latest news") -- never pick a _WEB category just because web research happens to be available.
If unsure: prefer DATA_AND_DOCUMENTS when both datasets and documents are uploaded, DATA_ONLY \
when only datasets are uploaded, DOCUMENTS_ONLY when only documents are uploaded.

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


def _heuristic_route(question: str, has_datasets: bool, has_documents: bool, has_web: bool) -> RouteCategory:
    """Fallback when the LLM router is unavailable/unparseable. Defaults
    to the broadest available combination (matching Phase 3's original
    always-every-tool behavior) unless a web-ish term is clearly present,
    so this can only ever narrow scope on top of an explicit signal, never
    silently drop a resource category a question needed."""
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
        # GENERAL_KNOWLEDGE is always a valid route the LLM needs to consider
        # (a user can ask an off-topic question regardless of what data they
        # have uploaded), so the LLM router call now runs unconditionally --
        # the old optimisation that skipped it when only one resource category
        # was available no longer applies. The heuristic is still the fallback
        # for any LLM failure, and it never returns GENERAL_KNOWLEDGE (it
        # always defaults to the broadest available data/doc category), which
        # is the right conservative behaviour for an LLM-unavailable scenario.
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
