"""Visualization Engine -- decides what chart type fits a result shape.

Selection is driven entirely by the shape of the data/question, never a
fixed default per dataset. When there isn't enough data to plot anything
meaningful, INSUFFICIENT_DATA is returned rather than guessing.

Chart type hierarchy for categorical breakdowns:
  - ranking (explicit top-N) → RANKING (sorted bar)
  - time series → LINE
  - two dimensions → GROUPED_BAR / STACKED_BAR
  - category comparison (the most common case) → BAR
  - pie/donut → only when the user explicitly requests it AND cardinality
    is low enough to be readable (≤ DONUT_MAX_CATEGORIES). Never the
    automatic default for a plain category breakdown.
"""

from app.semantic.models import ChartType

# Pie/donut charts are only readable up to this many slices.
# Above this limit we substitute a ranked bar chart, even when the user
# explicitly requested pie/donut (see engine._apply_chart_override).
DONUT_MAX_CATEGORIES = 6


def recommend_chart_type(
    *,
    result_type: str,
    is_ranking: bool = False,
    dimension_cardinality: int | None = None,
) -> tuple[ChartType, str]:
    """Return the most appropriate chart type for the given result shape.

    BAR is the default for category breakdowns — not DONUT/PIE.
    Pie/Donut must only be chosen when the user explicitly selects it
    (handled by _apply_chart_override in engine.py).
    """
    if result_type == "insufficient_data":
        return ChartType.INSUFFICIENT_DATA, "Not enough data to recommend a chart."

    if result_type == "scalar":
        return ChartType.KPI_CARD, "A single aggregated value is best shown as a KPI card."

    if result_type == "timeseries":
        return ChartType.LINE, "A metric tracked over time is best shown as a line chart."

    if is_ranking:
        return ChartType.RANKING, "A top/bottom ranking is best shown as a sorted bar chart."

    # Category breakdown — default to BAR regardless of cardinality.
    # Pie/Donut are valid for composition/share but are not the right
    # default for general category comparison (e.g. price by shipping_mode
    # should be a bar chart, not a doughnut).
    if dimension_cardinality is not None and dimension_cardinality > DONUT_MAX_CATEGORIES:
        return (
            ChartType.BAR,
            f"{dimension_cardinality} categories — shown as a bar chart for readability.",
        )

    return (
        ChartType.BAR,
        "A metric broken out by category is best shown as a bar chart.",
    )


def recommend_scatter_or_table(row_count: int) -> tuple[ChartType, str]:
    if row_count < 3:
        return ChartType.INSUFFICIENT_DATA, "Fewer than 3 overlapping data points -- not enough to plot."
    return ChartType.SCATTER, "Two numeric variables are best compared as a scatter plot."
