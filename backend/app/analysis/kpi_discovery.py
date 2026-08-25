"""Automatic KPI discovery.

Suggests candidate metrics from column names, types, and shape -- never
asserts business meaning a column name doesn't already carry (a column
literally named "amount" is aggregated and labelled "Total amount", not
silently renamed to "Total revenue").
"""

from app.analysis.engine import aggregate_scalar
from app.semantic.models import Aggregation, DatasetProfile, KPISuggestion
from app.semantic.store import DatasetRecord

METRIC_NAME_HINTS = (
    "revenue",
    "sales",
    "amount",
    "price",
    "cost",
    "profit",
    "total",
    "quantity",
    "units",
    "value",
    "salary",
    "bonus",
    "fare",
    "spend",
    "margin",
)

MIN_DIMENSION_CARDINALITY = 2
MAX_DIMENSION_CARDINALITY = 50
MAX_SUGGESTIONS = 8


def _name_matches_metric_hint(column: str) -> bool:
    lowered = column.lower()
    return any(hint in lowered for hint in METRIC_NAME_HINTS)


def rank_metric_candidates(profile: DatasetProfile) -> list[str]:
    candidates = list(profile.numeric_columns)
    candidates.sort(key=lambda c: (0 if _name_matches_metric_hint(c) else 1, profile.numeric_columns.index(c)))
    return candidates[:3]


def rank_dimension_candidates(profile: DatasetProfile) -> list[str]:
    by_name = {c.name: c for c in profile.columns}
    result = []
    for name in profile.categorical_columns:
        col = by_name[name]
        cardinality = col.cardinality or 0
        if MIN_DIMENSION_CARDINALITY <= cardinality <= MAX_DIMENSION_CARDINALITY:
            result.append(name)
    return result[:2]


def discover_kpis(record: DatasetRecord) -> list[KPISuggestion]:
    profile = record.profile
    df = record.dataframe
    suggestions: list[KPISuggestion] = []

    metric_candidates = rank_metric_candidates(profile)
    dimension_candidates = rank_dimension_candidates(profile)
    date_candidates = profile.date_columns[:1]

    for metric in metric_candidates:
        rationale = (
            f"'{metric}' is numeric and its name suggests a summable business quantity."
            if _name_matches_metric_hint(metric)
            else f"'{metric}' is numeric and available for aggregation."
        )
        value = aggregate_scalar(df, metric, Aggregation.SUM)
        suggestions.append(
            KPISuggestion(
                name=f"Total {metric}",
                dataset_id=profile.id,
                metric_column=metric,
                aggregation=Aggregation.SUM,
                rationale=rationale,
                preview_value=value,
            )
        )

    for identifier_column in profile.identifier_columns[:1]:
        count = int(df[identifier_column].nunique())
        suggestions.append(
            KPISuggestion(
                name=f"Distinct {identifier_column}",
                dataset_id=profile.id,
                metric_column=identifier_column,
                aggregation=Aggregation.NUNIQUE,
                rationale=f"'{identifier_column}' looks like an identifier column; counting distinct values is meaningful.",
                preview_value=float(count),
            )
        )

    if metric_candidates and dimension_candidates:
        metric, dimension = metric_candidates[0], dimension_candidates[0]
        suggestions.append(
            KPISuggestion(
                name=f"{metric} by {dimension}",
                dataset_id=profile.id,
                metric_column=metric,
                aggregation=Aggregation.SUM,
                dimension_column=dimension,
                rationale=f"'{dimension}' is a categorical column with a manageable number of groups "
                f"({df[dimension].nunique()}), suitable for breaking '{metric}' down by category.",
            )
        )

    if metric_candidates and date_candidates:
        metric, date_col = metric_candidates[0], date_candidates[0]
        suggestions.append(
            KPISuggestion(
                name=f"{metric} trend over time",
                dataset_id=profile.id,
                metric_column=metric,
                aggregation=Aggregation.SUM,
                date_column=date_col,
                rationale=f"'{date_col}' was detected as a date column, enabling a monthly trend of '{metric}'.",
            )
        )

    for metric in metric_candidates[:2]:
        value = aggregate_scalar(df, metric, Aggregation.MEAN)
        suggestions.append(
            KPISuggestion(
                name=f"Average {metric}",
                dataset_id=profile.id,
                metric_column=metric,
                aggregation=Aggregation.MEAN,
                rationale=f"'{metric}' is numeric; the average is a natural companion to the total.",
                preview_value=value,
            )
        )

    if not suggestions:
        suggestions.append(
            KPISuggestion(
                name="Record count",
                dataset_id=profile.id,
                metric_column=None,
                aggregation=Aggregation.COUNT,
                rationale="No numeric or identifier columns were suitable for a metric-based KPI; "
                "row count is the only reliable summary available.",
                preview_value=float(len(df)),
            )
        )

    return suggestions[:MAX_SUGGESTIONS]
