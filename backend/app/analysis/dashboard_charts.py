"""Deterministic default dashboard chart selection.

Produces up to 3 ready-to-render ChartSpec objects for the Management
Dashboard without requiring any user interaction. Charts are selected
based on what the dataset actually contains -- never invented.

Priority:
  1. Trend chart  -- if a date column + eligible metric exist
  2. Comparison   -- if a categorical dimension + eligible metric exist
  3. Composition  -- if a low-cardinality categorical dimension exists (donut)
  4. KPI scalar   -- fallback for numeric-only datasets (e.g. fact tables)

All metrics are validated through rank_metric_candidates() so identifiers,
keys, IDs and percentage-only columns are excluded automatically.

Also provides discover_cross_dataset_charts(): a star-schema fact table
often has no chart-worthy dimension of its own (e.g. a Sales table with only
a RegionKey/DateKey foreign key, the real "Region"/"Date" columns living in
separate dimension tables) -- no chart above can ever surface "Sales by
Region" from that one table alone. When multiple datasets are selected,
this reuses the existing relationship-detection and join engines (never a
new one) to safely join a fact table to its dimension table and discover
charts from the *joined* result too, e.g. an automatic "Sales by Region"
trend/comparison chart the individual tables could never produce on their
own.
"""

from app.analysis.engine import AnalysisError, run_analysis
from app.analysis.kpi_discovery import (
    deterministic_aggregation,
    rank_dimension_candidates,
    rank_metric_candidates,
    strip_currency_code_suffix,
)
from app.relationships.joins import JoinError, perform_join
from app.relationships.service import detect_relationships
from app.semantic.models import (
    Aggregation,
    AnalysisRequest,
    ChartSpec,
    ChartType,
    ConfidenceLevel,
    JoinRequest,
    JoinType,
)
from app.semantic.store import DatasetRecord, DatasetStore

# Maximum categories for a readable comparison/composition chart
MAX_COMPARISON_CATEGORIES = 20
MAX_COMPOSITION_SLICES = 7


def _eligible_agg(metric_col: str) -> Aggregation:
    """Return the correct aggregation for a metric column -- delegates to
    kpi_discovery's shared deterministic heuristic (percentage/rate/margin/
    age/tenure/years fields use MEAN, everything else uses SUM) so a
    column's aggregation choice is consistent between a KPI card and a
    chart, not two independently-drifting keyword lists."""
    return deterministic_aggregation(metric_col)


def _chart_title(aggregation: str | None, metric: str | None, dimension: str | None, chart_type: str) -> str:
    """Build a human-readable chart title from the analytical components."""
    agg_map = {
        "sum": "Total", "mean": "Average", "median": "Median",
        "min": "Minimum", "max": "Maximum", "count": "Count of",
        "nunique": "Distinct",
    }
    agg_label = agg_map.get(aggregation or "", "")

    # Clean the metric name — strip a currency-code suffix (e.g. "..._NGN")
    # before the aggregation prefix kpi_discovery already added
    raw_metric = strip_currency_code_suffix(metric or "").replace("_", " ")
    # Remove leading "sum_" / "mean_" prefix that the analysis engine injects into y_column
    raw_metric = raw_metric.replace("sum_", "").replace("mean_", "").replace("nunique_", "").strip()
    metric_label = raw_metric.title()
    dim_label = (dimension or "").replace("_", " ").title() if dimension else ""

    # A column whose own raw name already starts with the aggregation word
    # (e.g. a real "Average_Unit_Cost_NGN" column) would otherwise double
    # up into "Average Average Unit Cost by Category" -- found live, the
    # same bug as kpi_discovery._kpi_display_name, independently here
    # since chart titles are built separately. Drop the prefix when the
    # metric name already carries it.
    if agg_label and metric_label.lower().startswith(agg_label.lower()):
        agg_label = ""

    if chart_type in ("line", "time_series"):
        return f"Monthly {metric_label} Trend" if metric_label else "Trend Over Time"
    if dim_label:
        return f"{agg_label} {metric_label} by {dim_label}".strip()
    if metric_label:
        return f"{agg_label} {metric_label}".strip()
    return "Business Performance"


def discover_dashboard_charts(record: DatasetRecord) -> list[ChartSpec]:
    """Return up to 3 default charts for the Management Dashboard."""
    profile = record.profile
    charts: list[ChartSpec] = []
    seen: set[tuple[str | None, str | None, str]] = set()

    metrics = rank_metric_candidates(profile)
    dimensions = rank_dimension_candidates(profile)
    date_cols = profile.date_columns

    if not metrics:
        return []

    primary_metric = metrics[0]
    agg = _eligible_agg(primary_metric)

    # Source lineage for every chart
    source_name = profile.name
    source_sheet = profile.sheet_name

    def _annotate(spec: ChartSpec, metric_col: str | None = None, dim: str | None = None) -> ChartSpec:
        """Add title and source lineage to a ChartSpec."""
        spec.dataset_name = source_name
        spec.dataset_sheet = source_sheet
        # Use the raw metric column name (not the aggregated y_column like "sum_Sales Amount")
        spec.title = _chart_title(spec.aggregation, metric_col or spec.y_column, dim, spec.chart_type.value)
        return spec

    # Chart 1 — Trend
    if date_cols:
        date_col = date_cols[0]
        request = AnalysisRequest(
            dataset_id=profile.id,
            metric_column=primary_metric,
            aggregation=agg,
            date_column=date_col,
        )
        try:
            result = run_analysis(request, _store_proxy(record))
        except AnalysisError:
            result = None

        if result and result.chart_recommendation and result.result_type == "timeseries":
            spec = result.chart_recommendation
            fp = (spec.y_column, spec.x_column, spec.chart_type.value)
            if fp not in seen and spec.data and len(spec.data) >= 2:
                seen.add(fp)
                charts.append(_annotate(spec, primary_metric))

    # Chart 2 — Comparison
    comparison_dim_used: str | None = None
    if dimensions:
        dim = dimensions[0]
        df = record.dataframe
        cardinality = df[dim].nunique() if dim in df.columns else 0

        if 2 <= cardinality <= MAX_COMPARISON_CATEGORIES:
            request = AnalysisRequest(
                dataset_id=profile.id,
                metric_column=primary_metric,
                aggregation=agg,
                dimension_column=dim,
                top_n=10,
                sort="desc",
            )
            try:
                result = run_analysis(request, _store_proxy(record))
            except AnalysisError:
                result = None

            if result and result.chart_recommendation:
                spec = result.chart_recommendation
                fp = (spec.y_column, spec.x_column, spec.chart_type.value)
                if fp not in seen and spec.data and len(spec.data) >= 2:
                    seen.add(fp)
                    charts.append(_annotate(spec, primary_metric, dim))
                    comparison_dim_used = dim

    # Chart 3 — Second dimension or composition. Room for a 3rd chart exists
    # whenever trend + comparison didn't already fill both slots above -- NOT
    # just when fewer than 2 have been found so far, otherwise a dataset with
    # both a working trend and comparison chart (the common case) would never
    # get its 3rd/composition chart even though there's a slot free for it.
    if len(charts) < 3 and dimensions:
        second_metric = metrics[1] if len(metrics) > 1 else primary_metric
        second_dim = dimensions[1] if len(dimensions) > 1 else (dimensions[0] if dimensions else None)
        first_dim = comparison_dim_used

        if second_dim and second_dim != first_dim:
            df = record.dataframe
            cardinality = df[second_dim].nunique() if second_dim in df.columns else 0

            if 2 <= cardinality <= MAX_COMPOSITION_SLICES:
                request = AnalysisRequest(
                    dataset_id=profile.id,
                    metric_column=second_metric,
                    aggregation=_eligible_agg(second_metric),
                    dimension_column=second_dim,
                    chart_type=ChartType.DONUT,
                )
                try:
                    result = run_analysis(request, _store_proxy(record))
                except AnalysisError:
                    result = None

                if result and result.chart_recommendation:
                    spec = result.chart_recommendation
                    fp = (spec.y_column, spec.x_column, spec.chart_type.value)
                    if fp not in seen and spec.data and len(spec.data) >= 2:
                        seen.add(fp)
                        charts.append(_annotate(spec, second_metric, second_dim))

    # Fallback — KPI scalar cards
    if not charts and metrics:
        for metric in metrics[:2]:
            metric_agg = _eligible_agg(metric)
            request = AnalysisRequest(
                dataset_id=profile.id,
                metric_column=metric,
                aggregation=metric_agg,
            )
            try:
                result = run_analysis(request, _store_proxy(record))
            except AnalysisError:
                continue

            if result and result.chart_recommendation and result.result_type == "scalar":
                spec = result.chart_recommendation
                fp = (spec.y_column, spec.x_column, spec.chart_type.value)
                if fp not in seen:
                    seen.add(fp)
                    charts.append(_annotate(spec, metric))

    return charts[:3]


class _StoreProxy:
    """Minimal DatasetStore interface wrapping a single DatasetRecord.

    run_analysis only needs store.get(dataset_id) -- this proxy satisfies
    that without requiring the full DatasetStore.
    """
    def __init__(self, record: DatasetRecord) -> None:
        self._record = record

    def get(self, dataset_id: str) -> DatasetRecord | None:  # type: ignore[override]
        if dataset_id == self._record.profile.id:
            return self._record
        return None


def _store_proxy(record: DatasetRecord) -> "_StoreProxy":
    return _StoreProxy(record)


# Cap how many relationships we'll actually join -- selecting many datasets
# together can produce many HIGH-confidence pairs, and each join + chart
# discovery does real work (a join computation, then up to 3 analysis runs).
MAX_AUTO_JOINS = 2


def discover_cross_dataset_charts(records: list[DatasetRecord], store: DatasetStore) -> list[ChartSpec]:
    """Safely join related datasets and discover dashboard charts from the
    joined result too -- e.g. a Sales fact table with only a RegionKey
    foreign key gets a real "Sales by Region" chart once joined to its
    Region dimension table, which neither table could produce alone.

    Reuses the existing relationship-detection and join engines end to end,
    never a new one:
      - Only ever attempts relationships detect_relationships scored HIGH
        confidence -- "verified" in the sense that the existing evidence-based
        scoring (uniqueness, value overlap, cardinality) backs it, not just a
        name match.
      - perform_join's own safety checks still apply unmodified: a
        many-to-many join is refused (JoinError) rather than silently
        multiplying rows, so a risky pair is simply skipped here, never
        forced through.
      - Always requests an INNER join regardless of what's suggested --
        unlike a user-initiated join (reviewed before creation), this runs
        unattended on every dashboard load, so only genuinely matched rows
        should ever feed an automatically-generated chart; a left/right/full
        join could silently introduce unmatched/null rows into a chart the
        user never reviewed.
      - perform_join() ITSELF always mints a new derived dataset -- its
        duplicate-join prevention lives in the /relationships/join API
        endpoint instead (a Postgres content-hash lookup, since ownership
        metadata lives there, not in the file-based store this module
        works against). Calling perform_join() directly, as this function
        must, would bypass that and create a fresh duplicate on every
        dashboard load. So this checks the file store's own persisted
        JoinLineage for an equivalent prior join first and reuses it,
        never calling perform_join() twice for the same pair.
    """
    if len(records) < 2:
        return []

    try:
        suggestions = detect_relationships(records)
    except Exception:  # noqa: BLE001 -- relationship detection failing must not break the dashboard
        return []

    high_confidence = [s for s in suggestions if s.confidence == ConfidenceLevel.HIGH]

    charts: list[ChartSpec] = []
    attempted_pairs: set[frozenset[str]] = set()

    for suggestion in high_confidence:
        if len(attempted_pairs) >= MAX_AUTO_JOINS:
            break
        pair = frozenset({suggestion.left_dataset_id, suggestion.right_dataset_id})
        if pair in attempted_pairs:
            continue
        attempted_pairs.add(pair)

        request = JoinRequest(
            left_dataset_id=suggestion.left_dataset_id,
            left_column=suggestion.left_column,
            right_dataset_id=suggestion.right_dataset_id,
            right_column=suggestion.right_column,
            join_type=JoinType.INNER,
        )

        existing = _find_existing_join(store, request)
        if existing is not None:
            charts.extend(discover_dashboard_charts(existing))
            continue

        try:
            result = perform_join(store, request, created_by_user_id="dashboard-auto-join")
        except JoinError:
            continue  # e.g. refused as many-to-many -- not safe to auto-join

        joined_record = store.get(result.new_dataset_id)
        if joined_record is None:
            # A scoped store's ownership snapshot won't include a dataset
            # this very call just created -- extend it (see
            # ScopedDatasetStore.grant's docstring) and retry once. A plain
            # DatasetStore (e.g. in tests) has no such concept and would
            # already have succeeded above.
            grant = getattr(store, "grant", None)
            if callable(grant):
                grant(result.new_dataset_id)
                joined_record = store.get(result.new_dataset_id)
        if joined_record is None:
            continue
        charts.extend(discover_dashboard_charts(joined_record))

    return charts


def _find_existing_join(store: DatasetStore, request: JoinRequest) -> DatasetRecord | None:
    """Self-contained equivalent of the /relationships/join endpoint's
    Postgres content-hash dedup, but against the file store's own persisted
    JoinLineage -- same source dataset ids + same keys + same join type =>
    the same derived dataset, so perform_join() is never called twice for
    an identical pair.

    Prefers ScopedDatasetStore.all_records_derived_from_owned() when
    available: an auto-join has no Postgres Dataset row of its own (see
    ScopedDatasetStore.grant's docstring), so plain all_records() can never
    find it again on a LATER request, and every dashboard load would mint a
    fresh duplicate file otherwise.
    """
    lineage_scan = getattr(store, "all_records_derived_from_owned", None)
    candidates = lineage_scan() if callable(lineage_scan) else store.all_records()
    for record in candidates:
        lineage = record.profile.lineage
        if lineage is None:
            continue
        if (
            lineage.left_dataset_id == request.left_dataset_id
            and lineage.left_column == request.left_column
            and lineage.right_dataset_id == request.right_dataset_id
            and lineage.right_column == request.right_column
            and lineage.join_type == request.join_type
        ):
            return record
    return None
