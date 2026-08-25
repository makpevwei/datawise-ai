import json
from datetime import datetime, timezone

from app.agent.memory import ConversationMemory
from app.agent.planner import run_agent
from app.ai.types import LLMTurn, ToolCall
from app.documents.chunking import chunk_segments
from app.documents.extraction import Segment
from app.documents.models import ChunkLocation, DocumentSummary, DocumentType
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore
from tests.fakes import FakeLLMProvider
from tests.factories import orders_df

TOTAL_AMOUNT = sum(100.0 + i * 10 for i in range(1, 21))


def _dataset_store(tmp_path) -> DatasetStore:
    store = DatasetStore(storage_dir=tmp_path / "datasets")
    orders = orders_df(20)
    store.put("orders", orders, profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
    return store


def _document_store(tmp_path) -> DocumentStore:
    store = DocumentStore(storage_dir=tmp_path / "documents")
    chunks = chunk_segments(
        [Segment(text="Management attributes the Q2 revenue decline to a regional supply disruption.", location=ChunkLocation(page=2))],
        "doc1", "management_report.pdf",
    )
    store.put(
        DocumentSummary(
            id="doc1", filename="management_report.pdf", document_type=DocumentType.PDF,
            chunk_count=len(chunks), char_count=sum(len(c.text) for c in chunks),
            created_at=datetime.now(timezone.utc),
        ),
        chunks,
    )
    return store


def test_run_agent_without_llm_degrades_honestly(tmp_path):
    answer = run_agent(
        question="What were total sales?", session_id=None, llm=None,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(),
    )
    assert answer.configured is False
    assert "not configured" in answer.error.lower()
    assert answer.tool_invocations == []
    assert answer.trace[0].stage == "understanding_question"


def test_run_agent_calls_tool_and_labels_confirmed_number(tmp_path):
    tool_call = ToolCall(
        id="call_1", name="calculate_metric",
        input={"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum"},
    )
    turn1 = LLMTurn(text=None, tool_calls=[tool_call], stop_reason="tool_use")
    turn2 = LLMTurn(text="Calculated total sales.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": f"Total sales were {TOTAL_AMOUNT}.",
            "key_findings": [{"text": f"Total sales were {TOTAL_AMOUNT}.", "label": "CALCULATED", "citations": []}],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn3 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2, turn3])
    answer = run_agent(
        question="What were total sales?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.configured is True
    assert len(answer.tool_invocations) == 1
    assert answer.tool_invocations[0].tool_name == "calculate_metric"
    assert answer.tool_invocations[0].succeeded is True
    assert answer.key_findings[0].label == "CALCULATED"
    assert answer.key_findings[0].verification_note is None
    assert any(step.stage == "analysis" for step in answer.trace)


def test_run_agent_tells_the_synthesis_call_the_users_currency_and_decimal_places(tmp_path):
    # The synthesis LLM call formats the prose executive summary/findings --
    # without an explicit instruction it has no way to know the user picked
    # NGN in Settings and would default to "$". The digest handed to that
    # call must carry the presentation preference.
    turn1 = LLMTurn(text="direct answer, no tools needed", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    llm = FakeLLMProvider([turn1, turn2])

    run_agent(
        question="What were total sales?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(), currency="NGN", decimal_places=0,
    )

    synthesis_call_history = llm.calls[-1][1]
    digest_text = synthesis_call_history[0].text
    assert "NGN" in digest_text
    assert "0 decimal place" in digest_text


def test_run_agent_omits_the_currency_instruction_when_none_is_provided(tmp_path):
    turn1 = LLMTurn(text="direct answer, no tools needed", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    llm = FakeLLMProvider([turn1, turn2])

    run_agent(
        question="What were total sales?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    synthesis_call_history = llm.calls[-1][1]
    digest_text = synthesis_call_history[0].text
    assert "Presentation:" not in digest_text


def test_run_agent_downgrades_unsupported_numeric_claim(tmp_path):
    tool_call = ToolCall(
        id="call_1", name="calculate_metric",
        input={"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum"},
    )
    turn1 = LLMTurn(text=None, tool_calls=[tool_call], stop_reason="tool_use")
    turn2 = LLMTurn(text="Calculated total sales.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": "Total sales were 999999.",
            "key_findings": [{"text": "Total sales were 999999.", "label": "VERIFIED_FROM_DATA", "citations": []}],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn3 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2, turn3])
    answer = run_agent(
        question="What were total sales?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.key_findings[0].label == "AI_INTERPRETATION"
    assert answer.key_findings[0].verification_note is not None
    assert any(step.stage == "verification" and "downgraded" in step.detail.lower() for step in answer.trace)


def test_run_agent_refuses_when_no_evidence_gathered(tmp_path):
    turn1 = LLMTurn(text="I have no evidence for this.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": "Insufficient evidence in the uploaded data.",
            "key_findings": [{"text": "Insufficient evidence in the uploaded data.", "label": "INSUFFICIENT_DATA", "citations": []}],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2])
    answer = run_agent(
        question="What is our profit margin on unicorns?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.tool_invocations == []
    assert answer.key_findings[0].label == "INSUFFICIENT_DATA"
    assert "Insufficient evidence" in answer.key_findings[0].text


def test_run_agent_answers_general_question_without_calling_tools(tmp_path):
    # A conceptual question with no dependency on the user's own data should
    # be answered directly, labeled GENERAL_ANSWER, and never presented as a
    # fact from the user's business data. No datasets/documents are uploaded
    # at all here -- there's genuinely nothing to look up.
    turn1 = LLMTurn(text="Customer churn is the rate at which customers stop doing business with a company.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": "Customer churn is the rate at which customers stop doing business with a company over a given period.",
            "key_findings": [
                {
                    "text": "Customer churn is the rate at which customers stop doing business with a company over a given period.",
                    "label": "GENERAL_ANSWER",
                    "citations": [],
                }
            ],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2])
    answer = run_agent(
        question="What is customer churn?", session_id=None, llm=llm,
        dataset_store=DatasetStore(storage_dir=tmp_path / "datasets"),
        document_store=DocumentStore(storage_dir=tmp_path / "documents"),
        memory=ConversationMemory(),
    )

    assert answer.tool_invocations == []
    assert answer.key_findings[0].label == "GENERAL_ANSWER"
    assert "churn" in answer.key_findings[0].text.lower()


def test_run_agent_resolves_document_citation_from_real_chunk(tmp_path):
    document_store = _document_store(tmp_path)
    search_result = document_store.retrieve("supply disruption", top_k=1)[0]
    chunk_id = search_result.chunk.id

    search_call = ToolCall(id="call_1", name="search_documents", input={"query": "supply disruption"})
    turn1 = LLMTurn(text=None, tool_calls=[search_call], stop_reason="tool_use")
    turn2 = LLMTurn(text="Found the relevant passage.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": "Management cites a supply disruption.",
            "key_findings": [
                {
                    "text": "Management attributes the Q2 revenue decline to a regional supply disruption.",
                    "label": "DOCUMENT_EVIDENCE",
                    "citations": [{"document_id": "doc1", "chunk_id": chunk_id}],
                }
            ],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn3 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2, turn3])
    answer = run_agent(
        question="What does management say caused the decline?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=document_store,
        memory=ConversationMemory(),
    )

    assert answer.key_findings[0].label == "DOCUMENT_EVIDENCE"
    assert len(answer.key_findings[0].citations) == 1
    assert answer.key_findings[0].citations[0].document_name == "management_report.pdf"
    assert answer.citations[0].chunk_id == chunk_id


def test_run_agent_reclassifies_document_paraphrase_mislabeled_as_verified_from_data(tmp_path):
    # Regression test for the Phase 3 eval's known-issue #3: a non-numeric
    # paraphrase of a document (a real citation attached, no digits to
    # mechanically check) must never surface as VERIFIED_FROM_DATA just
    # because the LLM picked that label -- Phase 4 spec: "a document-
    # grounded statement must not be labelled VERIFIED_FROM_DATA."
    document_store = _document_store(tmp_path)
    search_result = document_store.retrieve("supply disruption", top_k=1)[0]
    chunk_id = search_result.chunk.id

    search_call = ToolCall(id="call_1", name="search_documents", input={"query": "supply disruption"})
    turn1 = LLMTurn(text=None, tool_calls=[search_call], stop_reason="tool_use")
    turn2 = LLMTurn(text="Found the relevant passage.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": "Management cites a supply disruption.",
            "key_findings": [
                {
                    "text": "Management attributes the Q2 revenue decline to a regional supply disruption.",
                    "label": "VERIFIED_FROM_DATA",  # mislabeled -- this is a document paraphrase, not a calculated fact
                    "citations": [{"document_id": "doc1", "chunk_id": chunk_id}],
                }
            ],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn3 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2, turn3])
    answer = run_agent(
        question="What does management say caused the decline?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=document_store,
        memory=ConversationMemory(),
    )

    assert answer.key_findings[0].label == "DOCUMENT_EVIDENCE"
    assert "reclassified" in answer.key_findings[0].verification_note.lower()


def test_run_agent_does_not_reclassify_a_genuinely_numeric_verified_from_data_claim(tmp_path):
    # Sanity check the reclassification fix doesn't fire on real calculated
    # claims just because a document happens to also be cited alongside them.
    tool_call = ToolCall(
        id="call_1", name="calculate_metric",
        input={"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum"},
    )
    turn1 = LLMTurn(text=None, tool_calls=[tool_call], stop_reason="tool_use")
    turn2 = LLMTurn(text="Calculated total sales.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {
            "executive_summary": f"Total sales were {TOTAL_AMOUNT}.",
            "key_findings": [{"text": f"Total sales were {TOTAL_AMOUNT}.", "label": "VERIFIED_FROM_DATA", "citations": []}],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn3 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")

    llm = FakeLLMProvider([turn1, turn2, turn3])
    answer = run_agent(
        question="What were total sales?", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(),
    )

    assert answer.key_findings[0].label == "VERIFIED_FROM_DATA"
    assert answer.key_findings[0].verification_note is None


def test_run_agent_caps_tool_iterations(tmp_path):
    # Every scripted turn keeps requesting another tool call -- the loop
    # must stop at max_iterations rather than looping forever.
    turns = [
        LLMTurn(
            text=None,
            tool_calls=[ToolCall(id=f"call_{i}", name="calculate_metric", input={"dataset_id": "orders", "aggregation": "count"})],
            stop_reason="tool_use",
        )
        for i in range(10)
    ]
    llm = FakeLLMProvider(turns)
    answer = run_agent(
        question="Keep going forever", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path),
        memory=ConversationMemory(), max_iterations=3,
    )
    assert len(answer.tool_invocations) == 3
    assert answer.configured is True


def test_run_agent_persists_conversation_memory(tmp_path):
    turn1 = LLMTurn(text="Answering directly.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "North region led revenue.", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    llm = FakeLLMProvider([turn1, turn2])
    memory = ConversationMemory()

    answer = run_agent(
        question="Show revenue by region.", session_id="s1", llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path), memory=memory,
    )

    assert memory.get_history("s1")
    assert "Show revenue by region." in memory.format_for_prompt("s1")
    assert answer.session_id == "s1"
