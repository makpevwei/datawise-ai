import json

import pytest
from fastapi.testclient import TestClient

from app.agent.memory import ConversationMemory
from app.ai.types import LLMTurn
from app.api.deps import (
    get_conversation_memory,
    get_dataset_store,
    get_document_store,
    get_llm_provider,
    get_scoped_dataset_store,
    get_scoped_document_store,
)
from app.api.scoped_stores import ScopedDatasetStore
from app.auth.dependencies import get_current_user
from app.documents.store import DocumentStore
from app.main import app
from app.semantic.store import DatasetStore
from tests.factories import customers_df, orders_df, to_csv_bytes
from tests.fakes import FakeLLMProvider


@pytest.fixture
def client(tmp_path, auth_override):
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")
    memory = ConversationMemory()

    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store
    app.dependency_overrides[get_scoped_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_scoped_document_store] = lambda: document_store
    app.dependency_overrides[get_conversation_memory] = lambda: memory
    app.dependency_overrides[get_llm_provider] = lambda: None
    app.dependency_overrides[get_current_user] = auth_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_agent_status_reports_unconfigured_by_default(client):
    response = client.get("/api/v1/agent/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_ask_without_llm_returns_honest_message(client):
    response = client.post("/api/v1/agent/ask", json={"question": "What were total sales?"})
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert "not configured" in body["error"].lower()


def test_ask_with_fake_llm_runs_full_loop(client, tmp_path):
    files = [("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))]
    client.post("/api/v1/datasets/upload", files=files)

    # /ask now goes through the LangGraph router first (app/agent/graph.py),
    # which makes its own llm.send() call before the agent loop -- one
    # extra scripted turn up front.
    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="No tools needed.", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "Summary.", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider([route_turn, turn1, turn2])

    response = client.post("/api/v1/agent/ask", json={"question": "Summarize this."})
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["executive_summary"] == "Summary."


def test_ask_with_dataset_ids_scopes_the_agent_to_only_those_datasets(client, tmp_path):
    """Ask DataWise's dataset-selection UI sends dataset_ids to narrow what
    the agent even sees (app/api/agent.py's ScopedDatasetStore.narrowed()
    call). Proven here by inspecting the system prompt the fake LLM
    actually received -- it must list only the selected dataset."""
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store

    orders_upload = client.post(
        "/api/v1/datasets/upload", files=[("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))]
    )
    customers_upload = client.post(
        "/api/v1/datasets/upload", files=[("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    )
    orders_id = orders_upload.json()["datasets"][0]["id"]
    customers_id = customers_upload.json()["datasets"][0]["id"]

    all_ids = {orders_id, customers_id}
    app.dependency_overrides[get_scoped_dataset_store] = lambda: ScopedDatasetStore(
        _store=dataset_store, _owned_ids=all_ids
    )

    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    fake = FakeLLMProvider([route_turn, turn1, turn2])
    app.dependency_overrides[get_llm_provider] = lambda: fake

    response = client.post(
        "/api/v1/agent/ask", json={"question": "How are we doing?", "dataset_ids": [orders_id]}
    )
    assert response.status_code == 200

    # The second .send() call is the main agent-loop system prompt (the
    # first is the router's own prompt) -- it must list only orders.csv.
    main_system_prompt = fake.calls[1][0]
    assert "orders" in main_system_prompt
    assert "customers" not in main_system_prompt


def test_ask_with_a_dataset_id_the_user_does_not_own_is_silently_excluded(client, tmp_path):
    """narrowed() only ever intersects -- a forged/unowned id in dataset_ids
    must not leak that dataset into the agent's context."""
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store

    orders_upload = client.post(
        "/api/v1/datasets/upload", files=[("files", ("orders.csv", to_csv_bytes(orders_df()), "text/csv"))]
    )
    orders_id = orders_upload.json()["datasets"][0]["id"]

    # This user only owns 'orders' -- scoped store reflects that.
    app.dependency_overrides[get_scoped_dataset_store] = lambda: ScopedDatasetStore(
        _store=dataset_store, _owned_ids={orders_id}
    )

    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "ok", "key_findings": [], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    fake = FakeLLMProvider([route_turn, turn1, turn2])
    app.dependency_overrides[get_llm_provider] = lambda: fake

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "How are we doing?", "dataset_ids": [orders_id, "someone-elses-dataset-id"]},
    )
    assert response.status_code == 200
    main_system_prompt = fake.calls[1][0]
    assert "someone-elses-dataset-id" not in main_system_prompt


def test_export_pdf_returns_pdf_bytes(client):
    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "Total revenue was strong.", "key_findings": [{"text": "Total revenue was strong.", "label": "AI_INTERPRETATION", "citations": []}], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider([route_turn, turn1, turn2])

    ask_response = client.post("/api/v1/agent/ask", json={"question": "How did we do?"})
    answer = ask_response.json()

    export_response = client.post("/api/v1/agent/export/pdf", json=answer)
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/pdf"
    assert export_response.content[:4] == b"%PDF"


def test_upload_routes_csv_to_datasets_and_pdf_to_documents(client):
    dataset_files = [("files", ("customers.csv", to_csv_bytes(customers_df()), "text/csv"))]
    dataset_response = client.post("/api/v1/datasets/upload", files=dataset_files)
    assert dataset_response.status_code == 200
    assert len(dataset_response.json()["datasets"]) == 1

    document_files = [("files", ("notes.md", b"# Summary\nRevenue grew this quarter.\n", "text/markdown"))]
    document_response = client.post("/api/v1/documents/upload", files=document_files)
    assert document_response.status_code == 200
    body = document_response.json()
    assert len(body["documents"]) == 1
    assert body["documents"][0]["document_type"] == "md"


def test_list_documents(client):
    files = [("files", ("notes.txt", b"Just some notes.\n", "text/plain"))]
    client.post("/api/v1/documents/upload", files=files)
    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_document_upload_rejects_unsupported_extension(client):
    files = [("files", ("data.exe", b"binary junk", "application/octet-stream"))]
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] == []
    assert len(body["errors"]) == 1
