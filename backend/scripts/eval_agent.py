"""Phase 3 accuracy evaluation harness.

Runs a fixed set of real business questions against the actual agent
endpoint, using whatever LLM is configured in the real .env (never
mocked). Uploads the real sample datasets plus one synthetic test
document created solely for RAG evaluation (see tests/eval_fixtures/).

Never prints the API key. Writes raw results to eval_results.json next
to this script for manual grading into docs/evaluation.md -- grading an
open-ended agent answer is not something this script does automatically.

Dataset/document storage is overridden to a throwaway temp directory so
this run never mixes with (or pollutes) the app's real persisted
data/uploads and data/documents -- only the real LLM call is live.

Usage: uv run python scripts/eval_agent.py
"""

import json
import tempfile
import time
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
OUTPUT_PATH = Path(__file__).resolve().parent / "eval_results.json"

QUESTIONS = [
    # 1. simple aggregation
    {"id": 1, "category": "simple_aggregation", "question": "What was the total price across all orders?"},
    {"id": 2, "category": "simple_aggregation", "question": "What is the average order price?"},
    # 2. filtering
    {"id": 3, "category": "filtering", "question": "What is the total price for orders paid by CASH?"},
    {"id": 4, "category": "filtering", "question": "How many orders had a late delivery risk?"},
    # 3. ranking
    {"id": 5, "category": "ranking", "question": "Which region generated the most total price?"},
    {"id": 6, "category": "ranking", "question": "Which shipping mode is used the most?"},
    # 4. joins
    {"id": 7, "category": "joins", "question": "Which product category generated the most revenue, joining orders with products?"},
    {"id": 8, "category": "joins", "question": "Which customer segment placed the most orders, joining orders with customers?"},
    # 5. time comparison
    {"id": 9, "category": "time_comparison", "question": "Compare total price between 2023-01 and 2023-02."},
    {"id": 10, "category": "time_comparison", "question": "Show me the monthly trend of order price over time."},
    # 6. anomaly detection
    {"id": 11, "category": "anomaly_detection", "question": "Are there any unusual or anomalous values in the order price column?"},
    {"id": 12, "category": "anomaly_detection", "question": "Detect anomalies in the cost column of the orders dataset."},
    # 7. multi-dataset analysis
    {"id": 13, "category": "multi_dataset", "question": "What relationships exist between the uploaded datasets?"},
    {"id": 14, "category": "multi_dataset", "question": "List the datasets currently available and how many rows each has."},
    # 8. chart generation
    {"id": 15, "category": "chart_generation", "question": "Create a chart showing total price by region."},
    {"id": 16, "category": "chart_generation", "question": "Build a small dashboard for the orders dataset."},
    # 9. insufficient-data questions
    {"id": 17, "category": "insufficient_data", "question": "What was our total profit margin in Japanese yen last decade?"},
    {"id": 18, "category": "insufficient_data", "question": "How many customers churned last year?"},
    # 10. document retrieval
    {"id": 19, "category": "document_retrieval", "question": "According to the management commentary, why did the West Africa region underperform?"},
    {"id": 20, "category": "document_retrieval", "question": "What risk did management flag regarding shipping?"},
    # 11. cross-document/data reasoning
    {"id": 21, "category": "cross_data_document", "question": "Management says West Africa underperformed due to slower Standard Class fulfillment. Does the order data support this explanation?"},
    {"id": 22, "category": "cross_data_document", "question": "Management says Footwear is the strongest category by order volume. Does the data support this?"},
    # 12. conversational memory -- an explicit chained mini-conversation
    # (all other questions above run in their own fresh session so their
    # results aren't contaminated by unrelated prior context).
    {"id": 23, "category": "conversational_memory", "chain": False, "question": "Show total price by region."},
    {"id": 24, "category": "conversational_memory", "chain": True, "question": "Now show only the top 2."},
    {"id": 25, "category": "conversational_memory", "chain": True, "question": "What about broken down by shipping mode instead?"},
]


def _upload_datasets(client: TestClient) -> None:
    files = []
    for name in ("products.csv", "orders.csv", "customers.csv"):
        path = SAMPLES_DIR / name
        if path.exists():
            files.append(("files", (name, path.read_bytes(), "text/csv")))
    if not files:
        raise SystemExit(f"No sample datasets found in {SAMPLES_DIR}")
    response = client.post("/api/v1/datasets/upload", files=files)
    response.raise_for_status()
    print(f"Uploaded datasets: {[d['name'] for d in response.json()['datasets']]}")


def _upload_document(client: TestClient) -> None:
    files = [("files", (FIXTURE_DOC.name, FIXTURE_DOC.read_bytes(), "text/markdown"))]
    response = client.post("/api/v1/documents/upload", files=files)
    response.raise_for_status()
    print(f"Uploaded documents: {[d['filename'] for d in response.json()['documents']]}")


def main() -> None:
    if not is_llm_configured():
        raise SystemExit(
            "LLM_PROVIDER/LLM_API_KEY are not configured in .env -- cannot run a real-LLM evaluation."
        )

    tmp_dir = tempfile.mkdtemp(prefix="datawise-eval-")
    dataset_store = DatasetStore(storage_dir=Path(tmp_dir) / "datasets")
    document_store = DocumentStore(storage_dir=Path(tmp_dir) / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()
    # get_llm_provider is intentionally NOT overridden -- this is the one
    # real, live dependency for this run.

    client = TestClient(app)
    _upload_datasets(client)
    _upload_document(client)

    results = []
    chain_session_id = None
    for item in QUESTIONS:
        session_id = chain_session_id if item.get("chain") else None
        start = time.monotonic()
        error = None
        answer = None
        try:
            response = client.post(
                "/api/v1/agent/ask",
                json={"question": item["question"], "session_id": session_id},
                timeout=120,
            )
            response.raise_for_status()
            answer = response.json()
            if item["category"] == "conversational_memory":
                chain_session_id = answer["session_id"]
        except Exception as exc:  # noqa: BLE001 -- record and continue, never abort the run
            error = str(exc)
        latency_ms = int((time.monotonic() - start) * 1000)

        record = {
            "id": item["id"],
            "category": item["category"],
            "question": item["question"],
            "latency_ms": latency_ms,
            "error": error,
        }
        if answer:
            record.update(
                {
                    "configured": answer.get("configured"),
                    "agent_error": answer.get("error"),
                    "executive_summary": answer.get("executive_summary"),
                    "key_findings": answer.get("key_findings"),
                    "claim_comparisons": answer.get("claim_comparisons"),
                    "citations": answer.get("citations"),
                    "tool_calls": [t["tool_name"] for t in answer.get("tool_invocations", [])],
                }
            )
        results.append(record)
        print(f"[{item['id']:2d}] {item['category']:22s} {latency_ms:6d}ms  {item['question'][:60]}")

    OUTPUT_PATH.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {len(results)} results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
