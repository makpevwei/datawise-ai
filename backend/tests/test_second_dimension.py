"""Second dimension (grouped/stacked breakdown) -- Phase 4 continuation
section 15. Extends the existing deterministic engine's grouped-table
branch to two dimensions; never touches the LLM."""

import pandas as pd
import pytest

from app.analysis.engine import run_analysis
from app.profiling.service import profile_dataframe
from app.semantic.models import AnalysisRequest, ChartType, DatasetKind
from app.semantic.store import DatasetStore


@pytest.fixture
def store(tmp_path):
    s = DatasetStore(storage_dir=tmp_path)
    df = pd.DataFrame(
        {
            "region": ["North", "North", "South", "South", "North", "South"],
            "category": ["Electronics", "Footwear", "Electronics", "Footwear", "Footwear", "Electronics"],
            "revenue": [100.0, 50.0, 80.0, 40.0, 30.0, 90.0],
        }
    )
    dataset_id = "ds1"
    profile = profile_dataframe(df=df, dataset_id=dataset_id, name="sales.csv", source_file="sales.csv", sheet_name=None, kind=DatasetKind.UPLOADED)
    s.put(dataset_id, df, profile)
    return s


def test_second_dimension_produces_one_row_per_combination(store):
    request = AnalysisRequest(
        dataset_id="ds1", metric_column="revenue", aggregation="sum",
        dimension_column="region", second_dimension_column="category",
    )
    result = run_analysis(request, store)
    assert result.result_type == "table"
    assert result.table is not None
    combos = {(r["region"], r["category"]) for r in result.table}
    assert combos == {("North", "Electronics"), ("North", "Footwear"), ("South", "Electronics"), ("South", "Footwear")}


def test_second_dimension_values_are_correctly_calculated(store):
    request = AnalysisRequest(
        dataset_id="ds1", metric_column="revenue", aggregation="sum",
        dimension_column="region", second_dimension_column="category",
    )
    result = run_analysis(request, store)
    north_electronics = next(r for r in result.table if r["region"] == "North" and r["category"] == "Electronics")
    assert north_electronics["sum_revenue"] == 100.0


def test_second_dimension_chart_recommendation_carries_series_column(store):
    request = AnalysisRequest(
        dataset_id="ds1", metric_column="revenue", aggregation="sum",
        dimension_column="region", second_dimension_column="category",
    )
    result = run_analysis(request, store)
    assert result.chart_recommendation is not None
    assert result.chart_recommendation.chart_type in (ChartType.GROUPED_BAR, ChartType.STACKED_BAR)
    assert result.chart_recommendation.series_column == "category"
    assert result.chart_recommendation.x_column == "region"


def test_second_dimension_is_ignored_when_no_first_dimension_is_given(store):
    """Guards against a nonsensical request; falls back to the scalar branch."""
    request = AnalysisRequest(dataset_id="ds1", metric_column="revenue", aggregation="sum", second_dimension_column="category")
    result = run_analysis(request, store)
    assert result.result_type == "scalar"


def test_second_dimension_with_date_column_falls_back_to_single_dimension_timeseries(tmp_path):
    """date + dim + seconddim isn't supported as a 3-way cube; the date
    branch (which only understands one optional dimension) takes priority,
    same shape as before this feature existed."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=6, freq="MS"),
            "region": ["North", "South"] * 3,
            "category": ["Electronics", "Footwear"] * 3,
            "revenue": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        }
    )
    s = DatasetStore(storage_dir=tmp_path)
    profile = profile_dataframe(df=df, dataset_id="ds2", name="ts.csv", source_file="ts.csv", sheet_name=None, kind=DatasetKind.UPLOADED)
    s.put("ds2", df, profile)

    request = AnalysisRequest(
        dataset_id="ds2", metric_column="revenue", aggregation="sum",
        dimension_column="region", second_dimension_column="category", date_column="date",
    )
    result = run_analysis(request, s)
    assert result.result_type == "timeseries"
