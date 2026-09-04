"""LangGraph router (app/agent/graph.py): question -> route -> scoped
tool-calling loop -> answer. Never hits a real LLM API."""

import json
from datetime import datetime, timezone

import pytest

from app.agent.graph import (
    DATA_TOOLS,
    DOCUMENT_TOOLS,
    ROUTE_TOOLS,
    WEB_TOOLS,
    _heuristic_route,
    _llm_route,
    _looks_like_a_greeting,
    run_agentic_graph,
)
from app.agent.memory import ConversationMemory
from app.ai.types import LLMTurn
from app.documents.models import ChunkLocation, DocumentSummary, DocumentType
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore
from tests.factories import orders_df
from tests.fakes import FakeLLMProvider


def _empty_synthesis() -> str:
    return json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )


def _dataset_store(tmp_path) -> DatasetStore:
    store = DatasetStore(storage_dir=tmp_path / "datasets")
    orders = orders_df(5)
    store.put("orders", orders, profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
    return store


def _document_store_with_doc(tmp_path) -> DocumentStore:
    from app.documents.chunking import chunk_segments
    from app.documents.extraction import Segment

    store = DocumentStore(storage_dir=tmp_path / "documents")
    chunks = chunk_segments([Segment(text="Revenue grew this quarter.", location=ChunkLocation(page=1))], "doc1", "report.pdf")
    store.put(
        DocumentSummary(id="doc1", filename="report.pdf", document_type=DocumentType.PDF, chunk_count=len(chunks), char_count=10, created_at=datetime.now(timezone.utc)),
        chunks,
    )
    return store


def _empty_document_store(tmp_path) -> DocumentStore:
    return DocumentStore(storage_dir=tmp_path / "documents_empty")


# -- Heuristic routing (no LLM needed) ----------------------------------------


def test_heuristic_routes_data_only_when_only_datasets_exist():
    assert _heuristic_route("What is total revenue?", has_datasets=True, has_documents=False, has_web=True) == "DATA_ONLY"


def test_heuristic_routes_documents_only_when_only_documents_exist():
    assert _heuristic_route("What does the report say?", has_datasets=False, has_documents=True, has_web=True) == "DOCUMENTS_ONLY"


def test_heuristic_defaults_to_data_and_documents_when_both_exist_and_ambiguous():
    assert _heuristic_route("Summarize everything.", has_datasets=True, has_documents=True, has_web=True) == "DATA_AND_DOCUMENTS"


def test_heuristic_escalates_to_web_only_on_explicit_web_terms():
    route = _heuristic_route("How does our growth compare to the industry benchmark?", has_datasets=True, has_documents=False, has_web=True)
    assert route == "DATA_AND_WEB"


def test_heuristic_never_escalates_to_web_when_not_configured():
    # Same question, but has_web=False -- must never route to a _WEB category.
    route = _heuristic_route("How does our growth compare to the industry benchmark?", has_datasets=True, has_documents=False, has_web=False)
    assert route == "DATA_ONLY"
    assert "WEB" not in route


def test_heuristic_routes_a_bare_greeting_to_general_or_greeting_even_with_datasets_available():
    # Regression: previously the heuristic had no concept of "no resource
    # needed" -- a workspace with only datasets forced DATA_ONLY on every
    # question regardless of content.
    assert _heuristic_route("hi", has_datasets=True, has_documents=False, has_web=True) == "GENERAL_OR_GREETING"
    assert _heuristic_route("thanks!", has_datasets=True, has_documents=True, has_web=True) == "GENERAL_OR_GREETING"


@pytest.mark.parametrize(
    "text",
    ["hi", "Hi", "hello", "hey", "good morning", "thanks", "thank you", "  hi  ", "hi!"],
)
def test_looks_like_a_greeting_matches_bare_greetings(text):
    assert _looks_like_a_greeting(text) is True


@pytest.mark.parametrize(
    "text",
    ["what is total revenue?", "hi, what is our churn rate", "what is RAG?", "hi there, quick question about sales"],
)
def test_looks_like_a_greeting_does_not_match_real_questions(text):
    # Conservative by design: never misroute an actual question, even one
    # that happens to start with a greeting-ish word.
    assert _looks_like_a_greeting(text) is False


@pytest.mark.parametrize("route", list(ROUTE_TOOLS.keys()))
def test_every_route_category_has_a_nonempty_tool_set(route):
    assert ROUTE_TOOLS[route]  # every category has at least verify_claim + something


def test_route_tool_sets_are_scoped_correctly():
    assert ROUTE_TOOLS["DATA_ONLY"] >= DATA_TOOLS
    assert not (ROUTE_TOOLS["DATA_ONLY"] & DOCUMENT_TOOLS)
    assert not (ROUTE_TOOLS["DATA_ONLY"] & WEB_TOOLS)
    assert ROUTE_TOOLS["DOCUMENTS_ONLY"] >= DOCUMENT_TOOLS
    assert not (ROUTE_TOOLS["DOCUMENTS_ONLY"] & DATA_TOOLS)
    assert ROUTE_TOOLS["DATA_AND_DOCUMENTS_AND_WEB"] >= (DATA_TOOLS | DOCUMENT_TOOLS | WEB_TOOLS)


def test_general_or_greeting_excludes_data_tools_but_keeps_document_search():
    # The core fix: a general-knowledge/greeting question must never be
    # able to reach a data-analysis tool (that's what let the model
    # "helpfully" profile an unrelated dataset instead of just answering),
    # but document search stays available since a real uploaded document
    # might plausibly cover the concept being asked about.
    assert not (ROUTE_TOOLS["GENERAL_OR_GREETING"] & DATA_TOOLS)
    assert ROUTE_TOOLS["GENERAL_OR_GREETING"] >= DOCUMENT_TOOLS
    assert not (ROUTE_TOOLS["GENERAL_OR_GREETING"] & WEB_TOOLS)


# -- LLM-based routing ---------------------------------------------------------


def test_llm_route_parses_a_clean_category_response():
    llm = FakeLLMProvider([LLMTurn(text="DOCUMENTS_ONLY", tool_calls=[], stop_reason="end_turn")])
    route = _llm_route(llm, "What does the report say?", has_datasets=False, has_documents=True, has_web=False)
    assert route == "DOCUMENTS_ONLY"


def test_llm_route_tolerates_extra_text_around_the_category():
    llm = FakeLLMProvider([LLMTurn(text="I'd classify this as: DATA_AND_DOCUMENTS.", tool_calls=[], stop_reason="end_turn")])
    route = _llm_route(llm, "does data support the report?", has_datasets=True, has_documents=True, has_web=False)
    assert route == "DATA_AND_DOCUMENTS"


def test_llm_route_returns_none_on_unparseable_response():
    llm = FakeLLMProvider([LLMTurn(text="I'm not sure what you mean.", tool_calls=[], stop_reason="end_turn")])
    route = _llm_route(llm, "huh?", has_datasets=True, has_documents=True, has_web=False)
    assert route is None


def test_llm_route_returns_none_on_error_turn():
    llm = FakeLLMProvider([LLMTurn(text="boom", tool_calls=[], stop_reason="error")])
    route = _llm_route(llm, "anything", has_datasets=True, has_documents=False, has_web=False)
    assert route is None


# -- Full graph run (route -> scoped agent loop -> answer) --------------------


def test_graph_scopes_tools_to_the_routed_category(tmp_path):
    llm = FakeLLMProvider(
        [
            LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn"),  # router
            LLMTurn(text="direct answer, no tools needed", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="What is total revenue?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store_with_doc(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.configured is True
    assert any(step.stage == "routing" and "DATA_ONLY" in step.label for step in answer.trace)
    # The agent-loop call (calls[1]) must only have been offered DATA_ONLY tools.
    _, _, tools_offered = llm.calls[1]
    offered_names = {t.name for t in tools_offered}
    assert offered_names <= ROUTE_TOOLS["DATA_ONLY"]
    assert "search_documents" not in offered_names
    assert "web_research" not in offered_names


def test_graph_with_no_llm_degrades_honestly_without_routing(tmp_path):
    answer = run_agentic_graph(
        question="What is total revenue?", session_id=None, llm=None,
        dataset_store=_dataset_store(tmp_path), document_store=_empty_document_store(tmp_path),
        memory=ConversationMemory(),
    )
    assert answer.configured is False
    assert not any(step.stage == "routing" for step in answer.trace)


def test_graph_still_calls_the_llm_router_when_only_one_resource_category_is_available(tmp_path, monkeypatch):
    # Regression: this case (only a dataset store, no documents, no web)
    # is exactly the demo-account scenario that produced the original bug
    # -- "what is RAG?" got silently forced onto DATA_ONLY and answered
    # with unrelated dataset stats, because the LLM router was skipped
    # entirely whenever only one resource category existed. A single
    # available resource category is not the same thing as "this question
    # obviously needs that category" -- the router must still run so a
    # greeting/general-knowledge question can land on GENERAL_OR_GREETING
    # instead. Only a bare, unambiguous greeting (see the heuristic test
    # above) still skips the LLM call.
    monkeypatch.setattr("app.agent.graph._web_research_configured", lambda: False)
    llm = FakeLLMProvider(
        [
            LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn"),  # router
            LLMTurn(text="direct answer, no tools needed", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="What is total revenue?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_empty_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.configured is True
    assert answer.executive_summary == "ok"
    assert len(llm.calls) == 3
    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "DATA_ONLY" in routing_step.label
    assert routing_step.detail.startswith("(llm)")


def test_graph_skips_the_llm_router_call_for_a_bare_greeting(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.graph._web_research_configured", lambda: False)
    llm = FakeLLMProvider(
        [
            LLMTurn(text="Hi! I'm DataWise AI.", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="hi", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_empty_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.configured is True
    assert len(llm.calls) == 2
    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "GENERAL_OR_GREETING" in routing_step.label
    assert "no LLM call needed" in routing_step.detail


def test_graph_routes_a_general_knowledge_question_away_from_data_tools_even_with_only_datasets_available(tmp_path, monkeypatch):
    # The exact reported bug, end to end: a workspace with datasets but no
    # documents, asked a question with zero relation to those datasets.
    # The fix must make it structurally impossible for the agent loop to
    # reach for a data-analysis tool here, regardless of what the model
    # would have chosen to do if offered one.
    monkeypatch.setattr("app.agent.graph._web_research_configured", lambda: False)
    llm = FakeLLMProvider(
        [
            LLMTurn(text="GENERAL_OR_GREETING", tool_calls=[], stop_reason="end_turn"),  # router
            LLMTurn(
                text="RAG (Retrieval-Augmented Generation) grounds an LLM's answer in retrieved evidence "
                "instead of relying only on its training data.",
                tool_calls=[], stop_reason="end_turn",
            ),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="what is rag", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_empty_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.configured is True
    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "GENERAL_OR_GREETING" in routing_step.label
    # The agent-loop call (calls[1]) must not have been offered any data tool.
    _, _, tools_offered = llm.calls[1]
    offered_names = {t.name for t in tools_offered}
    assert not (offered_names & DATA_TOOLS)


def test_graph_still_calls_the_llm_router_when_datasets_and_documents_are_both_available(tmp_path, monkeypatch):
    # The genuinely ambiguous case (which of two available resource types
    # does this question need) is exactly where the LLM router keeps
    # earning its round-trip -- must not be skipped here.
    monkeypatch.setattr("app.agent.graph._web_research_configured", lambda: False)
    llm = FakeLLMProvider(
        [
            LLMTurn(text="DOCUMENTS_ONLY", tool_calls=[], stop_reason="end_turn"),  # router
            LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="What does the report say?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store_with_doc(tmp_path),
        memory=ConversationMemory(),
    )

    assert len(llm.calls) == 3
    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "DOCUMENTS_ONLY" in routing_step.label


def test_graph_falls_back_to_heuristic_when_router_response_is_unparseable(tmp_path):
    llm = FakeLLMProvider(
        [
            LLMTurn(text="uh, not sure", tool_calls=[], stop_reason="end_turn"),  # unparseable router response
            LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="Summarize everything.", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store_with_doc(tmp_path),
        memory=ConversationMemory(),
    )

    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "heuristic" in routing_step.detail
    assert "DATA_AND_DOCUMENTS" in routing_step.label
