"""Phase 3A additions to the planner: llm_metadata surfaces on AgentAnswer,
and running through the gateway changes nothing about Phase 3's
verification guarantee -- the LLM still never gets to assert an unverified
number as fact."""

import json

from app.agent.memory import ConversationMemory
from app.agent.planner import run_agent
from app.ai.errors import PermanentLLMError
from app.ai.gateway import LLMGateway
from app.ai.types import LLMCallMetadata, LLMTurn, ToolCall
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore
from tests.factories import orders_df
from tests.fakes import FakeLLMProvider, FakeLLMProviderWithTransientBlip, FakeRaisingProvider


def _dataset_store(tmp_path) -> DatasetStore:
    store = DatasetStore(storage_dir=tmp_path / "datasets")
    orders = orders_df(20)
    store.put("orders", orders, profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
    return store


def _document_store(tmp_path) -> DocumentStore:
    return DocumentStore(storage_dir=tmp_path / "documents")


def test_agent_answer_carries_llm_metadata_from_scripted_turn(tmp_path):
    turn1 = LLMTurn(text="Answering directly.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(
        text=synthesis,
        tool_calls=[],
        stop_reason="end_turn",
        metadata=LLMCallMetadata(provider="openai", model="gpt-4o-mini", fallback_used=False, attempt_count=1, latency_ms=42),
    )
    llm = FakeLLMProvider([turn1, turn2])

    answer = run_agent(
        question="Show revenue.", session_id=None, llm=llm,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path), memory=ConversationMemory(),
    )

    assert answer.llm_metadata is not None
    assert answer.llm_metadata.provider == "openai"
    assert answer.llm_metadata.model == "gpt-4o-mini"
    assert answer.llm_metadata.fallback_used is False


def test_gateway_fallback_metadata_reaches_the_final_answer(tmp_path):
    # Primary provider is permanently down for every call; the gateway
    # fails over to a second (scripted) provider each time -- the final
    # answer's llm_metadata must report fallback_used=True, proving the
    # gateway integration is visible end-to-end, not just at the app/ai
    # layer. A real LLMGateway wraps: [always-failing primary, scripted
    # fallback] -- both the main-loop turn and the synthesis turn go
    # through the same gateway instance.
    synthesis = json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    primary = FakeRaisingProvider("openai", to_raise=[PermanentLLMError("bad key")] * 5)
    fallback = FakeLLMProvider(
        [
            LLMTurn(text="Answering directly.", tool_calls=[], stop_reason="end_turn"),
            LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn"),
        ]
    )
    gateway = LLMGateway(providers=[primary, fallback], max_retries=0)

    answer = run_agent(
        question="Show revenue.", session_id=None, llm=gateway,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path), memory=ConversationMemory(),
    )

    assert answer.llm_metadata is not None
    assert answer.llm_metadata.fallback_used is True
    assert answer.llm_metadata.provider == fallback.provider_name


def test_fabricated_number_from_llm_is_still_downgraded_through_gateway(tmp_path):
    # Repeats Phase 3's verification guarantee (test_planner.py::
    # test_run_agent_downgrades_unsupported_numeric_claim) but driven
    # through an LLMGateway wrapping a raising-capable fake, to prove
    # Phase 3A's retry/fallback plumbing doesn't bypass verification.
    tool_call = ToolCall(
        id="call_1", name="calculate_metric",
        input={"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum"},
    )
    turn1 = LLMTurn(text=None, tool_calls=[tool_call], stop_reason="tool_use")
    turn2 = LLMTurn(text="Calculated total sales.", tool_calls=[], stop_reason="end_turn")
    fabricated_synthesis = json.dumps(
        {
            "executive_summary": "Total sales were 999999.",
            "key_findings": [{"text": "Total sales were 999999.", "label": "VERIFIED_FROM_DATA", "citations": []}],
            "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": [],
        }
    )
    turn3 = LLMTurn(text=fabricated_synthesis, tool_calls=[], stop_reason="end_turn")

    # Primary is transiently down for the first attempt of every call but
    # succeeds on retry (max_retries=1); real LLMGateway retry logic sits
    # in front of the same scripted provider the non-gateway test uses.
    primary = FakeLLMProviderWithTransientBlip([turn1, turn2, turn3])
    gateway = LLMGateway(providers=[primary], max_retries=1)

    answer = run_agent(
        question="What were total sales?", session_id=None, llm=gateway,
        dataset_store=_dataset_store(tmp_path), document_store=_document_store(tmp_path), memory=ConversationMemory(),
    )

    assert answer.key_findings[0].label == "AI_INTERPRETATION"
    assert answer.key_findings[0].verification_note is not None
