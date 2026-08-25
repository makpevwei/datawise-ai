"""Analysis sessions/messages survive navigation and can be restored --
Phase 4 continuation sections 14-17, 30, 49. Uses a fake LLM (no real API
calls) through the real /agent/ask and /analysis/run endpoints, against
the real DataWise database.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.memory import ConversationMemory
from app.ai.types import LLMTurn
from app.api.deps import (
    get_conversation_memory,
    get_dataset_store,
    get_llm_provider,
    get_scoped_dataset_store,
)
from app.auth.dependencies import get_current_user
from app.main import app
from app.semantic.store import DatasetStore
from tests.factories import orders_df, to_csv_bytes
from tests.fakes import FakeLLMProvider


@pytest.fixture
def client(tmp_path, auth_override):
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_scoped_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()
    app.dependency_overrides[get_current_user] = auth_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _scripted_llm() -> FakeLLMProvider:
    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="No tools needed.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "Total revenue was strong.", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    return FakeLLMProvider([route_turn, turn1, turn2])


def test_ask_creates_a_session_and_it_can_be_restored(client):
    app.dependency_overrides[get_llm_provider] = lambda: _scripted_llm()

    ask = client.post("/api/v1/agent/ask", json={"question": "How did we do?"})
    assert ask.status_code == 200
    body = ask.json()
    session_id = body["session_id"]
    assert body["message_id"]

    restored = client.get(f"/api/v1/sessions/{session_id}")
    assert restored.status_code == 200
    detail = restored.json()
    assert detail["message_count"] == 2  # user question + assistant answer
    assert any(m["role"] == "assistant" and m["metadata"].get("executive_summary") == "Total revenue was strong." for m in detail["messages"])


def test_asking_again_with_the_same_session_id_appends_to_it(client):
    app.dependency_overrides[get_llm_provider] = lambda: _scripted_llm()
    first = client.post("/api/v1/agent/ask", json={"question": "First question."})
    session_id = first.json()["session_id"]

    app.dependency_overrides[get_llm_provider] = lambda: _scripted_llm()
    second = client.post("/api/v1/agent/ask", json={"question": "Second question.", "session_id": session_id})
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id

    detail = client.get(f"/api/v1/sessions/{session_id}").json()
    assert detail["message_count"] == 4


def test_sessions_list_shows_recent_activity_and_survives_a_fresh_client(client):
    app.dependency_overrides[get_llm_provider] = lambda: _scripted_llm()
    ask = client.post("/api/v1/agent/ask", json={"question": "Track this analysis."})
    session_id = ask.json()["session_id"]

    # Simulate "navigating away and back" -- a brand-new TestClient, same auth.
    fresh = TestClient(app)
    listing = fresh.get("/api/v1/sessions")
    assert listing.status_code == 200
    assert any(s["id"] == session_id for s in listing.json())


def test_analysis_workspace_run_persists_when_session_id_given(client):
    files = [("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))]
    upload = client.post("/api/v1/datasets/upload", files=files)
    dataset_id = upload.json()["datasets"][0]["id"]

    session = client.post("/api/v1/sessions", json={"title": "Workspace analysis"})
    session_id = session.json()["id"]

    run = client.post(
        "/api/v1/analysis/run",
        json={"dataset_id": dataset_id, "metric_column": "amount", "aggregation": "sum", "session_id": session_id},
    )
    assert run.status_code == 200

    detail = client.get(f"/api/v1/sessions/{session_id}").json()
    assert detail["message_count"] == 1
    assert detail["messages"][0]["kind"] == "analysis_run"


def test_analysis_workspace_run_without_session_id_does_not_persist(client):
    files = [("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))]
    upload = client.post("/api/v1/datasets/upload", files=files)
    dataset_id = upload.json()["datasets"][0]["id"]

    run = client.post(
        "/api/v1/analysis/run",
        json={"dataset_id": dataset_id, "metric_column": "amount", "aggregation": "sum"},
    )
    assert run.status_code == 200

    sessions = client.get("/api/v1/sessions").json()
    assert sessions == []


def test_delete_session_removes_it(client):
    app.dependency_overrides[get_llm_provider] = lambda: _scripted_llm()
    ask = client.post("/api/v1/agent/ask", json={"question": "Temporary."})
    session_id = ask.json()["session_id"]

    delete = client.delete(f"/api/v1/sessions/{session_id}")
    assert delete.status_code == 204

    get = client.get(f"/api/v1/sessions/{session_id}")
    assert get.status_code == 404
