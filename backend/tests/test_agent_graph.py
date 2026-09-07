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


@pytest.mark.parametrize("route", [r for r in ROUTE_TOOLS.keys() if r != "GENERAL_KNOWLEDGE"])
def test_every_route_category_has_a_nonempty_tool_set(route):
    assert ROUTE_TOOLS[route]  # every category except GENERAL_KNOWLEDGE has at least verify_claim + something


def test_general_knowledge_route_has_no_tools():
    # GENERAL_KNOWLEDGE intentionally exposes zero tools -- the agent loop
    # skips tool calls entirely and goes straight to synthesis, which labels
    # findings GENERAL_ANSWER. verify_claim is excluded because it requires
    # tool-invocation history to check against.
    assert ROUTE_TOOLS["GENERAL_KNOWLEDGE"] == set()


def test_route_tool_sets_are_scoped_correctly():
    assert ROUTE_TOOLS["DATA_ONLY"] >= DATA_TOOLS
    assert not (ROUTE_TOOLS["DATA_ONLY"] & DOCUMENT_TOOLS)
    assert not (ROUTE_TOOLS["DATA_ONLY"] & WEB_TOOLS)
    assert ROUTE_TOOLS["DOCUMENTS_ONLY"] >= DOCUMENT_TOOLS
    assert not (ROUTE_TOOLS["DOCUMENTS_ONLY"] & DATA_TOOLS)
    assert ROUTE_TOOLS["DATA_AND_DOCUMENTS_AND_WEB"] >= (DATA_TOOLS | DOCUMENT_TOOLS | WEB_TOOLS)


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


def test_graph_always_calls_the_llm_router_even_with_one_resource_category(tmp_path, monkeypatch):
    # With GENERAL_KNOWLEDGE now a valid route, the LLM router must always
    # run -- a user can ask "who is the president of Nigeria?" regardless of
    # what data they have uploaded, and only the LLM can recognise that.
    # Three turns: router + agent loop + synthesis.
    monkeypatch.setattr("app.agent.graph._web_research_configured", lambda: False)
    llm = FakeLLMProvider(
        [
            LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn"),   # router
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
    assert "llm" in routing_step.detail


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


# -- GENERAL_KNOWLEDGE route --------------------------------------------------


def test_llm_route_parses_general_knowledge_category():
    llm = FakeLLMProvider([LLMTurn(text="GENERAL_KNOWLEDGE", tool_calls=[], stop_reason="end_turn")])
    route = _llm_route(llm, "who is the president of Nigeria?", has_datasets=True, has_documents=False, has_web=False)
    assert route == "GENERAL_KNOWLEDGE"


def test_heuristic_never_returns_general_knowledge():
    # The heuristic is the LLM-unavailable fallback -- it must always err
    # toward data/docs, never GENERAL_KNOWLEDGE, which requires LLM judgment.
    for has_ds, has_doc in [(True, False), (False, True), (True, True), (False, False)]:
        result = _heuristic_route("who is the president of Nigeria?", has_datasets=has_ds, has_documents=has_doc, has_web=False)
        assert result != "GENERAL_KNOWLEDGE", f"heuristic returned GENERAL_KNOWLEDGE for has_datasets={has_ds}, has_documents={has_doc}"


def test_graph_routes_general_knowledge_with_no_tools(tmp_path):
    # When the LLM router returns GENERAL_KNOWLEDGE, the agent loop must
    # receive an empty tool set -- it goes straight to synthesis with no
    # tool calls, and synthesis labels findings GENERAL_ANSWER.
    gk_synthesis = json.dumps({
        "executive_summary": "Bola Tinubu has been Nigeria's president since May 2023.",
        "key_findings": [{"text": "Bola Tinubu is the president of Nigeria.", "label": "GENERAL_ANSWER", "citations": []}],
        "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
    })
    llm = FakeLLMProvider(
        [
            LLMTurn(text="GENERAL_KNOWLEDGE", tool_calls=[], stop_reason="end_turn"),  # router
            LLMTurn(text="Bola Tinubu is the president of Nigeria.", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=gk_synthesis, tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="Who is the president of Nigeria?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_empty_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.configured is True
    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "GENERAL_KNOWLEDGE" in routing_step.label

    # The agent-loop call must have been offered zero tools.
    _, _, tools_offered = llm.calls[1]
    assert tools_offered == []

    # Every finding must carry GENERAL_ANSWER, not a data label.
    from app.agent.schemas import EvidenceLabel
    for finding in answer.key_findings:
        assert finding.label == EvidenceLabel.GENERAL_ANSWER


def test_graph_data_question_does_not_slip_into_general_knowledge(tmp_path):
    # A business-adjacent question ("what is gross margin?") must NOT route
    # to GENERAL_KNOWLEDGE even when the user has only datasets -- it should
    # stay DATA_ONLY so the agent can check whether the data contains an
    # answer before falling back to general knowledge.
    llm = FakeLLMProvider(
        [
            LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn"),  # router correctly picks DATA_ONLY
            LLMTurn(text="no tools needed", tool_calls=[], stop_reason="end_turn"),  # agent loop
            LLMTurn(text=_empty_synthesis(), tool_calls=[], stop_reason="end_turn"),  # synthesis
        ]
    )

    answer = run_agentic_graph(
        question="What is gross margin and how do I improve it?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_empty_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    routing_step = next(step for step in answer.trace if step.stage == "routing")
    assert "GENERAL_KNOWLEDGE" not in routing_step.label
    assert "DATA_ONLY" in routing_step.label
