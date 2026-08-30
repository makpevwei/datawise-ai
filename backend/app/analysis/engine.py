"""Analysis Engine -- deterministic calculations over a dataset.

Every number returned here is computed directly from the stored DataFrame.
The LLM (AI Reasoning Layer, not yet implemented) is never on the path to a
calculated value -- it may only narrate results this engine already
produced.
"""

import pandas as pd

from app.geography.countries import looks_like_country_column, resolve_country
from app.profiling.type_inference import CURRENCY_CHARS
from app.semantic.models import (
    Aggregation,
    AnalysisRequest,
    AnalysisResult,
    ChartSpec,
    ChartType,
    FilterCondition,
    SourceLabel,
)
from app.semantic.store import DatasetStore
from app.visualization.recommender import recommend_chart_type, recommend_scatter_or_table

MAX_CHART_ROWS = 100
# A donut/pie chart stops being readable well before this -- a slice per
# category only communicates share-of-total when there are a handful of
# them, not hundreds.
MAX_DONUT_PIE_SLICES = 12


class AnalysisError(Exception):
    """Client-input error: unknown dataset/column. Not a data-quality issue."""


def numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    cleaned = series.astype(str).str.replace(CURRENCY_CHARS, "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _require_column(df: pd.DataFrame, column: str, dataset_name: str) -> None:
    if column not in df.columns:
        raise AnalysisError(f"Column '{column}' not found in dataset '{dataset_name}'.")


def apply_filters(df: pd.DataFrame, filters: list[FilterCondition], dataset_name: str) -> pd.DataFrame:
    for f in filters:
        _require_column(df, f.column, dataset_name)
        col = df[f.column]
        if f.operator == "eq":
            df = df[col == f.value]
        elif f.operator == "ne":
            df = df[col != f.value]
        elif f.operator in ("gt", "gte", "lt", "lte"):
            numeric_col = numeric_series(col)
            value = float(f.value)
            if f.operator == "gt":
                df = df[numeric_col > value]
            elif f.operator == "gte":
                df = df[numeric_col >= value]
            elif f.operator == "lt":
                df = df[numeric_col < value]
            else:
                df = df[numeric_col <= value]
        elif f.operator == "contains":
            df = df[col.astype(str).str.contains(str(f.value), case=False, na=False)]
        elif f.operator == "in":
            values = f.value if isinstance(f.value, list) else [f.value]
            df = df[col.isin(values)]
    return df


def aggregate_scalar(df: pd.DataFrame, metric_column: str | None, aggregation: Aggregation) -> float | None:
    if aggregation == Aggregation.COUNT:
        return float(len(df)) if metric_column is None else float(df[metric_column].notna().sum())
    if metric_column is None:
        return None
    if aggregation == Aggregation.NUNIQUE:
        return float(df[metric_column].nunique())
    numeric = numeric_series(df[metric_column]).dropna()
    if len(numeric) == 0:
        return None
    if aggregation == Aggregation.SUM:
        return float(numeric.sum())
    if aggregation == Aggregation.MEAN:
        return float(numeric.mean())
    if aggregation == Aggregation.MEDIAN:
        return float(numeric.median())
    if aggregation == Aggregation.MIN:
        return float(numeric.min())
    if aggregation == Aggregation.MAX:
        return float(numeric.max())
    return None


def _apply_chart_override(
    request: AnalysisRequest, chart_type: ChartType, reason: str, dimension_cardinality: int | None = None
) -> tuple[ChartType, str]:
    """The user's explicit chart-type choice (Phase 4 continuation section
    18) generally wins over the auto-recommendation -- the frontend's
    compatibility rules (lib/chartCompatibility.ts) already constrain which
    choices it offers for the current field selection, so trusting it here
    doesn't risk an invalid combination silently rendering nothing.

    The one deliberate exception: a donut/pie request isn't honored as-is
    once the dimension has too many categories to show meaningfully as
    slices (e.g. "revenue by customer" across 2,000 customers) -- that
    substitutes a readable ranked bar chart instead, with the reason
    explaining the substitution, rather than either silently ignoring the
    request or rendering an unreadable wall of slivers.
    """
    if request.chart_type is None:
        return chart_type, reason
    if (
        request.chart_type in (ChartType.DONUT, ChartType.PIE)
        and dimension_cardinality is not None
        and dimension_cardinality > MAX_DONUT_PIE_SLICES
    ):
        return (
            ChartType.BAR,
            f"This comparison has {dimension_cardinality} categories, too many to show clearly as a "
            f"{request.chart_type.value} chart -- showing a ranked bar chart instead.",
        )
    return request.chart_type, f"You selected {request.chart_type.value.replace('_', ' ')}."


def _build_country_map_chart(
    request: AnalysisRequest, records: list[dict], value_col: str, reason: str
) -> ChartSpec:
    """Resolves each dimension value to a real country centroid (Phase 4
    continuation section 20-24) -- never fabricates a coordinate. A value
    that doesn't match the deterministic lookup is reported in
    unmatched_categories rather than silently dropped or guessed at."""
    points: list[dict] = []
    unmatched: list[str] = []
    for row in records:
        raw_label = str(row[str(request.dimension_column)])
        country = resolve_country(raw_label)
        if country is None:
            unmatched.append(raw_label)
            continue
        points.append(
            {
                "lat": country.lat,
                "lng": country.lng,
                "label": country.name,
                "value": row[value_col],
            }
        )
    return ChartSpec(
        chart_type=ChartType.MAP,
        dataset_id=request.dataset_id,
        x_column=request.dimension_column,
        y_column=value_col,
        aggregation=request.aggregation.value,
        filters=request.filters,
        reason="Country-level map using representative country coordinates.",
        data=points,
        unmatched_categories=unmatched or None,
    )


def _insufficient(request: AnalysisRequest, reason: str) -> AnalysisResult:
    return AnalysisResult(
        request=request,
        result_type="insufficient_data",
        columns_used=[],
        row_count_considered=0,
        calculation_description=reason,
        source=SourceLabel.INSUFFICIENT_DATA,
        chart_recommendation=ChartSpec(
            chart_type="insufficient_data", dataset_id=request.dataset_id, reason=reason
        ),
    )


def run_analysis(request: AnalysisRequest, store: DatasetStore) -> AnalysisResult:
    record = store.get(request.dataset_id)
    if record is None:
        raise AnalysisError(f"Dataset '{request.dataset_id}' not found.")

    df = record.dataframe
    name = record.profile.name

    for col in [request.metric_column, request.dimension_column, request.second_dimension_column, request.date_column]:
        if col is not None:
            _require_column(df, col, name)

    df = apply_filters(df, request.filters, name)
    if len(df) == 0:
        return _insufficient(request, "No rows remain after applying the requested filters.")

    columns_used = [
        c for c in [request.metric_column, request.dimension_column, request.second_dimension_column, request.date_column] if c
    ]

    # -- Second dimension branch (grouped/stacked): only meaningful together
    # with a first dimension and no date breakdown -- date+dim+seconddim
    # would be a 3-way cube the existing chart types can't render, so the
    # second dimension is simply not offered together with a date field
    # (enforced by the frontend's compatibility rules, section 17).
    if request.dimension_column is not None and request.second_dimension_column is not None and request.date_column is None:
        if request.aggregation == Aggregation.COUNT:
            grouped = df.groupby([request.dimension_column, request.second_dimension_column], observed=True)
            series = grouped.size() if request.metric_column is None else grouped[request.metric_column].apply(
                lambda s: s.notna().sum()
            )
        elif request.aggregation == Aggregation.NUNIQUE:
            if request.metric_column is None:
                return _insufficient(request, "A metric column is required for a distinct-count breakdown.")
            grouped = df.groupby([request.dimension_column, request.second_dimension_column], observed=True)
            series = grouped[request.metric_column].nunique()
        else:
            if request.metric_column is None:
                return _insufficient(request, f"A metric column is required to compute {request.aggregation.value}.")
            numeric = numeric_series(df[request.metric_column])
            series = numeric.groupby(
                [df[request.dimension_column], df[request.second_dimension_column]], observed=True
            ).agg(request.aggregation.value)

        series = series.dropna()
        if len(series) == 0:
            return _insufficient(request, "No groups could be computed from the available data.")

        # Cap total series (dimension1 x dimension2 combinations) so a
        # grouped/stacked chart never gets so busy it's unreadable -- keep
        # the top combinations by value, matching the top_n concept single-
        # dimension results already use.
        series = series.sort_values(ascending=False).head(min(len(series), request.top_n or MAX_CHART_ROWS))

        metric_label = request.metric_column or "records"
        value_col = f"{request.aggregation.value}_{metric_label}"
        records = [
            {str(request.dimension_column): k[0], str(request.second_dimension_column): k[1], value_col: float(v)}
            for k, v in series.items()
        ]

        distinct_series = len({r[str(request.second_dimension_column)] for r in records})
        chart_type = ChartType.STACKED_BAR if distinct_series > 4 else ChartType.GROUPED_BAR
        reason = (
            f"Two dimensions ({request.dimension_column}, {request.second_dimension_column}) is best shown as a "
            f"{'stacked' if chart_type == ChartType.STACKED_BAR else 'grouped'} bar chart."
        )
        chart_type, reason = _apply_chart_override(request, chart_type, reason, dimension_cardinality=len(records))
        return AnalysisResult(
            request=request,
            result_type="table",
            table=records,
            columns_used=columns_used,
            row_count_considered=len(df),
            calculation_description=(
                f"{request.aggregation.value}({metric_label}) grouped by {request.dimension_column} "
                f"and {request.second_dimension_column}"
            ),
            chart_recommendation=ChartSpec(
                chart_type=chart_type,
                dataset_id=request.dataset_id,
                x_column=request.dimension_column,
                y_column=value_col,
                series_column=request.second_dimension_column,
                aggregation=request.aggregation.value,
                filters=request.filters,
                reason=reason,
                data=records,
            ),
        )

    # -- Time series branch --
    if request.date_column is not None:
        dates = pd.to_datetime(df[request.date_column], errors="coerce")
        valid = dates.notna()
        if valid.sum() == 0:
            return _insufficient(
                request, f"Column '{request.date_column}' contains no parseable dates."
            )
        working = df.loc[valid].copy()
        working["_period"] = dates[valid].dt.to_period("M")

        group_cols = ["_period"] + ([request.dimension_column] if request.dimension_column else [])
        grouped = working.groupby(group_cols, observed=True)

        if request.aggregation == Aggregation.COUNT:
            series = grouped.size() if request.metric_column is None else grouped[request.metric_column].apply(
                lambda s: s.notna().sum()
            )
        elif request.aggregation == Aggregation.NUNIQUE:
            if request.metric_column is None:
                return _insufficient(request, "A metric column is required for a distinct-count time series.")
            series = grouped[request.metric_column].nunique()
        else:
            if request.metric_column is None:
                return _insufficient(request, f"A metric column is required to compute {request.aggregation.value}.")
            working["_metric"] = numeric_series(working[request.metric_column])
            series = grouped["_metric"].agg(request.aggregation.value)

        table = series.reset_index()
        value_col = table.columns[-1]
        table = table.rename(columns={"_period": "period", value_col: "value"})
        table["period"] = table["period"].astype(str)
        table = table.sort_values("period")

        if len(table) < 2:
            return _insufficient(
                request,
                f"Only {len(table)} time period(s) of data are available -- "
                "not enough to show a trend.",
            )

        records = table.to_dict(orient="records")
        chart_type, reason = recommend_chart_type(result_type="timeseries")
        metric_label = request.metric_column or "records"
        return AnalysisResult(
            request=request,
            result_type="timeseries",
            table=records,
            columns_used=columns_used,
            row_count_considered=len(working),
            calculation_description=(
                f"{request.aggregation.value}({metric_label}) grouped by month"
                + (f" and {request.dimension_column}" if request.dimension_column else "")
            ),
            chart_recommendation=ChartSpec(
                chart_type=chart_type,
                dataset_id=request.dataset_id,
                x_column="period",
                y_column="value",
                aggregation=request.aggregation.value,
                filters=request.filters,
                reason=reason,
                data=records[:MAX_CHART_ROWS],
            ),
        )

    # -- Grouped table branch --
    if request.dimension_column is not None:
        grouped = df.groupby(request.dimension_column, observed=True)

        if request.aggregation == Aggregation.COUNT:
            series = grouped.size() if request.metric_column is None else grouped[request.metric_column].apply(
                lambda s: s.notna().sum()
            )
        elif request.aggregation == Aggregation.NUNIQUE:
            if request.metric_column is None:
                return _insufficient(request, "A metric column is required for a distinct-count breakdown.")
            series = grouped[request.metric_column].nunique()
        else:
            if request.metric_column is None:
                return _insufficient(request, f"A metric column is required to compute {request.aggregation.value}.")
            numeric = numeric_series(df[request.metric_column])
            series = numeric.groupby(df[request.dimension_column], observed=True).agg(request.aggregation.value)

        series = series.dropna().sort_values(ascending=(request.sort == "asc"))
        is_ranking = request.top_n is not None
        if request.top_n:
            series = series.head(request.top_n)

        if len(series) == 0:
            return _insufficient(request, "No groups could be computed from the available data.")

        total = float(series.sum()) if request.aggregation in (Aggregation.SUM, Aggregation.COUNT, Aggregation.NUNIQUE) else None
        metric_label = request.metric_column or "records"
        records = []
        for k, v in series.items():
            row = {str(request.dimension_column): k, f"{request.aggregation.value}_{metric_label}": float(v)}
            if total:
                row["percentage_of_total"] = round(float(v) / total * 100, 2)
            records.append(row)

        chart_type, reason = recommend_chart_type(
            result_type="table",
            is_ranking=is_ranking,
            dimension_cardinality=len(series),
        )
        chart_type, reason = _apply_chart_override(request, chart_type, reason, dimension_cardinality=len(series))
        value_col = f"{request.aggregation.value}_{metric_label}"

        chart_spec = (
            _build_country_map_chart(request, records, value_col, reason)
            if chart_type == ChartType.MAP and looks_like_country_column(request.dimension_column or "")
            else ChartSpec(
                chart_type=chart_type,
                dataset_id=request.dataset_id,
                x_column=request.dimension_column,
                y_column=value_col,
                aggregation=request.aggregation.value,
                filters=request.filters,
                reason=reason,
                data=records[:MAX_CHART_ROWS],
            )
        )
        return AnalysisResult(
            request=request,
            result_type="table",
            table=records,
            columns_used=columns_used,
            row_count_considered=len(df),
            calculation_description=f"{request.aggregation.value}({metric_label}) grouped by {request.dimension_column}",
            chart_recommendation=chart_spec,
        )

    # -- Scalar branch --
    value = aggregate_scalar(df, request.metric_column, request.aggregation)
    if value is None:
        return _insufficient(
            request,
            f"Could not compute {request.aggregation.value} -- "
            f"'{request.metric_column}' has no usable numeric values.",
        )

    metric_label = request.metric_column or "records"
    chart_type, reason = recommend_chart_type(result_type="scalar")
    chart_type, reason = _apply_chart_override(request, chart_type, reason)
    return AnalysisResult(
        request=request,
        result_type="scalar",
        scalar_value=value,
        columns_used=columns_used,
        row_count_considered=len(df),
        calculation_description=f"{request.aggregation.value}({metric_label}) over {len(df)} row(s)",
        chart_recommendation=ChartSpec(
            chart_type=chart_type,
            dataset_id=request.dataset_id,
            y_column=request.metric_column,
            aggregation=request.aggregation.value,
            filters=request.filters,
            reason=reason,
            data=[{metric_label: value}],
        ),
    )


def compute_correlation(df: pd.DataFrame, column_a: str, column_b: str) -> dict:
    a = numeric_series(df[column_a])
    b = numeric_series(df[column_b])
    paired = pd.DataFrame({"a": a, "b": b}).dropna()
    chart_type, reason = recommend_scatter_or_table(len(paired))
    if len(paired) < 3:
        return {
            "coefficient": None,
            "pairs_considered": len(paired),
            "description": "Not enough overlapping numeric values to compute a correlation.",
            "chart_type": chart_type.value,
            "chart_reason": reason,
            "sample": [],
        }
    coefficient = float(paired["a"].corr(paired["b"]))
    return {
        "coefficient": round(coefficient, 4),
        "pairs_considered": len(paired),
        "description": f"Pearson correlation between {column_a} and {column_b} across {len(paired)} rows.",
        "chart_type": chart_type.value,
        "chart_reason": reason,
        "sample": paired.head(MAX_CHART_ROWS).rename(columns={"a": column_a, "b": column_b}).to_dict(orient="records"),
    }


def compute_distribution(df: pd.DataFrame, column: str, bins: int = 10) -> dict:
    series = df[column].dropna()
    if len(series) == 0:
        return {"kind": "empty", "buckets": []}

    if pd.api.types.is_numeric_dtype(series):
        counts, edges = pd.cut(series, bins=bins, retbins=True, duplicates="drop").value_counts().sort_index(), None
        buckets = [
            {"range": str(interval), "count": int(count)}
            for interval, count in counts.items()
        ]
        return {"kind": "numeric", "buckets": buckets}

    value_counts = series.astype(str).value_counts().head(20)
    buckets = [{"value": v, "count": int(c)} for v, c in value_counts.items()]
    return {"kind": "categorical", "buckets": buckets}
