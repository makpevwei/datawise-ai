"""Explicit agent tools.

Every tool here is a thin, structured wrapper around the Phase 2
deterministic engine (or the document store) -- none of them perform
their own business-number calculations. The agent (app/agent/planner.py)
can only affect the world through these functions; it never gets raw
filesystem or dataframe access.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agent.web_research import WebResearchError, WebResearchNotConfiguredError, search_web
from app.ai.base import LLMProvider
from app.ai.types import ToolSchema
from app.analysis.engine import AnalysisError, compute_correlation, run_analysis
from app.analysis.insights import compute_iqr_anomalies, generate_insights, numeric_series
from app.analysis.kpi_discovery import discover_kpis
from app.config import Settings
from app.documents.store import DocumentStore
from app.geography.countries import looks_like_country_column
from app.relationships.joins import JoinError, perform_join
from app.relationships.service import detect_relationships
from app.semantic.models import (
    Aggregation,
    AnalysisRequest,
    ChartType,
    DatasetProfile,
    FilterCondition,
    JoinRequest,
    JoinType,
)
from app.semantic.resolver import Role, resolve_column
from app.semantic.store import DatasetRecord, DatasetStore

MAX_GENERATE_DASHBOARD_ITEMS = 6


class ToolExecutionError(Exception):
    """A tool ran but could not satisfy the request -- reported back to the
    LLM as a tool_result with is_error=True, never raised past the agent."""


@dataclass
class ResearchBudget:
    """Per-question caps on web research so a single question can never
    trigger an uncontrolled loop of external calls. Reset per run_agent()
    call -- see app/agent/planner.py."""

    max_queries: int
    max_tool_calls: int
    queries_used: int = 0
    tool_calls_used: int = 0


@dataclass
class ToolContext:
    dataset_store: DatasetStore
    document_store: DocumentStore
    settings: Settings | None = None
    research_budget: ResearchBudget | None = None
    # Only used to let generate_dashboard's KPI discovery ask the LLM to
    # classify a column's aggregation semantics (sum vs mean) -- see
    # app/analysis/kpi_semantics.py. None is a completely valid value (KPI
    # discovery has a deterministic fallback); this is never used to
    # generate or alter an actual numeric result.
    llm_provider: LLMProvider | None = None


@dataclass
class Tool:
    schema: ToolSchema
    handler: Callable[[dict[str, Any], ToolContext], dict[str, Any]]


def _filters_from_dicts(raw: list[dict] | None) -> list[FilterCondition]:
    return [FilterCondition(**f) for f in (raw or [])]


def _resolve_dataset_id(ctx: ToolContext, dataset_id: str) -> str:
    """The LLM is given each dataset's real id alongside its display name
    (see planner._format_datasets), but a model sometimes uses the name
    instead (e.g. 'orders.csv') -- which would otherwise fail every tool
    call outright even though the dataset genuinely exists. Falls back to
    a case-insensitive name match (with or without a file extension)
    before giving up, the same forgiving-resolution philosophy as
    app/semantic/resolver.py, just one level up (dataset identity instead
    of column identity)."""
    if ctx.dataset_store.get(dataset_id) is not None:
        return dataset_id
    normalized = dataset_id.strip().lower()
    stem = normalized.rsplit(".", 1)[0]
    for summary in ctx.dataset_store.list_summaries():
        summary_name = summary.name.strip().lower()
        if summary_name == normalized or summary_name.rsplit(".", 1)[0] == stem:
            return summary.id
    return dataset_id


def _get_record_or_raise(ctx: ToolContext, dataset_id: str) -> DatasetRecord:
    record = ctx.dataset_store.get(_resolve_dataset_id(ctx, dataset_id))
    if record is None:
        available = ", ".join(f"{s.name} (id={s.id})" for s in ctx.dataset_store.list_summaries())
        raise ToolExecutionError(f"Dataset '{dataset_id}' not found. Available datasets: {available}.")
    return record


def _resolve_column_arg(value: str | None, role: Role, profile: DatasetProfile, notes: list[str]) -> str | None:
    """Best-effort natural-language -> real-column resolution for a single
    tool argument (see app/semantic/resolver.py). Exact matches pass
    through untouched at zero cost -- this only does any work when the
    caller (LLM or a future deterministic fast-path) supplied a name that
    isn't already a literal column in the dataset, tolerating naming-
    convention differences, business synonyms, and typos instead of
    failing the whole tool call outright. Appends a human-readable note to
    `notes` whenever the mapping wasn't a trivial one, and raises
    ToolExecutionError with the closest real columns when nothing can be
    resolved confidently, so the caller can retry instead of getting a bare
    'column not found'."""
    if value is None:
        return None
    if any(c.name == value for c in profile.columns):
        return value

    resolution = resolve_column(value, profile, role)
    if not resolution.resolved:
        available = ", ".join(c.name for c in profile.columns)
        suggestion = f" Closest columns: {', '.join(resolution.alternatives)}." if resolution.alternatives else ""
        raise ToolExecutionError(
            f"'{value}' doesn't match a column in this dataset.{suggestion} Available columns: {available}."
        )
    if resolution.note:
        notes.append(resolution.note)
    return resolution.column


# -- Dataset inspection -------------------------------------------------


def _list_datasets(args: dict, ctx: ToolContext) -> dict:
    return {"datasets": [s.model_dump(mode="json") for s in ctx.dataset_store.list_summaries()]}


def _inspect_dataset(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    return record.profile.model_dump(mode="json")


def _inspect_schema(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    return {
        "dataset_id": record.profile.id,
        "name": record.profile.name,
        "row_count": record.profile.row_count,
        "columns": [
            {"name": c.name, "type": c.inferred_type.value, "missing_percentage": c.missing_percentage}
            for c in record.profile.columns
        ],
    }


def _find_relationships(args: dict, ctx: ToolContext) -> dict:
    records = ctx.dataset_store.all_records()
    dataset_ids = args.get("dataset_ids")
    if dataset_ids:
        resolved_ids = {_resolve_dataset_id(ctx, d) for d in dataset_ids}
        records = [r for r in records if r.profile.id in resolved_ids]
    suggestions = detect_relationships(records)
    return {"relationships": [s.model_dump(mode="json") for s in suggestions]}


def _join_datasets(args: dict, ctx: ToolContext) -> dict:
    request = JoinRequest(
        left_dataset_id=_resolve_dataset_id(ctx, args["left_dataset_id"]),
        left_column=args["left_column"],
        right_dataset_id=_resolve_dataset_id(ctx, args["right_dataset_id"]),
        right_column=args["right_column"],
        join_type=JoinType(args.get("join_type", "inner")),
        allow_fan_out=bool(args.get("allow_fan_out", False)),
    )
    try:
        # ToolContext is deliberately user-agnostic (see ScopedDatasetStore's
        # docstring) -- the join's lineage still needs *some* creator id for
        # provenance, but authorization/scoping already happened one layer
        # up (the endpoint only ever hands the agent a store scoped to the
        # requesting user), so a fixed sentinel is correct here, not a gap.
        result = perform_join(ctx.dataset_store, request, created_by_user_id="agent")
    except JoinError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return result.model_dump(mode="json")


# -- Analysis -------------------------------------------------------------


def _metric_role(aggregation: str | None) -> Role:
    """"nunique" is the standard, correct way to count distinct entities --
    counting distinct values of an *identifier* column (Customer_ID,
    Order_ID, ...) is the single most common use of it, so role="measure"
    (which hard-excludes anything not ColumnType.NUMERIC, see
    app/semantic/resolver.py's _role_incompatible) would wrongly reject the
    exact column a "how many distinct X" question needs, falling back to
    fuzzy scoring and silently substituting a real but wrong numeric
    column instead. Found live: "how many distinct customers" resolved to
    Customer_Order_Number (nunique of that returns each customer's own max
    order count, e.g. 14) instead of Customer_ID (the real answer, in the
    thousands) -- role="any" for nunique lets the resolver's own type
    checks (still real, just not this hard gate) do the rest."""
    return "any" if aggregation == "nunique" else "measure"


def _calculate_metric(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    notes: list[str] = []
    metric_column = _resolve_column_arg(args.get("metric_column"), _metric_role(args.get("aggregation")), record.profile, notes)
    request = AnalysisRequest(
        dataset_id=record.profile.id,
        metric_column=metric_column,
        aggregation=Aggregation(args.get("aggregation", "sum")),
        filters=_filters_from_dicts(args.get("filters")),
    )
    try:
        result = run_analysis(request, ctx.dataset_store)
    except AnalysisError as exc:
        raise ToolExecutionError(str(exc)) from exc
    payload = result.model_dump(mode="json")
    if notes:
        payload["interpretation_notes"] = notes
    return payload


def _group_and_aggregate(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    notes: list[str] = []
    metric_column = _resolve_column_arg(args.get("metric_column"), _metric_role(args.get("aggregation")), record.profile, notes)
    dimension_column = _resolve_column_arg(args["dimension_column"], "dimension", record.profile, notes)
    second_dimension_column = _resolve_column_arg(args.get("second_dimension_column"), "dimension", record.profile, notes)
    request = AnalysisRequest(
        dataset_id=record.profile.id,
        metric_column=metric_column,
        aggregation=Aggregation(args.get("aggregation", "sum")),
        dimension_column=dimension_column,
        second_dimension_column=second_dimension_column,
        top_n=args.get("top_n"),
        sort=args.get("sort", "desc"),
        filters=_filters_from_dicts(args.get("filters")),
    )
    try:
        result = run_analysis(request, ctx.dataset_store)
    except AnalysisError as exc:
        raise ToolExecutionError(str(exc)) from exc
    payload = result.model_dump(mode="json")
    if notes:
        payload["interpretation_notes"] = notes
    return payload


def _compare_periods(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    notes: list[str] = []
    metric_column = _resolve_column_arg(args.get("metric_column"), "measure", record.profile, notes)
    date_column = _resolve_column_arg(args["date_column"], "date", record.profile, notes)
    request = AnalysisRequest(
        dataset_id=record.profile.id,
        metric_column=metric_column,
        aggregation=Aggregation(args.get("aggregation", "sum")),
        date_column=date_column,
        filters=_filters_from_dicts(args.get("filters")),
    )
    try:
        result = run_analysis(request, ctx.dataset_store)
    except AnalysisError as exc:
        raise ToolExecutionError(str(exc)) from exc

    if result.result_type != "timeseries" or result.table is None:
        payload = {
            "result_type": result.result_type,
            "message": result.calculation_description,
        }
        if notes:
            payload["interpretation_notes"] = notes
        return payload

    by_period = {row["period"]: row["value"] for row in result.table}
    period_a, period_b = args["period_a"], args["period_b"]
    value_a, value_b = by_period.get(period_a), by_period.get(period_b)
    if value_a is None or value_b is None:
        return {
            "error": "One or both periods not found in the data (format YYYY-MM).",
            "available_periods": sorted(by_period.keys()),
        }

    absolute_change = round(value_b - value_a, 2)
    pct_change = round((value_b - value_a) / value_a * 100, 2) if value_a else None
    payload = {
        "period_a": period_a,
        "value_a": value_a,
        "period_b": period_b,
        "value_b": value_b,
        "absolute_change": absolute_change,
        "percentage_change": pct_change,
        "source": "CALCULATED",
    }
    if notes:
        payload["interpretation_notes"] = notes
    return payload


def _detect_anomalies(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    notes: list[str] = []
    metric_column = _resolve_column_arg(args.get("metric_column"), "measure", record.profile, notes)
    if metric_column:
        result = compute_iqr_anomalies(numeric_series(record.dataframe[metric_column]))
        if result is None:
            payload = {"anomalies_found": False, "metric_column": metric_column}
        else:
            payload = {"anomalies_found": True, "metric_column": metric_column, **result}
        if notes:
            payload["interpretation_notes"] = notes
        return payload

    insights = [i for i in generate_insights(record) if i.category == "anomaly"]
    if not insights:
        return {"anomalies_found": False}
    return {"anomalies_found": True, "insights": [i.model_dump(mode="json") for i in insights]}


def _correlate(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    notes: list[str] = []
    column_a = _resolve_column_arg(args["column_a"], "measure", record.profile, notes)
    column_b = _resolve_column_arg(args["column_b"], "measure", record.profile, notes)
    payload = compute_correlation(record.dataframe, column_a, column_b)
    if notes:
        payload["interpretation_notes"] = notes
    return payload


# -- Visualization ----------------------------------------------------------


def _generate_chart(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])
    notes: list[str] = []
    metric_column = _resolve_column_arg(args.get("metric_column"), "measure", record.profile, notes)
    dimension_column = _resolve_column_arg(args.get("dimension_column"), "dimension", record.profile, notes)
    second_dimension_column = _resolve_column_arg(args.get("second_dimension_column"), "dimension", record.profile, notes)
    date_column = _resolve_column_arg(args.get("date_column"), "date", record.profile, notes)

    requested_chart_type = args.get("chart_type")
    if requested_chart_type == "map" and not looks_like_country_column(dimension_column or ""):
        # 'map' only actually produces geo points when the dimension is a
        # real country column (see app/analysis/engine.py's
        # _build_country_map_chart) -- otherwise the engine falls through
        # to a normal chart with the misleading 'map' label. Drop the
        # override rather than let the agent request a broken chart; the
        # engine's own auto-recommendation is still a safe fallback.
        requested_chart_type = None
        notes.append("'map' isn't available for this dimension (no recognized country column) -- used the recommended chart instead.")

    request = AnalysisRequest(
        dataset_id=record.profile.id,
        metric_column=metric_column,
        aggregation=Aggregation(args.get("aggregation", "sum")),
        dimension_column=dimension_column,
        second_dimension_column=second_dimension_column,
        date_column=date_column,
        top_n=args.get("top_n"),
        sort=args.get("sort", "desc"),
        filters=_filters_from_dicts(args.get("filters")),
        chart_type=ChartType(requested_chart_type) if requested_chart_type else None,
    )
    try:
        result = run_analysis(request, ctx.dataset_store)
    except AnalysisError as exc:
        raise ToolExecutionError(str(exc)) from exc
    if result.chart_recommendation is None:
        payload = {"chart": None, "message": result.calculation_description}
    else:
        payload = {"chart": result.chart_recommendation.model_dump(mode="json"), "calculation_description": result.calculation_description}
    if notes:
        payload["interpretation_notes"] = notes
    return payload


def _generate_dashboard(args: dict, ctx: ToolContext) -> dict:
    record = _get_record_or_raise(ctx, args["dataset_id"])

    kpis = discover_kpis(record, llm_provider=ctx.llm_provider)[:MAX_GENERATE_DASHBOARD_ITEMS]
    charts: list[dict] = []
    for kpi in kpis:
        request = AnalysisRequest(
            dataset_id=record.profile.id,
            metric_column=kpi.metric_column,
            aggregation=kpi.aggregation,
            dimension_column=kpi.dimension_column,
            date_column=kpi.date_column,
        )
        try:
            result = run_analysis(request, ctx.dataset_store)
        except AnalysisError:
            continue
        charts.append(
            {
                "title": kpi.name,
                "result_type": result.result_type,
                "scalar_value": result.scalar_value,
                "table": result.table,
                "chart": result.chart_recommendation.model_dump(mode="json") if result.chart_recommendation else None,
            }
        )

    return {"dataset_id": record.profile.id, "kpi_suggestions": [k.model_dump(mode="json") for k in kpis], "charts": charts}


# -- Documents / RAG ----------------------------------------------------------


def _search_documents(args: dict, ctx: ToolContext) -> dict:
    results = ctx.document_store.retrieve(
        query=args["query"], top_k=args.get("top_k", 5), document_ids=args.get("document_ids")
    )
    return {"results": [r.model_dump(mode="json") for r in results]}


def _retrieve_document_evidence(args: dict, ctx: ToolContext) -> dict:
    chunk = ctx.document_store.get_chunk(args["document_id"], args["chunk_id"])
    if chunk is None:
        raise ToolExecutionError(f"Chunk '{args['chunk_id']}' not found in document '{args['document_id']}'.")
    return chunk.model_dump(mode="json")


# -- Web research ---------------------------------------------------------


def _web_research(args: dict, ctx: ToolContext) -> dict:
    if ctx.settings is None:
        raise ToolExecutionError("Web research is not available in this context.")

    budget = ctx.research_budget
    if budget is not None:
        if budget.tool_calls_used >= budget.max_tool_calls:
            raise ToolExecutionError(
                f"Web research tool-call limit ({budget.max_tool_calls}) reached for this question."
            )
        if budget.queries_used >= budget.max_queries:
            raise ToolExecutionError(f"Web research query limit ({budget.max_queries}) reached for this question.")
        budget.tool_calls_used += 1
        budget.queries_used += 1

    max_results = min(int(args.get("max_results", 5)), ctx.settings.max_research_sources)
    try:
        results = search_web(args["query"], ctx.settings, max_results=max_results)
    except (WebResearchNotConfiguredError, WebResearchError) as exc:
        raise ToolExecutionError(str(exc)) from exc

    return {"query": args["query"], "results": [dataclasses.asdict(r) for r in results]}


# -- Verification -------------------------------------------------------------


def verify_claim_tool(args: dict, ctx: ToolContext, tool_invocations: list) -> dict:
    """Special-cased handler: needs this turn's tool_invocations, which the
    generic Tool.handler(args, ctx) signature doesn't carry. Dispatched
    explicitly by the planner instead of going through TOOLS[name].handler.
    """
    from app.agent.schemas import EvidenceLabel
    from app.agent.verification import verify_finding_label

    claimed_label = EvidenceLabel(args.get("claimed_label", "AI_INTERPRETATION"))
    relevant = tool_invocations
    tool_call_ids = args.get("tool_call_ids")
    if tool_call_ids:
        relevant = [t for t in tool_invocations if t.id in tool_call_ids]

    final_label, note = verify_finding_label(args["claim_text"], claimed_label, relevant)
    return {
        "claim_text": args["claim_text"],
        "claimed_label": claimed_label.value,
        "verified_label": final_label.value,
        "note": note,
    }


TOOLS: dict[str, Tool] = {
    "list_datasets": Tool(
        schema=ToolSchema(
            name="list_datasets",
            description="List every dataset currently uploaded, with row/column counts and quality rating.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        handler=_list_datasets,
    ),
    "inspect_dataset": Tool(
        schema=ToolSchema(
            name="inspect_dataset",
            description="Get the full profile of one dataset: columns, types, stats, and data-quality findings.",
            parameters={
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}},
                "required": ["dataset_id"],
                "additionalProperties": False,
            },
        ),
        handler=_inspect_dataset,
    ),
    "inspect_schema": Tool(
        schema=ToolSchema(
            name="inspect_schema",
            description="Get just the column names and types of a dataset (lighter than inspect_dataset).",
            parameters={
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}},
                "required": ["dataset_id"],
                "additionalProperties": False,
            },
        ),
        handler=_inspect_schema,
    ),
    "find_relationships": Tool(
        schema=ToolSchema(
            name="find_relationships",
            description="Discover possible join relationships between datasets, with confidence and reasons.",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional subset; omit for all."}
                },
                "additionalProperties": False,
            },
        ),
        handler=_find_relationships,
    ),
    "join_datasets": Tool(
        schema=ToolSchema(
            name="join_datasets",
            description=(
                "Join two datasets on the given columns, producing a new combined dataset. Before "
                "calling this, prefer inspecting cardinality with find_relationships/inspect_schema. "
                "If both join columns contain duplicate values (many-to-many), this call is refused "
                "with an estimated row-multiplication count rather than performed silently -- only "
                "set allow_fan_out=true if that fan-out is genuinely intended."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "left_dataset_id": {"type": "string"},
                    "left_column": {"type": "string"},
                    "right_dataset_id": {"type": "string"},
                    "right_column": {"type": "string"},
                    "join_type": {"type": "string", "enum": ["inner", "left", "right"]},
                    "allow_fan_out": {
                        "type": "boolean",
                        "description": "Set true only to explicitly confirm a many-to-many join after seeing the refusal's row-multiplication estimate.",
                    },
                },
                "required": ["left_dataset_id", "left_column", "right_dataset_id", "right_column"],
                "additionalProperties": False,
            },
        ),
        handler=_join_datasets,
    ),
    "calculate_metric": Tool(
        schema=ToolSchema(
            name="calculate_metric",
            description=(
                "Compute a single aggregated number (total, average, count, ...) over a dataset, "
                "optionally filtered. metric_column doesn't need to be the exact column name -- a "
                "close business term ('sales', 'revenue') is resolved against the real schema, "
                "preferring a genuinely numeric measure over an identifier column."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_column": {"type": "string"},
                    "aggregation": {"type": "string", "enum": ["sum", "mean", "median", "min", "max", "count", "nunique"]},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"]},
                                "value": {},
                            },
                            "required": ["column", "operator", "value"],
                        },
                    },
                },
                "required": ["dataset_id", "aggregation"],
                "additionalProperties": False,
            },
        ),
        handler=_calculate_metric,
    ),
    "group_and_aggregate": Tool(
        schema=ToolSchema(
            name="group_and_aggregate",
            description=(
                "Break a metric down by a category (e.g. revenue by region), with optional ranking "
                "and filters. metric_column and dimension_column are resolved against the real "
                "schema even when not spelled exactly -- 'product' correctly prefers a descriptive "
                "column like product_name over product_id unless the wording explicitly asks for the id. "
                "Set second_dimension_column for a two-way breakdown (e.g. 'sales by region and shipping "
                "mode') -- returns one row per (dimension, second_dimension) combination."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_column": {"type": "string"},
                    "aggregation": {"type": "string", "enum": ["sum", "mean", "median", "min", "max", "count", "nunique"]},
                    "dimension_column": {"type": "string"},
                    "second_dimension_column": {
                        "type": "string",
                        "description": "Optional second grouping column for a two-dimension breakdown.",
                    },
                    "top_n": {"type": "integer"},
                    "sort": {"type": "string", "enum": ["asc", "desc"]},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"]},
                                "value": {},
                            },
                            "required": ["column", "operator", "value"],
                        },
                    },
                },
                "required": ["dataset_id", "aggregation", "dimension_column"],
                "additionalProperties": False,
            },
        ),
        handler=_group_and_aggregate,
    ),
    "compare_periods": Tool(
        schema=ToolSchema(
            name="compare_periods",
            description="Compare a metric between two calendar-month periods (format 'YYYY-MM') and get the absolute and percentage change.",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_column": {"type": "string"},
                    "aggregation": {"type": "string", "enum": ["sum", "mean", "median", "min", "max", "count", "nunique"]},
                    "date_column": {"type": "string"},
                    "period_a": {"type": "string", "description": "Earlier period, e.g. '2024-01'."},
                    "period_b": {"type": "string", "description": "Later period, e.g. '2024-02'."},
                    "filters": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["dataset_id", "date_column", "period_a", "period_b"],
                "additionalProperties": False,
            },
        ),
        handler=_compare_periods,
    ),
    "detect_anomalies": Tool(
        schema=ToolSchema(
            name="detect_anomalies",
            description="Find statistically unusual values (IQR outliers) in a numeric column, or auto-pick the best metric.",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_column": {"type": "string", "description": "Optional; auto-selected if omitted."},
                },
                "required": ["dataset_id"],
                "additionalProperties": False,
            },
        ),
        handler=_detect_anomalies,
    ),
    "correlate": Tool(
        schema=ToolSchema(
            name="correlate",
            description="Compute the Pearson correlation between two numeric columns in a dataset.",
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "column_a": {"type": "string"},
                    "column_b": {"type": "string"},
                },
                "required": ["dataset_id", "column_a", "column_b"],
                "additionalProperties": False,
            },
        ),
        handler=_correlate,
    ),
    "generate_chart": Tool(
        schema=ToolSchema(
            name="generate_chart",
            description=(
                "Run an analysis and get back a chart plus chart-ready data for it. "
                "chart_type is an optional override -- set it when the question's own "
                "wording implies a specific chart, not just the category count (e.g. "
                "'what percentage/share of X is Y' implies donut/pie; 'trend'/'over time' "
                "implies line; a plain 'count/total X by Y' should stay bar/column, not "
                "donut, even with few categories; 'by <dimension> and <second dimension>' "
                "implies setting second_dimension_column, which produces grouped_bar/"
                "stacked_bar; 'by country'/geographic questions imply map, but map only "
                "actually renders when dimension_column is a real country column -- it's "
                "silently ignored otherwise). Omit chart_type to let the engine pick from "
                "the data shape alone."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "metric_column": {"type": "string"},
                    "aggregation": {"type": "string", "enum": ["sum", "mean", "median", "min", "max", "count", "nunique"]},
                    "dimension_column": {"type": "string"},
                    "second_dimension_column": {
                        "type": "string",
                        "description": "Optional second grouping column, e.g. 'sales by region and shipping mode' -- produces a grouped/stacked chart.",
                    },
                    "date_column": {"type": "string"},
                    "top_n": {"type": "integer", "description": "Set this for a 'top N' / ranking question."},
                    "sort": {"type": "string", "enum": ["desc", "asc"]},
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "column", "donut", "pie", "line", "grouped_bar", "stacked_bar", "scatter", "map", "table"],
                    },
                    "filters": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["dataset_id", "aggregation"],
                "additionalProperties": False,
            },
        ),
        handler=_generate_chart,
    ),
    "generate_dashboard": Tool(
        schema=ToolSchema(
            name="generate_dashboard",
            description="Build a small multi-chart dashboard from a dataset's auto-discovered KPIs.",
            parameters={
                "type": "object",
                "properties": {"dataset_id": {"type": "string"}},
                "required": ["dataset_id"],
                "additionalProperties": False,
            },
        ),
        handler=_generate_dashboard,
    ),
    "search_documents": Tool(
        schema=ToolSchema(
            name="search_documents",
            description="Search uploaded documents (PDF/DOCX/PPTX/TXT/MD/PY) for chunks relevant to a query.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "document_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        handler=_search_documents,
    ),
    "retrieve_document_evidence": Tool(
        schema=ToolSchema(
            name="retrieve_document_evidence",
            description="Retrieve the full text and source location of one specific document chunk by id.",
            parameters={
                "type": "object",
                "properties": {"document_id": {"type": "string"}, "chunk_id": {"type": "string"}},
                "required": ["document_id", "chunk_id"],
                "additionalProperties": False,
            },
        ),
        handler=_retrieve_document_evidence,
    ),
    "web_research": Tool(
        schema=ToolSchema(
            name="web_research",
            description=(
                "Search the public web for external context (industry benchmarks, news, competitor "
                "info) that isn't present in the uploaded datasets or documents. Bounded per question "
                "by MAX_RESEARCH_QUERIES/MAX_RESEARCH_TOOL_CALLS -- only call this when internal data "
                "and documents genuinely cannot answer the question, and prefer few, specific queries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        handler=_web_research,
    ),
    "verify_claim": Tool(
        schema=ToolSchema(
            name="verify_claim",
            description="Check whether a numeric claim you are about to make is actually backed by a tool result "
            "from this conversation. Call this before labelling anything VERIFIED_FROM_DATA or CALCULATED.",
            parameters={
                "type": "object",
                "properties": {
                    "claim_text": {"type": "string"},
                    "claimed_label": {
                        "type": "string",
                        "enum": [
                            "VERIFIED_FROM_DATA",
                            "CALCULATED",
                            "DERIVED",
                            "DOCUMENT_EVIDENCE",
                            "AI_INTERPRETATION",
                            "INSUFFICIENT_DATA",
                        ],
                    },
                    "tool_call_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim_text", "claimed_label"],
                "additionalProperties": False,
            },
        ),
        handler=None,  # handled specially -- needs access to this turn's tool_invocations
    ),
}
