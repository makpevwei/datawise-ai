from app.semantic.models import ChartType
from app.visualization.recommender import recommend_chart_type, recommend_scatter_or_table


def test_scalar_recommends_kpi_card():
    chart_type, _ = recommend_chart_type(result_type="scalar")
    assert chart_type == ChartType.KPI_CARD


def test_timeseries_recommends_line():
    chart_type, _ = recommend_chart_type(result_type="timeseries")
    assert chart_type == ChartType.LINE


def test_ranking_recommends_ranking_chart():
    chart_type, _ = recommend_chart_type(result_type="table", is_ranking=True)
    assert chart_type == ChartType.RANKING


def test_low_cardinality_breakdown_recommends_bar():
    # Bar is the correct default for category comparison regardless of
    # cardinality -- pie/donut are only used when explicitly requested
    # and should never be the automatic default for a general breakdown.
    chart_type, _ = recommend_chart_type(result_type="table", dimension_cardinality=4)
    assert chart_type == ChartType.BAR


def test_high_cardinality_breakdown_recommends_bar():
    chart_type, _ = recommend_chart_type(result_type="table", dimension_cardinality=30)
    assert chart_type == ChartType.BAR


def test_insufficient_data_never_recommends_a_chart():
    chart_type, reason = recommend_chart_type(result_type="insufficient_data")
    assert chart_type == ChartType.INSUFFICIENT_DATA
    assert reason


def test_scatter_requires_minimum_overlapping_points():
    chart_type, _ = recommend_scatter_or_table(row_count=2)
    assert chart_type == ChartType.INSUFFICIENT_DATA
    chart_type, _ = recommend_scatter_or_table(row_count=10)
    assert chart_type == ChartType.SCATTER
