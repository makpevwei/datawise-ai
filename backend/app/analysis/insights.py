"""Deterministic business insight generation.

Every insight is computed directly from the data and carries Finding /
Evidence / Calculation / Interpretation, plus a confidence label. Nothing
here calls an LLM -- this is the CALCULATED side of the CALCULATED vs.
AI INTERPRETATION split. When a category of insight can't be supported by
the data, it is simply not generated (never fabricated).
"""

import uuid

import pandas as pd

from app.analysis.engine import numeric_series
from app.analysis.kpi_discovery import rank_dimension_candidates, rank_metric_candidates
from app.semantic.models import Evidence, Insight, SourceLabel
from app.semantic.store import DatasetRecord

CONCENTRATION_THRESHOLD_PCT = 40.0
MISSING_THRESHOLD_PCT = 30.0
DUPLICATE_ROW_THRESHOLD_PCT = 5.0
SIGNIFICANT_CHANGE_THRESHOLD_PCT = 15.0
MAX_MISSING_INSIGHTS = 3


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _top_performer_and_concentration(record: DatasetRecord) -> list[Insight]:
    profile, df = record.profile, record.dataframe
    metrics = rank_metric_candidates(profile)
    dimensions = rank_dimension_candidates(profile)
    if not metrics or not dimensions:
        return []

    metric, dimension = metrics[0], dimensions[0]
    grouped = numeric_series(df[metric]).groupby(df[dimension], observed=True).sum().dropna()
    if len(grouped) == 0:
        return []

    total = float(grouped.sum())
    if total == 0:
        return []
    top_category = grouped.idxmax()
    top_value = float(grouped.max())
    share = round(top_value / total * 100, 2)

    insights = [
        Insight(
            id=_new_id(),
            dataset_id=profile.id,
            category="top_performer",
            finding=f"'{top_category}' has the highest {metric} among all {dimension} groups, "
            f"accounting for {share}% of the total.",
            evidence=Evidence(
                description=f"Sum of {metric} for '{top_category}' vs. total across all {dimension} groups.",
                supporting_values={"top_value": top_value, "total": total, "group_count": len(grouped)},
            ),
            calculation=f"{top_value} / {total} * 100 = {share}%",
            interpretation=f"'{top_category}' is the largest single contributor to {metric} in this dataset.",
            confidence_label=SourceLabel.CALCULATED,
        )
    ]

    if share > CONCENTRATION_THRESHOLD_PCT:
        insights.append(
            Insight(
                id=_new_id(),
                dataset_id=profile.id,
                category="concentration_risk",
                finding=f"{metric} is concentrated in a single {dimension}: '{top_category}' alone "
                f"accounts for {share}% of the total.",
                evidence=Evidence(
                    description=f"'{top_category}' share of total {metric} exceeds the "
                    f"{CONCENTRATION_THRESHOLD_PCT:.0f}% concentration threshold.",
                    supporting_values={"top_value": top_value, "total": total},
                ),
                calculation=f"{top_value} / {total} * 100 = {share}%",
                interpretation=f"Reliance on '{top_category}' for {metric} may represent a "
                "concentration risk if that group's performance were to decline.",
                confidence_label=SourceLabel.CALCULATED,
            )
        )
    return insights


def _data_quality_insights(record: DatasetRecord) -> list[Insight]:
    profile = record.profile
    insights: list[Insight] = []

    if profile.quality.duplicate_row_percentage > DUPLICATE_ROW_THRESHOLD_PCT:
        insights.append(
            Insight(
                id=_new_id(),
                dataset_id=profile.id,
                category="data_quality",
                finding=f"{profile.quality.duplicate_row_count} duplicate rows were found "
                f"({profile.quality.duplicate_row_percentage}% of all rows).",
                evidence=Evidence(
                    description="Exact full-row duplicates detected during profiling.",
                    supporting_values={
                        "duplicate_row_count": profile.quality.duplicate_row_count,
                        "row_count": profile.row_count,
                    },
                ),
                calculation=f"{profile.quality.duplicate_row_count} / {profile.row_count} * 100 = "
                f"{profile.quality.duplicate_row_percentage}%",
                interpretation="Duplicate rows can inflate totals and counts; consider de-duplicating "
                "before relying on aggregate figures.",
                confidence_label=SourceLabel.VERIFIED_FROM_DATA,
            )
        )

    high_missing = [c for c in profile.columns if c.missing_percentage > MISSING_THRESHOLD_PCT]
    for col in high_missing[:MAX_MISSING_INSIGHTS]:
        insights.append(
            Insight(
                id=_new_id(),
                dataset_id=profile.id,
                category="data_quality",
                finding=f"Column '{col.name}' is missing {col.missing_percentage}% of its values.",
                evidence=Evidence(
                    description=f"{col.missing_count} of {col.row_count} rows have no value in '{col.name}'.",
                    supporting_values={"missing_count": col.missing_count, "row_count": col.row_count},
                ),
                calculation=f"{col.missing_count} / {col.row_count} * 100 = {col.missing_percentage}%",
                interpretation=f"Analyses using '{col.name}' should account for this gap; "
                "results based on it cover only the populated rows.",
                confidence_label=SourceLabel.VERIFIED_FROM_DATA,
            )
        )

    return insights


def _distribution_insight(record: DatasetRecord) -> list[Insight]:
    """Distribution insight — only surfaced when the concentration itself is
    materially significant (>50% in one value) AND there's no numeric metric
    to rank by. A bare "X is the most common value" is not a management finding.
    """
    profile, df = record.profile, record.dataframe
    metrics = rank_metric_candidates(profile)
    dimensions = rank_dimension_candidates(profile)
    if metrics or not dimensions:
        return []  # only used as a fallback when there's no metric to rank by

    dimension = dimensions[0]
    counts = df[dimension].dropna().astype(str).value_counts()
    if len(counts) == 0:
        return []
    total = int(counts.sum())
    top_value, top_count = counts.index[0], int(counts.iloc[0])
    share = round(top_count / total * 100, 2)

    # Only surface when concentration is materially high — otherwise
    # "most common value" adds no management insight.
    if share < 50.0:
        return []

    return [
        Insight(
            id=_new_id(),
            dataset_id=profile.id,
            category="concentration_risk",
            finding=f"{share}% of records share the same '{dimension}' value ('{top_value}'), "
            f"indicating high concentration in this dataset.",
            evidence=Evidence(
                description=f"Value counts for '{dimension}': '{top_value}' appears in {top_count} of {total} records.",
                supporting_values={"top_count": top_count, "total": total, "share_pct": share},
            ),
            calculation=f"{top_count} / {total} * 100 = {share}%",
            interpretation=f"Over half of all records belong to a single '{dimension}' group. "
            f"This level of concentration may warrant investigation.",
            confidence_label=SourceLabel.CALCULATED,
        )
    ]


def _significant_change_insight(record: DatasetRecord) -> list[Insight]:
    profile, df = record.profile, record.dataframe
    metrics = rank_metric_candidates(profile)
    dates = profile.date_columns
    if not metrics or not dates:
        return []

    metric, date_col = metrics[0], dates[0]
    parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
    valid = parsed_dates.notna()
    if valid.sum() == 0:
        return []

    working = pd.DataFrame(
        {"period": parsed_dates[valid].dt.to_period("M"), "metric": numeric_series(df.loc[valid, metric])}
    )
    monthly = working.groupby("period")["metric"].sum().dropna().sort_index()
    if len(monthly) < 2:
        return []

    last_period, prior_period = monthly.index[-1], monthly.index[-2]
    last_value, prior_value = float(monthly.iloc[-1]), float(monthly.iloc[-2])
    if prior_value == 0:
        return []
    pct_change = round((last_value - prior_value) / prior_value * 100, 2)
    if abs(pct_change) < SIGNIFICANT_CHANGE_THRESHOLD_PCT:
        return []

    direction = "increased" if pct_change > 0 else "decreased"
    return [
        Insight(
            id=_new_id(),
            dataset_id=profile.id,
            category="significant_change",
            finding=f"{metric} {direction} {abs(pct_change)}% from {prior_period} to {last_period}.",
            evidence=Evidence(
                description=f"Monthly sum of {metric} for the two most recent periods.",
                supporting_values={
                    "prior_period": str(prior_period),
                    "prior_value": prior_value,
                    "last_period": str(last_period),
                    "last_value": last_value,
                },
            ),
            calculation=f"({last_value} - {prior_value}) / {prior_value} * 100 = {pct_change}%",
            interpretation=f"This is the most recent period-over-period change in {metric} "
            "that the data can support; investigate the drivers before acting on it.",
            confidence_label=SourceLabel.CALCULATED,
        )
    ]


def compute_iqr_anomalies(values: pd.Series) -> dict | None:
    """IQR-based outlier detection on a single numeric series.

    Returns None when there isn't enough data or no variation to flag
    outliers against; otherwise the bounds and the outlier rows found.
    Shared by the deterministic insight generator and the agent's
    detect_anomalies tool so both report the same numbers.
    """
    values = values.dropna()
    if len(values) < 10:
        return None
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = values[(values < lower) | (values > upper)]
    if len(outliers) == 0:
        return None
    return {
        "q1": round(float(q1), 2),
        "q3": round(float(q3), 2),
        "iqr": round(float(iqr), 2),
        "lower_bound": round(float(lower), 2),
        "upper_bound": round(float(upper), 2),
        "outlier_count": len(outliers),
        "total_considered": len(values),
        "outlier_share_pct": round(len(outliers) / len(values) * 100, 2),
        "outlier_values": [round(float(v), 2) for v in outliers.head(20)],
    }


def _anomaly_insight(record: DatasetRecord) -> list[Insight]:
    profile, df = record.profile, record.dataframe
    metrics = rank_metric_candidates(profile)
    if not metrics:
        return []

    metric = metrics[0]
    series = numeric_series(df[metric])
    result = compute_iqr_anomalies(series)
    if result is None:
        return []

    outlier_pct = result["outlier_share_pct"]
    outlier_count = result["outlier_count"]
    total_considered = result["total_considered"]

    # Only surface when outliers are materially significant — either by count
    # percentage OR because their aggregate contribution could distort totals.
    if outlier_pct < 1.0 and outlier_count < 10:
        return []

    # Calculate outlier contribution to the total
    total_sum = float(series.dropna().sum())
    outlier_sum = float(series.dropna()[(series.dropna() < result["lower_bound"]) | (series.dropna() > result["upper_bound"])].sum())
    outlier_contribution_pct = round(abs(outlier_sum) / abs(total_sum) * 100, 1) if total_sum != 0 else None

    # Describe direction
    high_outliers = series.dropna()[series.dropna() > result["upper_bound"]]
    low_outliers = series.dropna()[series.dropna() < result["lower_bound"]]
    direction_note = ""
    if len(high_outliers) > len(low_outliers):
        direction_note = f" Most outliers are unusually high (above {result['upper_bound']:,.2f})."
    elif len(low_outliers) > 0:
        direction_note = f" Some outliers are unusually low (below {result['lower_bound']:,.2f})."

    contribution_note = (
        f" These records account for approximately {outlier_contribution_pct}% of total {metric}."
        if outlier_contribution_pct is not None else ""
    )

    return [
        Insight(
            id=_new_id(),
            dataset_id=profile.id,
            category="anomaly",
            finding=(
                f"{outlier_pct}% of '{metric}' records ({outlier_count:,} of {total_considered:,}) "
                f"fall outside the expected range [{result['lower_bound']:,.2f} – {result['upper_bound']:,.2f}]."
                f"{direction_note}"
            ),
            evidence=Evidence(
                description=(
                    f"IQR analysis: Q1={result['q1']:,.2f}, Q3={result['q3']:,.2f}, IQR={result['iqr']:,.2f}. "
                    f"Expected range: [{result['lower_bound']:,.2f}, {result['upper_bound']:,.2f}]."
                    f"{contribution_note}"
                ),
                supporting_values={
                    "lower_bound": result["lower_bound"],
                    "upper_bound": result["upper_bound"],
                    "outlier_count": outlier_count,
                    "outlier_share_pct": outlier_pct,
                    "outlier_contribution_pct": outlier_contribution_pct,
                    "total_considered": total_considered,
                },
            ),
            calculation=(
                f"IQR = Q3({result['q3']:,.2f}) - Q1({result['q1']:,.2f}) = {result['iqr']:,.2f}; "
                f"bounds = [Q1 - 1.5×IQR, Q3 + 1.5×IQR]"
            ),
            interpretation=(
                f"These '{metric}' values are statistically unusual and may represent legitimate "
                f"bulk transactions, data entry errors, or exceptional business events. "
                f"{'Review the high-value outliers to confirm they reflect real business activity.' if len(high_outliers) > 0 else 'Review these records before relying on aggregate figures.'}"
            ),
            confidence_label=SourceLabel.CALCULATED,
        )
    ]


def generate_insights(record: DatasetRecord) -> list[Insight]:
    insights: list[Insight] = []
    insights.extend(_top_performer_and_concentration(record))
    insights.extend(_significant_change_insight(record))
    insights.extend(_anomaly_insight(record))
    insights.extend(_data_quality_insights(record))
    insights.extend(_distribution_insight(record))

    # When no confirmed business insight can be calculated, return an empty
    # list. The caller (dashboard / insights panel) handles the empty state
    # with a dedicated "No confirmed findings yet" message.
    #
    # DO NOT create a fake "Insufficient data" finding card here -- that
    # would appear as an executive finding, which it is not. Data-quality
    # / coverage warnings are surfaced separately in the UI.
    return insights
