from app.analysis.kpi_discovery import discover_kpis, _is_identifier_column
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetRecord
from tests.factories import orders_df


def _record():
    df = orders_df(20)
    profile = profile_dataframe(df, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_identifier_detection():
    # These should be classified as identifiers and excluded from SUM KPIs
    assert _is_identifier_column("CustomerKey")
    assert _is_identifier_column("SalesOrderLineKey")
    assert _is_identifier_column("SalesTerritoryKey")
    assert _is_identifier_column("ProductKey")
    assert _is_identifier_column("customer_id")
    assert _is_identifier_column("order_no")
    # These are business metrics and should not be classified as identifiers
    assert not _is_identifier_column("Sales Amount")
    assert not _is_identifier_column("revenue")
    assert not _is_identifier_column("quantity")
    assert not _is_identifier_column("price")


def test_suggests_total_for_numeric_metric_column():
    suggestions = discover_kpis(_record())
    # The KPI engine now uses clean display names; "amount" column maps to
    # "Total Amount" (or "Total amount" with title-case). Check the column
    # is included, not the exact label format which may vary.
    amount_kpi = next((s for s in suggestions if s.metric_column == "amount" and s.aggregation == "sum"), None)
    assert amount_kpi is not None, "Expected a SUM KPI for the 'amount' column"
    expected = sum(100.0 + i * 10 for i in range(1, 21))
    assert amount_kpi.preview_value == expected


def test_suggests_breakdown_by_dimension():
    suggestions = discover_kpis(_record())
    assert any(s.dimension_column == "region" for s in suggestions)


def test_suggests_trend_when_date_column_present():
    suggestions = discover_kpis(_record())
    assert any(s.date_column == "date" for s in suggestions)


def test_every_suggestion_is_labelled_as_suggested():
    suggestions = discover_kpis(_record())
    assert all(s.label == "Suggested KPI" for s in suggestions)


def test_does_not_relabel_column_business_meaning():
    # "amount" must be aggregated and named for what it literally is,
    # never silently renamed to "revenue" or similar.
    suggestions = discover_kpis(_record())
    assert any("amount" in s.name.lower() for s in suggestions)
    assert not any("revenue" in s.name.lower() for s in suggestions)


def test_falls_back_to_record_count_when_no_usable_columns():
    import pandas as pd

    df = pd.DataFrame({"free_text": ["a very long unique description " + str(i) for i in range(30)]})
    profile = profile_dataframe(df, "d1", "notes", "notes.csv", None, DatasetKind.UPLOADED)
    record = DatasetRecord(dataframe=df, profile=profile)
    suggestions = discover_kpis(record)
    # Falls back to record count when no numeric or identifier columns exist
    assert suggestions[0].name == "Record Count"
    assert suggestions[0].preview_value == 30


def test_identifier_columns_not_summed_as_financial_kpis():
    """CustomerKey, SalesTerritoryKey etc. must never appear as SUM KPIs."""
    import pandas as pd
    from app.profiling.service import profile_dataframe

    df = pd.DataFrame({
        "CustomerKey": range(1, 101),
        "SalesTerritoryKey": [1, 2, 3, 4] * 25,
        "Sales Amount": [float(i * 100) for i in range(1, 101)],
        "Order Quantity": [2] * 100,
    })
    profile = profile_dataframe(df, "aw", "Sales", "sales.csv", None, DatasetKind.UPLOADED)
    record = DatasetRecord(dataframe=df, profile=profile)
    suggestions = discover_kpis(record)

    # No suggestion should SUM an identifier column
    for s in suggestions:
        if s.aggregation == "sum":
            assert not _is_identifier_column(s.metric_column or ""), \
                f"Identifier column '{s.metric_column}' was summed as a financial KPI: {s.name}"
