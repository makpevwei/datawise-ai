"""The LLM must never see raw dataset rows -- only schemas, summaries, and
calculated results. These tests use a dataset with many rows to prove the
size of what's sent to the model doesn't scale with row count.
"""

import pandas as pd

from app.agent.planner import _build_system_prompt, _format_datasets
from app.agent.tools import TOOLS, ToolContext
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore

# The static instructional portion of the prompt (question-type
# classification, chart-selection guidance, tool usage rules, etc.) has
# grown across phases as real guidance was added -- this bound exists to
# catch the prompt scaling with *data volume*, not to cap legitimate
# instructional content. The real safety property is the relative-growth
# assertion below (large vs. small dataset), not this absolute number.
MAX_REASONABLE_SYSTEM_PROMPT_CHARS = 8000


def _big_dataset_store(tmp_path, n_rows: int) -> DatasetStore:
    store = DatasetStore(storage_dir=tmp_path / "datasets")
    df = pd.DataFrame(
        {
            "order_id": range(1, n_rows + 1),
            "amount": [10.0 + (i % 97) for i in range(n_rows)],
            "region": [["North", "South", "East", "West"][i % 4] for i in range(n_rows)],
        }
    )
    store.put("orders", df, profile_dataframe(df, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
    return store


def test_system_prompt_size_does_not_scale_with_row_count(tmp_path):
    small_store = _big_dataset_store(tmp_path / "small", 100)
    large_store = _big_dataset_store(tmp_path / "large", 50_000)

    prompt_small = _build_system_prompt(small_store, DocumentStore(storage_dir=tmp_path / "docs1"), None)
    prompt_large = _build_system_prompt(large_store, DocumentStore(storage_dir=tmp_path / "docs2"), None)

    assert len(prompt_small) < MAX_REASONABLE_SYSTEM_PROMPT_CHARS
    assert len(prompt_large) < MAX_REASONABLE_SYSTEM_PROMPT_CHARS
    # The 500x row-count difference must not meaningfully change prompt size.
    assert abs(len(prompt_large) - len(prompt_small)) < 200


def test_dataset_summary_in_prompt_has_no_row_level_data(tmp_path):
    store = _big_dataset_store(tmp_path, 50_000)
    formatted = _format_datasets(store)
    # Only counts and identifiers -- never actual cell values.
    assert "10.0" not in formatted
    assert "North" not in formatted
    assert "row_count=50000" in formatted or "rows=50000" in formatted


def test_inspect_dataset_tool_returns_profile_not_rows(tmp_path):
    dataset_store = _big_dataset_store(tmp_path, 50_000)
    document_store = DocumentStore(storage_dir=tmp_path / "docs2")
    ctx = ToolContext(dataset_store=dataset_store, document_store=document_store)

    result = TOOLS["inspect_dataset"].handler({"dataset_id": "orders"}, ctx)
    # A profile is compact regardless of dataset size -- column stats only.
    assert len(str(result)) < 20_000
    assert "row_count" in result


def test_calculate_metric_tool_output_is_a_scalar_not_a_dump(tmp_path):
    dataset_store = _big_dataset_store(tmp_path, 50_000)
    document_store = DocumentStore(storage_dir=tmp_path / "docs3")
    ctx = ToolContext(dataset_store=dataset_store, document_store=document_store)

    result = TOOLS["calculate_metric"].handler(
        {"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum"}, ctx
    )
    assert isinstance(result["scalar_value"], float)
    assert len(str(result)) < 2000
