"""Debug retest of Q10 (monthly trend chart) -- prints full tool_invocation
output_summary text (not just tool names) so the actual generate_chart
error, if any, is visible."""

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


def main() -> None:
    if not is_llm_configured():
        raise SystemExit("LLM not configured.")

    tmp_dir = tempfile.mkdtemp(prefix="datawise-retest10dbg-")
    dataset_store = DatasetStore(storage_dir=Path(tmp_dir) / "datasets")
    document_store = DocumentStore(storage_dir=Path(tmp_dir) / "documents")
    app.dependency_overrides[get_dataset_store] = lambda: dataset_store
    app.dependency_overrides[get_document_store] = lambda: document_store
    app.dependency_overrides[get_conversation_memory] = lambda: ConversationMemory()

    client = TestClient(app)
    files = [("files", (name, (SAMPLES_DIR / name).read_bytes(), "text/csv")) for name in ("products.csv", "orders.csv", "customers.csv")]
    client.post("/api/v1/datasets/upload", files=files).raise_for_status()

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "Show me the monthly trend of order price over time."},
        timeout=120,
    )
    response.raise_for_status()
    answer = response.json()
    print("executive_summary:", answer.get("executive_summary"))
    print()
    for inv in answer.get("tool_invocations", []):
        print(f"--- {inv['tool_name']} succeeded={inv['succeeded']} ---")
        print("input:", json.dumps(inv["input"]))
        print("output:", inv["output_summary"][:600])
        print()


if __name__ == "__main__":
    main()
