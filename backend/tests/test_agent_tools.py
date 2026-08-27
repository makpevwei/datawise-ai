import pandas as pd
import pytest

from app.agent.tools import TOOLS, ToolContext, ToolExecutionError, verify_claim_tool
from app.documents.chunking import chunk_segments
from app.documents.extraction import Segment
from app.documents.models import ChunkLocation, DocumentSummary, DocumentType
from app.documents.store import DocumentStore
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetStore
from tests.factories import customers_df, orders_df


@pytest.fixture
def ctx(tmp_path):
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")

    customers = customers_df()
    orders = orders_df(20)
    dataset_store.put(
        "customers", customers,
        profile_dataframe(customers, "customers", "customers", "customers.csv", None, DatasetKind.UPLOADED),
    )
    dataset_store.put(
        "orders", orders,
        profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED),
    )

    segments = [Segment(text="Q2 revenue declined due to a supply disruption in the West region.", location=ChunkLocation(page=1))]
    chunks = chunk_segments(segments, document_id="doc1", document_name="report.pdf")
    document_store.put(
        DocumentSummary(
            id="doc1", filename="report.pdf", document_type=DocumentType.PDF,
            chunk_count=len(chunks), char_count=sum(len(c.text) for c in chunks),
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ),
        chunks,
    )

    return ToolContext(dataset_store=dataset_store, document_store=document_store)


def test_list_datasets_returns_summaries_not_raw_rows(ctx):
    result = TOOLS["list_datasets"].handler({}, ctx)
    names = {d["name"] for d in result["datasets"]}
    assert names == {"customers", "orders"}
    assert "row_count" in result["datasets"][0]
    assert not any("dataframe" in d or "rows" in d for d in result["datasets"])


def test_inspect_dataset_returns_profile(ctx):
    result = TOOLS["inspect_dataset"].handler({"dataset_id": "orders"}, ctx)
    assert result["row_count"] == 20
    assert any(c["name"] == "amount" for c in result["columns"])


def test_inspect_dataset_missing_id_raises(ctx):
    with pytest.raises(ToolExecutionError):
        TOOLS["inspect_dataset"].handler({"dataset_id": "does-not-exist"}, ctx)


def test_inspect_schema_is_lighter_than_inspect_dataset(ctx):
    schema = TOOLS["inspect_schema"].handler({"dataset_id": "orders"}, ctx)
    full = TOOLS["inspect_dataset"].handler({"dataset_id": "orders"}, ctx)
    assert len(str(schema)) < len(str(full))
    assert schema["columns"][0].keys() == {"name", "type", "missing_percentage"}


UUID_ID = "a5d40658900440f1b76f4d55c2748267"


@pytest.fixture
def ctx_with_uuid_id(tmp_path):
    # Mirrors the real system: the dataset's actual id (what tools must be
    # called with) is a random string, distinct from its display name
    # (what a real LLM sometimes uses instead -- see
    # _resolve_dataset_id's docstring for why that must still work). A
    # fresh store (not the shared 'ctx' fixture) so there's no other
    # "orders"-stemmed dataset to collide with.
    dataset_store = DatasetStore(storage_dir=tmp_path / "datasets")
    document_store = DocumentStore(storage_dir=tmp_path / "documents")
    df = orders_df(10)
    dataset_store.put(
        UUID_ID, df,
        profile_dataframe(df, UUID_ID, "shipments.csv", "shipments.csv", None, DatasetKind.UPLOADED),
    )
    return ToolContext(dataset_store=dataset_store, document_store=document_store)


def test_tool_call_with_dataset_name_instead_of_id_still_resolves(ctx_with_uuid_id):
    # The exact bug observed live: an LLM calling a tool with the display
    # name ("shipments.csv") rather than the real id must not fail outright.
    result = TOOLS["inspect_schema"].handler({"dataset_id": "shipments.csv"}, ctx_with_uuid_id)
    assert result["dataset_id"] == UUID_ID


def test_tool_call_with_dataset_name_without_extension_still_resolves(ctx_with_uuid_id):
    result = TOOLS["inspect_schema"].handler({"dataset_id": "shipments"}, ctx_with_uuid_id)
    assert result["dataset_id"] == UUID_ID


def test_group_and_aggregate_resolves_dataset_by_name_and_computes_the_real_analysis(ctx_with_uuid_id):
    result = TOOLS["group_and_aggregate"].handler(
        {"dataset_id": "shipments.csv", "metric_column": "amount", "aggregation": "sum", "dimension_column": "region"},
        ctx_with_uuid_id,
    )
    assert result["request"]["dataset_id"] == UUID_ID
    assert result["result_type"] == "table"


def test_generate_dashboard_resolves_dataset_by_name(ctx_with_uuid_id):
    result = TOOLS["generate_dashboard"].handler({"dataset_id": "shipments.csv"}, ctx_with_uuid_id)
    assert result["dataset_id"] == UUID_ID


def test_unknown_dataset_name_still_raises_with_a_helpful_message(ctx_with_uuid_id):
    with pytest.raises(ToolExecutionError) as exc_info:
        TOOLS["inspect_dataset"].handler({"dataset_id": "nonexistent.csv"}, ctx_with_uuid_id)
    assert "shipments.csv" in str(exc_info.value)


def test_find_relationships_detects_customer_id(ctx):
    result = TOOLS["find_relationships"].handler({}, ctx)
    assert any(r["left_column"] == "customer_id" or r["right_column"] == "customer_id" for r in result["relationships"])


def test_join_datasets_produces_new_dataset(ctx):
    result = TOOLS["join_datasets"].handler(
        {"left_dataset_id": "orders", "left_column": "customer_id", "right_dataset_id": "customers", "right_column": "customer_id"},
        ctx,
    )
    assert result["rows_after"] == 20
    assert result["join_type"] == "inner"


def test_calculate_metric_sums_correctly(ctx):
    result = TOOLS["calculate_metric"].handler({"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum"}, ctx)
    expected = sum(100.0 + i * 10 for i in range(1, 21))
    assert result["scalar_value"] == expected
    assert result["source"] == "CALCULATED"


def test_group_and_aggregate_returns_table(ctx):
    result = TOOLS["group_and_aggregate"].handler(
        {"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum", "dimension_column": "region"}, ctx
    )
    assert result["result_type"] == "table"
    assert len(result["table"]) > 0


def test_compare_periods_computes_change(ctx):
    result = TOOLS["compare_periods"].handler(
        {"dataset_id": "orders", "metric_column": "amount", "date_column": "date", "period_a": "2024-01", "period_b": "2024-02"},
        ctx,
    )
    assert "percentage_change" in result or "error" in result


def test_compare_periods_reports_missing_period_honestly(ctx):
    result = TOOLS["compare_periods"].handler(
        {
            "dataset_id": "orders", "metric_column": "amount", "date_column": "date",
            "period_a": "1999-01", "period_b": "1999-02",
        },
        ctx,
    )
    assert "error" in result
    assert "available_periods" in result


def test_detect_anomalies_reports_none_found_when_no_outliers(ctx):
    result = TOOLS["detect_anomalies"].handler({"dataset_id": "customers"}, ctx)
    assert "anomalies_found" in result


@pytest.fixture
def ctx_with_products(ctx):
    n = 20
    products = pd.DataFrame(
        {
            "product_id": list(range(1, n + 1)),
            "product_name": [f"Widget {i % 6}" for i in range(1, n + 1)],
            "sales_amount": [100.0 + i * 5 for i in range(1, n + 1)],
        }
    )
    ctx.dataset_store.put(
        "sales", products,
        profile_dataframe(products, "sales", "sales", "sales.csv", None, DatasetKind.UPLOADED),
    )
    return ctx


def test_group_and_aggregate_resolves_a_natural_language_dimension_to_the_descriptive_column(ctx_with_products):
    # 'sales by product' -- the user never wrote the real column names.
    # Must resolve to product_name (the business-friendly dimension), not
    # product_id, and must not require the caller to already know the
    # exact schema.
    result = TOOLS["group_and_aggregate"].handler(
        {"dataset_id": "sales", "metric_column": "sales", "aggregation": "mean", "dimension_column": "product"},
        ctx_with_products,
    )
    assert result["request"]["dimension_column"] == "product_name"
    assert result["request"]["metric_column"] == "sales_amount"
    assert result["result_type"] == "table"
    assert "interpretation_notes" in result
    assert any("product_name" in note for note in result["interpretation_notes"])


def test_group_and_aggregate_honors_an_explicit_id_request(ctx_with_products):
    result = TOOLS["group_and_aggregate"].handler(
        {"dataset_id": "sales", "metric_column": "sales_amount", "aggregation": "sum", "dimension_column": "product id"},
        ctx_with_products,
    )
    assert result["request"]["dimension_column"] == "product_id"


def test_group_and_aggregate_tolerates_a_typo_in_the_dimension_column(ctx_with_products):
    result = TOOLS["group_and_aggregate"].handler(
        {"dataset_id": "sales", "metric_column": "sales_amount", "aggregation": "sum", "dimension_column": "prodcut"},
        ctx_with_products,
    )
    assert result["request"]["dimension_column"] == "product_name"


def test_calculate_metric_resolves_a_business_synonym(ctx_with_products):
    exact = TOOLS["calculate_metric"].handler(
        {"dataset_id": "sales", "metric_column": "sales_amount", "aggregation": "sum"}, ctx_with_products,
    )
    via_synonym = TOOLS["calculate_metric"].handler(
        {"dataset_id": "sales", "metric_column": "revenue", "aggregation": "sum"}, ctx_with_products,
    )
    assert via_synonym["scalar_value"] == exact["scalar_value"]
    assert via_synonym["request"]["metric_column"] == "sales_amount"


def test_calculate_metric_never_resolves_a_measure_to_an_identifier_column(ctx_with_products):
    # 'product' alone, as a *measure*, must never silently fall through to
    # summing product_id -- there is no reasonable numeric measure here, so
    # this must fail loudly rather than return a meaningless number.
    with pytest.raises(ToolExecutionError):
        TOOLS["calculate_metric"].handler(
            {"dataset_id": "sales", "metric_column": "product", "aggregation": "sum"}, ctx_with_products,
        )


def test_unresolvable_column_raises_with_available_columns_listed(ctx_with_products):
    with pytest.raises(ToolExecutionError) as exc_info:
        TOOLS["group_and_aggregate"].handler(
            {"dataset_id": "sales", "metric_column": "sales_amount", "aggregation": "sum", "dimension_column": "zorblaxian flux"},
            ctx_with_products,
        )
    assert "product_name" in str(exc_info.value)


def test_generate_chart_returns_chart_spec(ctx):
    result = TOOLS["generate_chart"].handler(
        {"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum", "dimension_column": "region"}, ctx
    )
    assert result["chart"] is not None
    assert result["chart"]["dataset_id"] == "orders"


def test_generate_chart_defaults_to_bar_when_chart_type_omitted(ctx):
    # orders.region has only 4 distinct values (North/South/East/West).
    # The default for a category breakdown is now BAR, not DONUT --
    # pie/donut are only appropriate when explicitly requested by the user.
    result = TOOLS["generate_chart"].handler(
        {"dataset_id": "orders", "metric_column": "amount", "aggregation": "sum", "dimension_column": "region"}, ctx
    )
    assert result["chart"]["chart_type"] == "bar"


def test_generate_chart_honors_an_explicit_chart_type_override(ctx):
    # A plain "count/total X by region" question should stay bar even
    # though region's low cardinality would otherwise auto-pick donut --
    # the agent expresses that intent via chart_type, same mechanism as
    # the frontend's manual chart-type override in AnalysisRequest.
    result = TOOLS["generate_chart"].handler(
        {
            "dataset_id": "orders", "metric_column": "amount", "aggregation": "sum",
            "dimension_column": "region", "chart_type": "bar",
        },
        ctx,
    )
    assert result["chart"]["chart_type"] == "bar"


def test_generate_chart_honors_sort_and_top_n_for_a_ranking_question(ctx):
    result = TOOLS["generate_chart"].handler(
        {
            "dataset_id": "orders", "metric_column": "amount", "aggregation": "sum",
            "dimension_column": "region", "sort": "desc", "top_n": 2,
        },
        ctx,
    )
    assert len(result["chart"]["data"]) == 2


@pytest.fixture
def ctx_with_shipping(ctx):
    n = 24
    shipping = pd.DataFrame(
        {
            "region": [["North", "South", "East", "West"][i % 4] for i in range(n)],
            "shipping_mode": [["Standard", "Express"][i % 2] for i in range(n)],
            "sales": [50.0 + i for i in range(n)],
        }
    )
    ctx.dataset_store.put(
        "shipping", shipping,
        profile_dataframe(shipping, "shipping", "shipping", "shipping.csv", None, DatasetKind.UPLOADED),
    )
    return ctx


@pytest.fixture
def ctx_with_country(ctx):
    n = 20
    geo = pd.DataFrame(
        {
            "country": [["Nigeria", "Ghana", "Kenya", "Egypt"][i % 4] for i in range(n)],
            "revenue": [100.0 + i * 5 for i in range(n)],
        }
    )
    ctx.dataset_store.put(
        "geo_sales", geo,
        profile_dataframe(geo, "geo_sales", "geo_sales", "geo_sales.csv", None, DatasetKind.UPLOADED),
    )
    return ctx


def test_group_and_aggregate_second_dimension_produces_two_way_breakdown(ctx_with_shipping):
    # "sales by region and shipping mode" -- both dimensions together.
    result = TOOLS["group_and_aggregate"].handler(
        {
            "dataset_id": "shipping", "metric_column": "sales", "aggregation": "sum",
            "dimension_column": "region", "second_dimension_column": "shipping_mode",
        },
        ctx_with_shipping,
    )
    assert result["request"]["second_dimension_column"] == "shipping_mode"
    assert result["result_type"] == "table"
    assert all("region" in row and "shipping_mode" in row for row in result["table"])


def test_generate_chart_second_dimension_produces_grouped_or_stacked_bar(ctx_with_shipping):
    result = TOOLS["generate_chart"].handler(
        {
            "dataset_id": "shipping", "metric_column": "sales", "aggregation": "sum",
            "dimension_column": "region", "second_dimension_column": "shipping_mode",
        },
        ctx_with_shipping,
    )
    assert result["chart"]["chart_type"] in ("grouped_bar", "stacked_bar")
    assert result["chart"]["series_column"] == "shipping_mode"


def test_generate_chart_second_dimension_resolves_natural_language_names(ctx_with_shipping):
    # Neither dimension spelled exactly -- both go through the resolver.
    result = TOOLS["generate_chart"].handler(
        {
            "dataset_id": "shipping", "metric_column": "sales", "aggregation": "sum",
            "dimension_column": "regon", "second_dimension_column": "shipping mode",
        },
        ctx_with_shipping,
    )
    assert result["chart"]["x_column"] == "region"
    assert result["chart"]["series_column"] == "shipping_mode"


def test_generate_chart_map_override_produces_geo_points_for_a_country_column(ctx_with_country):
    result = TOOLS["generate_chart"].handler(
        {
            "dataset_id": "geo_sales", "metric_column": "revenue", "aggregation": "sum",
            "dimension_column": "country", "chart_type": "map",
        },
        ctx_with_country,
    )
    assert result["chart"]["chart_type"] == "map"
    assert all("lat" in p and "lng" in p for p in result["chart"]["data"])


def test_generate_chart_map_override_is_dropped_for_a_non_geographic_dimension(ctx):
    # 'region' isn't a recognized country column -- requesting 'map' must
    # not silently mislabel a normal bar-shaped result as a map (which the
    # frontend would then fail to render as geo points).
    result = TOOLS["generate_chart"].handler(
        {
            "dataset_id": "orders", "metric_column": "amount", "aggregation": "sum",
            "dimension_column": "region", "chart_type": "map",
        },
        ctx,
    )
    assert result["chart"]["chart_type"] != "map"
    assert any("map" in note.lower() for note in result.get("interpretation_notes", []))


def test_generate_dashboard_bundles_multiple_charts(ctx):
    result = TOOLS["generate_dashboard"].handler({"dataset_id": "orders"}, ctx)
    assert len(result["kpi_suggestions"]) > 0
    assert len(result["charts"]) > 0


def test_search_documents_returns_relevant_chunk_with_metadata(ctx):
    result = TOOLS["search_documents"].handler({"query": "supply disruption revenue decline"}, ctx)
    assert len(result["results"]) > 0
    top = result["results"][0]
    assert top["chunk"]["document_name"] == "report.pdf"
    assert top["chunk"]["location"]["page"] == 1
    assert top["relevance_score"] > 0


def test_search_documents_empty_query_returns_nothing(ctx):
    result = TOOLS["search_documents"].handler({"query": ""}, ctx)
    assert result["results"] == []


def test_retrieve_document_evidence_returns_full_chunk(ctx):
    search = TOOLS["search_documents"].handler({"query": "supply disruption"}, ctx)
    chunk_id = search["results"][0]["chunk"]["id"]
    evidence = TOOLS["retrieve_document_evidence"].handler({"document_id": "doc1", "chunk_id": chunk_id}, ctx)
    assert "supply disruption" in evidence["text"]


def test_retrieve_document_evidence_missing_chunk_raises(ctx):
    with pytest.raises(ToolExecutionError):
        TOOLS["retrieve_document_evidence"].handler({"document_id": "doc1", "chunk_id": "nope"}, ctx)


def test_verify_claim_tool_confirms_matching_number(ctx):
    from app.agent.schemas import ToolInvocation

    invocations = [
        ToolInvocation(id="t1", tool_name="calculate_metric", input={}, output_summary='{"scalar_value": 14.2}', succeeded=True, duration_ms=1)
    ]
    result = verify_claim_tool(
        {"claim_text": "Revenue fell 14.2%.", "claimed_label": "CALCULATED"}, ctx, invocations
    )
    assert result["verified_label"] == "CALCULATED"


def test_verify_claim_tool_downgrades_unsupported_number(ctx):
    from app.agent.schemas import ToolInvocation

    invocations = [
        ToolInvocation(id="t1", tool_name="calculate_metric", input={}, output_summary='{"scalar_value": 5.0}', succeeded=True, duration_ms=1)
    ]
    result = verify_claim_tool(
        {"claim_text": "Revenue fell 99%.", "claimed_label": "VERIFIED_FROM_DATA"}, ctx, invocations
    )
    assert result["verified_label"] == "AI_INTERPRETATION"
    assert result["note"] is not None
