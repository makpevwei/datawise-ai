"""Targeted retest of eval questions 7-9 -- Q8 and Q9 failed in the full
Phase 4 run where the Phase 3 baseline succeeded on the same questions.
This checks whether that was reproducible (a real regression) or one-off
LLM stochasticity, by re-running the same 3-question sequence (shared
dataset store, same order, matching the original harness) fresh.
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

QUESTIONS = [
    {"id": 7, "question": "Which product category generated the most revenue, joining orders with products?"},
    {"id": 8, "question": "Which customer segment placed the most orders, joining orders with customers?"},
    {"id": 9, "question": "Compare total price between 2023-01 and 2023-02."},
]


def main() -> None:
    if not is_llm_configured():
        raise SystemExit("LLM not configured.")

    tmp_dir = tempfile.mkdtemp(prefix="datawise-retest79-")
    dataset_store = DatasetStore(storage_dir=Path(tmp_dir) / "datasets")
    document_store = DocumentStore(storage_dir=Path(tmp_dir) / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()

    client = TestClient(app)
    files = [("files", (name, (SAMPLES_DIR / name).read_bytes(), "text/csv")) for name in ("products.csv", "orders.csv", "customers.csv")]
    client.post("/api/v1/datasets/upload", files=files).raise_for_status()

    results = []
    for item in QUESTIONS:
        response = client.post("/api/v1/agent/ask", json={"question": item["question"]}, timeout=120)
        response.raise_for_status()
        answer = response.json()
        results.append(
            {
                "id": item["id"],
                "question": item["question"],
                "configured": answer.get("configured"),
                "error": answer.get("error"),
                "executive_summary": answer.get("executive_summary"),
                "key_findings": answer.get("key_findings"),
                "tool_calls": [t["tool_name"] for t in answer.get("tool_invocations", [])],
            }
        )
        print(json.dumps(results[-1], indent=2))

    Path(__file__).resolve().parent.joinpath("eval_retest_7_9_results.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
