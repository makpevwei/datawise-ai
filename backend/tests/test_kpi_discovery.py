from app.analysis.kpi_discovery import discover_kpis
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetRecord
from tests.factories import orders_df


def _record():
    df = orders_df(20)
    profile = profile_dataframe(df, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_suggests_total_for_numeric_metric_column():
    suggestions = discover_kpis(_record())
    total_amount = next(s for s in suggestions if s.name == "Total amount")
    assert total_amount.aggregation == "sum"
    expected = sum(100.0 + i * 10 for i in range(1, 21))
    assert total_amount.preview_value == expected


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
    assert any("amount" in s.name for s in suggestions)
    assert not any("revenue" in s.name.lower() for s in suggestions)


def test_falls_back_to_record_count_when_no_usable_columns():
    import pandas as pd

    df = pd.DataFrame({"free_text": ["a very long unique description " + str(i) for i in range(30)]})
    profile = profile_dataframe(df, "d1", "notes", "notes.csv", None, DatasetKind.UPLOADED)
    record = DatasetRecord(dataframe=df, profile=profile)
    suggestions = discover_kpis(record)
    assert suggestions[0].name == "Record count"
    assert suggestions[0].preview_value == 30
