import pandas as pd
import pytest

from app.analysis.engine import AnalysisError, run_analysis
from app.profiling.service import profile_dataframe
from app.semantic.models import Aggregation, AnalysisRequest, ChartType, DatasetKind, FilterCondition, FilterOperator
from app.semantic.store import DatasetStore
from tests.factories import orders_df


@pytest.fixture
def store(tmp_path):
    s = DatasetStore(storage_dir=tmp_path)
    orders = orders_df(20)
    s.put("orders", orders, profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
    return s


@pytest.fixture
def geo_store(tmp_path):
    s = DatasetStore(storage_dir=tmp_path / "geo")
    # Spec section 29's exact test data, plus one unmapped value to exercise
    # honest unmatched-country handling.
    geo = pd.DataFrame(
        {
            "country": ["Nigeria", "Ghana", "Kenya", "South Africa", "United Kingdom", "United States", "Wakanda"],
            "revenue": [5_000_000, 3_000_000, 2_000_000, 4_000_000, 1_500_000, 7_000_000, 999],
            "quantity": [1200, 800, 600, 900, 300, 1500, 1],
        }
    )
    s.put("geo", geo, profile_dataframe(geo, "geo", "geo", "geo.csv", None, DatasetKind.UPLOADED))
    return s


def test_scalar_sum_matches_manual_calculation(store):
    request = AnalysisRequest(dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM)
    result = run_analysis(request, store)
    expected = sum(100.0 + i * 10 for i in range(1, 21))
    assert result.result_type == "scalar"
    assert result.scalar_value == expected
    assert result.source == "CALCULATED"


def test_grouped_table_includes_percentage_of_total(store):
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM, dimension_column="region"
    )
    result = run_analysis(request, store)
    assert result.result_type == "table"
    total_pct = sum(row["percentage_of_total"] for row in result.table)
    assert round(total_pct, 1) == 100.0


def test_top_n_ranking_limits_rows(store):
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM,
        dimension_column="region", top_n=2,
    )
    result = run_analysis(request, store)
    assert len(result.table) == 2
    assert result.chart_recommendation.chart_type == "ranking"


def test_timeseries_groups_by_month(store):
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM, date_column="date"
    )
    result = run_analysis(request, store)
    assert result.result_type == "timeseries"
    assert result.chart_recommendation.chart_type == "line"
    assert len(result.table) >= 2


def test_filters_narrow_the_result(store):
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM,
        filters=[FilterCondition(column="region", operator=FilterOperator.EQ, value="North")],
    )
    all_request = AnalysisRequest(dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM)
    filtered = run_analysis(request, store)
    unfiltered = run_analysis(all_request, store)
    assert filtered.scalar_value < unfiltered.scalar_value


def test_filters_that_match_nothing_return_insufficient_data(store):
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM,
        filters=[FilterCondition(column="region", operator=FilterOperator.EQ, value="Nowhere")],
    )
    result = run_analysis(request, store)
    assert result.result_type == "insufficient_data"
    assert result.source == "INSUFFICIENT_DATA"
    assert result.chart_recommendation.chart_type == "insufficient_data"


def test_missing_metric_column_is_client_error(store):
    request = AnalysisRequest(dataset_id="orders", metric_column="does_not_exist", aggregation=Aggregation.SUM)
    with pytest.raises(AnalysisError):
        run_analysis(request, store)


def test_missing_dataset_is_client_error(store):
    request = AnalysisRequest(dataset_id="no-such-dataset", aggregation=Aggregation.COUNT)
    with pytest.raises(AnalysisError):
        run_analysis(request, store)


def test_count_without_metric_counts_rows(store):
    request = AnalysisRequest(dataset_id="orders", aggregation=Aggregation.COUNT)
    result = run_analysis(request, store)
    assert result.scalar_value == 20


def test_country_map_resolves_real_centroids_and_reports_unmatched(geo_store):
    request = AnalysisRequest(
        dataset_id="geo", metric_column="revenue", aggregation=Aggregation.SUM,
        dimension_column="country", chart_type=ChartType.MAP,
    )
    result = run_analysis(request, geo_store)
    chart = result.chart_recommendation

    assert chart.chart_type == "map"
    assert chart.reason == "Country-level map using representative country coordinates."
    # 6 of the 7 rows resolve; "Wakanda" does not and must never get a
    # fabricated coordinate.
    assert len(chart.data) == 6
    assert chart.unmatched_categories == ["Wakanda"]

    nigeria_point = next(p for p in chart.data if p["label"] == "Nigeria")
    assert nigeria_point["lat"] == pytest.approx(9.08)
    assert nigeria_point["lng"] == pytest.approx(8.68)
    assert nigeria_point["value"] == 5_000_000

    # The underlying dataframe/original data is untouched by map generation.
    original = geo_store.get("geo").dataframe
    assert list(original["country"]) == [
        "Nigeria", "Ghana", "Kenya", "South Africa", "United Kingdom", "United States", "Wakanda",
    ]


@pytest.fixture
def many_customers_store(tmp_path):
    # 20 distinct customers -- enough to exceed MAX_DONUT_PIE_SLICES, for
    # exercising the "don't honor a pie/donut request for too many
    # categories" smart-fallback (spec: "average revenue by 2,000
    # customers in a pie chart" must not become a 2,000-slice pie).
    s = DatasetStore(storage_dir=tmp_path / "many_customers")
    df = pd.DataFrame(
        {
            "customer_name": [f"Customer {i}" for i in range(1, 21)],
            "revenue": [1000.0 + i * 37 for i in range(1, 21)],
        }
    )
    s.put("sales", df, profile_dataframe(df, "sales", "sales", "sales.csv", None, DatasetKind.UPLOADED))
    return s


def test_explicit_donut_request_is_honored_for_a_small_number_of_categories(store):
    # "region" only has 4 distinct values -- well within a readable donut.
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM,
        dimension_column="region", chart_type=ChartType.DONUT,
    )
    result = run_analysis(request, store)
    assert result.chart_recommendation.chart_type == "donut"
    assert result.chart_recommendation.reason == "You selected donut."


def test_explicit_pie_request_falls_back_to_bar_for_too_many_categories(many_customers_store):
    request = AnalysisRequest(
        dataset_id="sales", metric_column="revenue", aggregation=Aggregation.SUM,
        dimension_column="customer_name", chart_type=ChartType.PIE,
    )
    result = run_analysis(request, many_customers_store)
    chart = result.chart_recommendation
    assert chart.chart_type == "bar"
    assert "20 categories" in chart.reason
    assert "pie" in chart.reason
    # The underlying calculation is untouched by the chart-type fallback --
    # same 20 rows, same values, only the recommended chart type changed.
    assert result.result_type == "table"
    assert len(result.table) == 20
    assert sum(row["sum_revenue"] for row in result.table) == sum(1000.0 + i * 37 for i in range(1, 21))


def test_map_centroid_resolution_only_triggers_for_a_real_country_column(store):
    # "region" (North/South/East/West) is not a country column, so even
    # with chart_type=map explicitly requested, the engine must not attempt
    # centroid resolution against non-country values -- it falls back to
    # the plain grouped rows rather than producing nonsense lat/lng points.
    request = AnalysisRequest(
        dataset_id="orders", metric_column="amount", aggregation=Aggregation.SUM,
        dimension_column="region", chart_type=ChartType.MAP,
    )
    result = run_analysis(request, store)
    chart = result.chart_recommendation
    assert chart.unmatched_categories is None
    assert all("lat" not in row for row in chart.data)
