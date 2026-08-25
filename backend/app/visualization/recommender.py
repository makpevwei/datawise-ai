"""Visualization Engine -- decides what chart type fits a result shape.

Selection is driven entirely by the shape of the data/question, never a
fixed default per dataset. When there isn't enough data to plot anything
meaningful, INSUFFICIENT_DATA is returned rather than guessing.
"""

from app.semantic.models import ChartType

DONUT_MAX_CATEGORIES = 6


def recommend_chart_type(
    *,
    result_type: str,
    is_ranking: bool = False,
    dimension_cardinality: int | None = None,
) -> tuple[ChartType, str]:
    if result_type == "insufficient_data":
        return ChartType.INSUFFICIENT_DATA, "Not enough data to recommend a chart."

    if result_type == "scalar":
        return ChartType.KPI_CARD, "A single aggregated value is best shown as a KPI card."

    if result_type == "timeseries":
        return ChartType.LINE, "A metric tracked over time is best shown as a line chart."

    if is_ranking:
        return ChartType.RANKING, "A top/bottom ranking is best shown as a sorted bar chart."

    if dimension_cardinality is not None and dimension_cardinality <= DONUT_MAX_CATEGORIES:
        return (
            ChartType.DONUT,
            f"{dimension_cardinality} categories is few enough to show share of total as a donut chart.",
        )

    return ChartType.BAR, "A metric broken out by category is best shown as a bar chart."


def recommend_scatter_or_table(row_count: int) -> tuple[ChartType, str]:
    if row_count < 3:
        return ChartType.INSUFFICIENT_DATA, "Fewer than 3 overlapping data points -- not enough to plot."
    return ChartType.SCATTER, "Two numeric variables are best compared as a scatter plot."
