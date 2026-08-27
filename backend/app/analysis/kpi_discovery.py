"""Automatic KPI discovery.

Suggests candidate metrics from column names, types, and shape -- never
asserts business meaning a column name doesn't already carry (a column
literally named "amount" is aggregated and labelled "Total amount", not
silently renamed to "Total revenue").

Identifier columns (CustomerKey, SalesOrderLineKey, SalesTerritoryKey,
ProductKey, etc.) are explicitly excluded from financial/business KPIs --
they are counted (distinct values) rather than summed, and only when
counting is genuinely meaningful for the dataset context.
"""

import re

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
    "income",
    "earning",
    "fee",
    "rate",
)

# Priority-ordered groups for ranking metric candidates.
# Higher priority = shown first as KPI candidates.
_METRIC_PRIORITY_GROUPS: list[tuple[int, tuple[str, ...]]] = [
    (0, ("revenue", "sales")),                              # Revenue / Sales — highest priority
    (1, ("profit", "margin", "earning", "income")),        # Profitability
    (2, ("cost", "spend", "expense")),                     # Cost
    (3, ("amount",)),                                       # Generic amount (Sales Amount etc.)
    (4, ("quantity", "units", "volume")),                   # Volume / Quantity
    (5, ("price",)),                                        # Price (use MEAN not SUM)
    (6, ("salary", "bonus", "fee", "fare")),                # Compensation
    (7, ("rate", "margin", "pct", "percent", "%")),         # Rate/Percentage
    (8, ("total",)),                                        # Misc totals
    (9, ("value",)),                                        # Value (catch-all)
]

def _metric_priority(column: str) -> int:
    """Return a priority rank for a business metric column (lower = higher priority)."""
    lowered = column.lower().replace("_", " ").replace("-", " ")
    for priority, keywords in _METRIC_PRIORITY_GROUPS:
        if any(kw in lowered for kw in keywords):
            return priority
    return 99

# Patterns that strongly indicate an identifier / surrogate key column.
# Handles both camelCase (CustomerKey, SalesOrderLineKey) and
# underscore_separated (customer_id, order_no) forms.
# Columns matching these patterns should never be SUM-aggregated as KPIs.
_IDENTIFIER_PATTERNS = re.compile(
    r"(?i)"
    r"(?:"
    # CamelCase suffix: ends with Key, Id, Code, No, Seq, Ref, Uuid, Guid
    r"(?:Key|Id|Code|No|Num|Seq|Ref|Uuid|Guid|Pk|Fk|Oid|RowId)$"
    r"|"
    # Underscore-separated: _key, _id, _code, etc. or starts with id_, key_
    r"(?:_(?:key|id|code|num|no|seq|ref|uuid|guid|pk|fk|oid|rowid)(?:_|$))"
    r"|"
    r"(?:^(?:key|id|code|num|no)_)"
    r")"
)

# Human-friendly label overrides for common business column names.
_DISPLAY_OVERRIDES: dict[str, str] = {
    "sales amount": "Total Sales",
    "extended amount": "Total Extended Amount",
    "order quantity": "Total Quantity",
    "unit price": "Average Unit Price",
    "standard cost": "Total Standard Cost",
    "total product cost": "Total Product Cost",
    "gross margin": "Total Gross Margin",
    "units sold": "Total Units Sold",
    "sales_amount": "Total Sales",
    "gross_margin": "Total Gross Margin",
    "units_sold": "Total Units Sold",
    "order_quantity": "Total Quantity",
    "unit_price": "Average Unit Price",
}

MIN_DIMENSION_CARDINALITY = 2
MAX_DIMENSION_CARDINALITY = 50
MAX_SUGGESTIONS = 8


def _is_identifier_column(column: str) -> bool:
    """Return True if the column name strongly suggests an identifier/surrogate key.

    Columns like CustomerKey, SalesOrderLineKey, SalesTerritoryKey, ProductKey,
    OrderID, customer_id, etc. should be counted (distinct) not summed.
    """
    return bool(_IDENTIFIER_PATTERNS.search(column))


def _name_matches_metric_hint(column: str) -> bool:
    lowered = column.lower()
    # Exclude identifiers even if they happen to contain a metric hint word
    if _is_identifier_column(lowered):
        return False
    return any(hint in lowered for hint in METRIC_NAME_HINTS)


def _kpi_display_name(aggregation: str, column: str) -> str:
    """Return a clean, business-readable KPI label for the given column."""
    key = column.lower().replace("_", " ").strip()
    if key in _DISPLAY_OVERRIDES and aggregation == "sum":
        return _DISPLAY_OVERRIDES[key]
    if key in _DISPLAY_OVERRIDES and aggregation == "mean":
        base = _DISPLAY_OVERRIDES[key].replace("Total ", "Average ")
        return base
    prefix = {"sum": "Total", "mean": "Average", "count": "Count of", "nunique": "Distinct"}.get(
        aggregation, aggregation.title()
    )
    # Title-case the column name for display
    display_col = column.replace("_", " ").replace("-", " ").title()
    return f"{prefix} {display_col}"


def rank_metric_candidates(profile: DatasetProfile) -> list[str]:
    """Return numeric columns ranked by business-metric likelihood.

    Identifier columns are excluded entirely from the metric candidate list
    to prevent KPIs like "Total CustomerKey" or "Total SalesTerritoryKey"
    from appearing on the executive dashboard.

    Candidates are sorted by semantic priority:
    Revenue/Sales > Profit/Margin > Cost > Amount > Quantity > Price > ...
    """
    candidates = [c for c in profile.numeric_columns if not _is_identifier_column(c)]
    candidates.sort(key=lambda c: (
        0 if _name_matches_metric_hint(c) else 1,
        _metric_priority(c),
    ))
    # Return top 5 to give KPI discovery enough variety for rich datasets
    return candidates[:5]


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

    # Source lineage for every KPI produced by this record
    source_name = profile.name
    source_sheet = profile.sheet_name

    metric_candidates = rank_metric_candidates(profile)
    dimension_candidates = rank_dimension_candidates(profile)
    date_candidates = profile.date_columns[:1]

    # Collect the priority-0/1/2 (revenue/profit/cost) metric names so we
    # can suppress near-redundant metrics that would be confusing alongside them.
    # e.g. "Extended Amount" duplicates "Sales Amount" in AdventureWorks.
    top_metric_hints = {"revenue", "sales", "profit", "cost"}
    top_metrics_present = [
        c for c in metric_candidates
        if any(h in c.lower() for h in top_metric_hints)
    ]
    # Track metric columns already added to detect the "extended amount" / "sales amount"
    # style redundancy: if we already have a "sales"/"revenue" metric, skip plain "amount"
    # variants that produce near-identical totals.
    added_metric_cols: set[str] = set()

    for metric in metric_candidates:
        # Suppress redundant metrics: if a higher-priority sales/revenue metric already
        # covers the same analytical space, skip a lower-priority "amount" or "extended"
        # variant unless it's materially different.
        is_redundant = False
        if top_metrics_present and metric not in top_metrics_present:
            # "Extended Amount" and "Sales Amount" tend to be near-identical in AW
            lower = metric.lower()
            if "amount" in lower or "extended" in lower:
                if any(c for c in added_metric_cols if "sales" in c.lower() or "revenue" in c.lower()):
                    is_redundant = True

        if is_redundant:
            continue

        is_unit_metric = any(h in metric.lower() for h in ("price", "rate", "margin", "pct", "percent", "%"))
        agg = Aggregation.MEAN if is_unit_metric else Aggregation.SUM
        rationale = (
            f"'{metric}' is a numeric business quantity suitable for {agg.value} aggregation."
            if _name_matches_metric_hint(metric)
            else f"'{metric}' is numeric and available for aggregation."
        )
        value = aggregate_scalar(df, metric, agg)
        suggestions.append(
            KPISuggestion(
                name=_kpi_display_name(agg.value, metric),
                dataset_id=profile.id,
                dataset_name=source_name,
                dataset_sheet=source_sheet,
                metric_column=metric,
                aggregation=agg,
                rationale=rationale,
                preview_value=value,
            )
        )
        added_metric_cols.add(metric)

    # Identifier columns: count distinct entities — only useful when the
    # distinct count is materially less than the row count (i.e., this is
    # a genuine dimension like "how many customers" rather than a fact-row
    # count like "how many sales order lines").
    #
    # Rule: only surface as a KPI when distinct_count / row_count < 0.3
    # AND the column name hints at a real business entity (not a join key).
    # "order" is excluded because SalesOrderLineKey / order_id nunique in a
    # fact table just mirrors the row count.
    meaningful_id_hints = ("customer", "product", "store", "employee", "reseller")
    identifier_columns = [c for c in profile.identifier_columns if
                          any(h in c.lower() for h in meaningful_id_hints)]
    for identifier_column in identifier_columns[:1]:
        count = int(df[identifier_column].nunique())
        row_count = len(df)
        if row_count > 0 and count / row_count > 0.3:
            continue
        from app.profiling.type_inference import CAMEL_BOUNDARY
        words = CAMEL_BOUNDARY.sub(" ", identifier_column)
        words = words.replace("_", " ").replace("-", " ")
        display_col = re.sub(r"\s*(Key|Id|Code|Num|UUID|GUID)\s*$", "", words, flags=re.IGNORECASE).strip().title()
        plural = display_col + ("s" if not display_col.endswith("s") else "")
        suggestions.append(
            KPISuggestion(
                name=f"Distinct {plural}",
                dataset_id=profile.id,
                dataset_name=source_name,
                dataset_sheet=source_sheet,
                metric_column=identifier_column,
                aggregation=Aggregation.NUNIQUE,
                rationale=f"'{identifier_column}' is an identifier; counting distinct values shows the number of unique {display_col.lower()}s.",
                preview_value=float(count),
            )
        )

    if metric_candidates and dimension_candidates:
        metric, dimension = metric_candidates[0], dimension_candidates[0]
        agg = Aggregation.MEAN if any(h in metric.lower() for h in ("price", "rate", "margin")) else Aggregation.SUM
        suggestions.append(
            KPISuggestion(
                name=f"{_kpi_display_name(agg.value, metric)} by {dimension.replace('_',' ').title()}",
                dataset_id=profile.id,
                dataset_name=source_name,
                dataset_sheet=source_sheet,
                metric_column=metric,
                aggregation=agg,
                dimension_column=dimension,
                rationale=f"'{dimension}' is a categorical column with a manageable number of groups "
                f"({df[dimension].nunique()}), suitable for breaking '{metric}' down by category.",
            )
        )

    if metric_candidates and date_candidates:
        metric, date_col = metric_candidates[0], date_candidates[0]
        agg = Aggregation.MEAN if any(h in metric.lower() for h in ("price", "rate", "margin")) else Aggregation.SUM
        suggestions.append(
            KPISuggestion(
                name=f"{metric.replace('_',' ').title()} Trend",
                dataset_id=profile.id,
                dataset_name=source_name,
                dataset_sheet=source_sheet,
                metric_column=metric,
                aggregation=agg,
                date_column=date_col,
                rationale=f"'{date_col}' was detected as a date column, enabling a monthly trend of '{metric}'.",
            )
        )

    for metric in metric_candidates[:2]:
        value = aggregate_scalar(df, metric, Aggregation.MEAN)
        suggestions.append(
            KPISuggestion(
                name=_kpi_display_name("mean", metric),
                dataset_id=profile.id,
                dataset_name=source_name,
                dataset_sheet=source_sheet,
                metric_column=metric,
                aggregation=Aggregation.MEAN,
                rationale=f"'{metric}' is numeric; the average is a natural companion to the total.",
                preview_value=value,
            )
        )

    if not suggestions:
        suggestions.append(
            KPISuggestion(
                name="Record Count",
                dataset_id=profile.id,
                dataset_name=source_name,
                dataset_sheet=source_sheet,
                metric_column=None,
                aggregation=Aggregation.COUNT,
                rationale="No numeric business metric or meaningful identifier was found; "
                "row count is the only reliable summary available.",
                preview_value=float(len(df)),
            )
        )

    # Deduplicate by (metric_column, aggregation, dimension_column, date_column) fingerprint
    seen: set[tuple[str | None, str, str | None, str | None]] = set()
    deduped: list[KPISuggestion] = []
    for kpi in suggestions:
        fp = (kpi.metric_column, kpi.aggregation.value, kpi.dimension_column, kpi.date_column)
        if fp not in seen:
            seen.add(fp)
            deduped.append(kpi)

    return deduped[:MAX_SUGGESTIONS]
