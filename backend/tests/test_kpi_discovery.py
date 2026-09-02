import pandas as pd

from app.ai.base import LLMProvider
from app.ai.types import ConversationTurn, LLMTurn, ToolSchema
from app.analysis.kpi_discovery import _is_identifier_column, deterministic_aggregation, discover_kpis
from app.profiling.service import profile_dataframe
from app.semantic.models import Aggregation, DatasetKind
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


def _hr_record():
    df = pd.DataFrame(
        {
            "employee_id": [f"E{i}" for i in range(20)],
            "age": [25 + (i % 30) for i in range(20)],
            "salary": [50000.0 + i * 1000 for i in range(20)],
            "department": [("Engineering", "Sales", "HR", "Finance")[i % 4] for i in range(20)],
        }
    )
    profile = profile_dataframe(df, "hr", "hr", "hr.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_age_is_averaged_not_summed_by_the_deterministic_fallback():
    # A workforce's *total* age is a meaningless number -- averaging it is
    # the only reading that means anything on an executive dashboard.
    assert deterministic_aggregation("age") == Aggregation.MEAN
    suggestions = discover_kpis(_hr_record())
    age_kpi = next(s for s in suggestions if s.metric_column == "age")
    assert age_kpi.aggregation == "mean"
    assert "average" in age_kpi.name.lower()


def test_closing_inventory_value_is_averaged_not_summed_across_snapshots():
    # Found live against a real dataset: summing a "Closing_..." balance
    # column across 24 monthly snapshots for one store produced a nonsense
    # ~28B figure presented as "excess inventory" -- a point-in-time
    # balance is never a meaningful sum across time.
    assert deterministic_aggregation("Closing_Inventory_Value_NGN") == Aggregation.MEAN
    assert deterministic_aggregation("Opening_Stock_Units") == Aggregation.MEAN


def test_salary_is_still_summed_by_the_deterministic_fallback():
    # A genuinely additive quantity (money paid out) must not get swept
    # into the same "average it" bucket as per-entity attributes like age.
    assert deterministic_aggregation("salary") == Aggregation.SUM
    suggestions = discover_kpis(_hr_record())
    salary_kpi = next(s for s in suggestions if s.metric_column == "salary" and s.aggregation == "sum")
    assert "total" in salary_kpi.name.lower()


class _StubLLMProvider(LLMProvider):
    """Returns a fixed classification, never a real value -- proves the
    LLM path only ever *chooses an aggregation*, never touches the actual
    computed number (which still comes from the real dataframe)."""

    provider_name = "stub"
    model = "stub-model"

    def __init__(self, response_text: str):
        self._response_text = response_text

    def send(self, system: str, history: list[ConversationTurn], tools: list[ToolSchema]) -> LLMTurn:
        return LLMTurn(text=self._response_text, tool_calls=[], stop_reason="end_turn")


def test_llm_classification_overrides_the_deterministic_default():
    # The stub claims "salary" should be averaged, not summed -- an
    # obviously wrong answer a human would reject, chosen deliberately so
    # the test proves the LLM's choice is actually honored, not just
    # coincidentally matching the heuristic it would override.
    provider = _StubLLMProvider('{"salary": "mean", "age": "mean"}')
    suggestions = discover_kpis(_hr_record(), llm_provider=provider)
    salary_kpi = next(s for s in suggestions if s.metric_column == "salary")
    assert salary_kpi.aggregation == "mean"
    # The number itself is still the real, unmodified dataframe mean --
    # the LLM never supplies or touches the value.
    assert salary_kpi.preview_value == _hr_record().dataframe["salary"].mean()


def test_llm_failure_falls_back_to_the_deterministic_heuristic():
    class _BrokenProvider(_StubLLMProvider):
        def send(self, system, history, tools):
            raise RuntimeError("simulated provider outage")

    suggestions = discover_kpis(_hr_record(), llm_provider=_BrokenProvider(""))
    age_kpi = next(s for s in suggestions if s.metric_column == "age")
    # Still correct via the deterministic fallback -- a broken LLM call
    # must never block KPI discovery or produce a wrong/missing KPI.
    assert age_kpi.aggregation == "mean"


def test_llm_malformed_response_falls_back_to_the_deterministic_heuristic():
    provider = _StubLLMProvider("not valid json at all")
    suggestions = discover_kpis(_hr_record(), llm_provider=provider)
    salary_kpi = next(s for s in suggestions if s.metric_column == "salary" and s.aggregation == "sum")
    assert salary_kpi is not None


def _date_dim_record():
    # Reproduces the real bug found against a live date-dimension table:
    # Year/Month_Number/Week_Number/Day are numeric but neither summing
    # nor averaging any of them is a meaningful headline KPI.
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=40, freq="D"),
            "year": [2024] * 40,
            "month_number": [1] * 31 + [2] * 9,
            "week_number": [(i // 7) + 1 for i in range(40)],
            "day": list(range(1, 32)) + list(range(1, 10)),
            "revenue": [1000.0 + i * 10 for i in range(40)],
        }
    )
    profile = profile_dataframe(df, "dates", "dates", "dates.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_calendar_date_part_columns_are_excluded_by_the_deterministic_fallback():
    from app.analysis.kpi_discovery import _is_date_part_column

    assert _is_date_part_column("year")
    assert _is_date_part_column("Month_Number")
    assert _is_date_part_column("Week_Number")
    assert _is_date_part_column("Day")
    # Plurals are real duration metrics, not calendar date-parts -- must
    # NOT be excluded.
    assert not _is_date_part_column("Delivery_Days")
    assert not _is_date_part_column("Years_At_Company")

    suggestions = discover_kpis(_date_dim_record())
    metric_columns = {s.metric_column for s in suggestions}
    assert "year" not in metric_columns
    assert "month_number" not in metric_columns
    assert "week_number" not in metric_columns
    assert "day" not in metric_columns
    assert "revenue" in metric_columns


def test_llm_can_exclude_a_column_the_deterministic_heuristic_would_have_kept():
    # A column name the fixed word list has never heard of (a stand-in for
    # any real dataset's own naming quirk) -- proves exclusion is a genuine
    # LLM judgment call, not just a hardcoded pattern re-implemented here.
    df = pd.DataFrame(
        {
            "fiscal_period_code": [1, 2, 3, 4] * 10,
            "revenue": [1000.0 + i for i in range(40)],
        }
    )
    profile = profile_dataframe(df, "d", "d", "d.csv", None, DatasetKind.UPLOADED)
    record = DatasetRecord(dataframe=df, profile=profile)

    provider = _StubLLMProvider('{"fiscal_period_code": "exclude", "revenue": "sum"}')
    suggestions = discover_kpis(record, llm_provider=provider)
    metric_columns = {s.metric_column for s in suggestions}
    assert "fiscal_period_code" not in metric_columns
    assert "revenue" in metric_columns


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
