"""Targeted retest of eval questions 21-22 (cross_data_document) after
strengthening the system prompt's "must call search_documents even if the
claim is already stated in the question" instruction. Real LLM, real
sample data -- same harness pattern as eval_agent.py, scoped to just these
two questions so the retest is fast and cheap.
"""

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

QUESTIONS = [
    {"id": 21, "question": "Management says West Africa underperformed due to slower Standard Class fulfillment. Does the order data support this explanation?"},
    {"id": 22, "question": "Management says Footwear is the strongest category by order volume. Does the data support this?"},
]


def main() -> None:
    if not is_llm_configured():
        raise SystemExit("LLM not configured.")

    tmp_dir = tempfile.mkdtemp(prefix="datawise-retest-")
    dataset_store = DatasetStore(storage_dir=Path(tmp_dir) / "datasets")
    document_store = DocumentStore(storage_dir=Path(tmp_dir) / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()

    client = TestClient(app)
    files = [("files", (name, (SAMPLES_DIR / name).read_bytes(), "text/csv")) for name in ("products.csv", "orders.csv", "customers.csv")]
    client.post("/api/v1/datasets/upload", files=files).raise_for_status()
    client.post("/api/v1/documents/upload", files=[("files", (FIXTURE_DOC.name, FIXTURE_DOC.read_bytes(), "text/markdown"))]).raise_for_status()

    results = []
    for item in QUESTIONS:
        response = client.post("/api/v1/agent/ask", json={"question": item["question"]}, timeout=120)
        response.raise_for_status()
        answer = response.json()
        results.append(
            {
                "id": item["id"],
                "question": item["question"],
                "executive_summary": answer.get("executive_summary"),
                "claim_comparisons": answer.get("claim_comparisons"),
                "citations": answer.get("citations"),
                "tool_calls": [t["tool_name"] for t in answer.get("tool_invocations", [])],
            }
        )
        print(json.dumps(results[-1], indent=2))

    Path(__file__).resolve().parent.joinpath("eval_retest_21_22_results.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
