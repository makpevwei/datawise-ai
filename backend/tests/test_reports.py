"""Report creation/retrieval/delete, end-to-end through the real filesystem
paths -- regression coverage for a real bug found during browser testing:
storage_reference was computed relative to backend/, but reports_dir
("../data/reports") actually lives one level above backend/, so every
report file's path fell outside that base and `Path.relative_to()` raised
ValueError (surfaced to the browser as an opaque CORS/network failure,
since the 500 response never got the chance to carry CORS headers).
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.memory import ConversationMemory
from app.ai.types import LLMTurn
from app.api.deps import get_conversation_memory, get_dataset_store, get_llm_provider, get_scoped_dataset_store
from app.auth.dependencies import get_current_user
from app.main import app
from app.semantic.store import DatasetStore
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


def _ask_and_get_message_id(client) -> str:
    route_turn = LLMTurn(text="DATA_ONLY", tool_calls=[], stop_reason="end_turn")
    turn1 = LLMTurn(text="direct answer", tool_calls=[], stop_reason="end_turn")
    synthesis = json.dumps(
        {"executive_summary": "Revenue was strong.", "key_findings": [{"text": "Revenue was strong.", "label": "AI_INTERPRETATION", "citations": []}], "risks": [], "recommendations": [], "claim_comparisons": [], "chart_tool_call_ids": []}
    )
    turn2 = LLMTurn(text=synthesis, tool_calls=[], stop_reason="end_turn")
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider([route_turn, turn1, turn2])

    ask = client.post("/api/v1/agent/ask", json={"question": "How did we do?"})
    assert ask.status_code == 200
    message_id = ask.json()["message_id"]
    assert message_id
    return message_id


def test_report_create_get_delete_round_trips_through_the_real_filesystem(client):
    message_id = _ask_and_get_message_id(client)

    create = client.post("/api/v1/reports", json={"message_id": message_id, "title": "Q1 Report"})
    assert create.status_code == 201, create.text
    report = create.json()
    assert report["title"] == "Q1 Report"

    listing = client.get("/api/v1/reports")
    assert listing.status_code == 200
    assert any(r["id"] == report["id"] for r in listing.json())

    get = client.get(f"/api/v1/reports/{report['id']}")
    assert get.status_code == 200
    assert get.headers["content-type"] == "application/pdf"
    assert get.content[:4] == b"%PDF"

    delete = client.delete(f"/api/v1/reports/{report['id']}")
    assert delete.status_code == 204

    get_after_delete = client.get(f"/api/v1/reports/{report['id']}")
    assert get_after_delete.status_code == 404


def test_storage_reference_is_relative_to_the_project_root_not_backend(client):
    """The specific regression: storage_reference must resolve to a real
    file when joined with the project root, proving the path fix."""
    from pathlib import Path

    message_id = _ask_and_get_message_id(client)
    create = client.post("/api/v1/reports", json={"message_id": message_id, "title": "Path check"})
    assert create.status_code == 201

    from app.db.models import Report
    from app.db.session import get_session_factory

    db = get_session_factory()()
    row = db.get(Report, create.json()["id"])
    project_root = Path(__file__).resolve().parents[2]
    resolved_path = project_root / row.storage_reference
    assert resolved_path.exists()
    assert resolved_path.suffix == ".pdf"
    db.close()


def test_creating_a_report_from_someone_elses_message_is_rejected(client, fake_user):
    from app.db.models import AnalysisSession, Message, User
    from app.db.session import get_session_factory

    db = get_session_factory()()
    other_user = User(email=f"other-{fake_user.id}@example.com", password_hash="x", full_name="Other")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    session = AnalysisSession(user_id=other_user.id, title="Not yours")
    db.add(session)
    db.commit()
    db.refresh(session)

    message = Message(session_id=session.id, role="assistant", kind="agent_answer", content="secret", message_metadata={})
    db.add(message)
    db.commit()
    db.refresh(message)

    try:
        response = client.post("/api/v1/reports", json={"message_id": message.id, "title": "Should fail"})
        assert response.status_code == 404
    finally:
        db.delete(other_user)
        db.commit()
        db.close()
