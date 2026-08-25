"""Targeted retest of eval question 19 -- confirms the DOCUMENT_EVIDENCE
mislabeling fix (app/agent/planner._build_finding's reclassification logic)
actually reclassifies a real live LLM's mislabeled output, not just the
scripted unit test."""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.memory import ConversationMemory
from app.ai.client import is_llm_configured
from app.api.deps import get_conversation_memory, get_dataset_store, get_document_store
from app.documents.store import DocumentStore
from app.main import app
from app.semantic.store import DatasetStore

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "data" / "samples"
FIXTURE_DOC = BACKEND_DIR / "tests" / "eval_fixtures" / "management_commentary.md"


def main() -> None:
    if not is_llm_configured():
        raise SystemExit("LLM not configured.")

    tmp_dir = tempfile.mkdtemp(prefix="datawise-retest19-")
    dataset_store = DatasetStore(storage_dir=Path(tmp_dir) / "datasets")
    document_store = DocumentStore(storage_dir=Path(tmp_dir) / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()

    client = TestClient(app)
    files = [("files", (name, (SAMPLES_DIR / name).read_bytes(), "text/csv")) for name in ("products.csv", "orders.csv", "customers.csv")]
    client.post("/api/v1/datasets/upload", files=files).raise_for_status()
    client.post("/api/v1/documents/upload", files=[("files", (FIXTURE_DOC.name, FIXTURE_DOC.read_bytes(), "text/markdown"))]).raise_for_status()

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "According to the management commentary, why did the West Africa region underperform?"},
        timeout=120,
    )
    response.raise_for_status()
    answer = response.json()
    print(json.dumps({"key_findings": answer.get("key_findings"), "tool_calls": [t["tool_name"] for t in answer.get("tool_invocations", [])]}, indent=2))


if __name__ == "__main__":
    main()
