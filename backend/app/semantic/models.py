"""Shared data-model / semantic-layer schemas.

Every other layer (profiling, relationships, analysis, visualization) speaks
in these types. This is the one place that defines what a "dataset",
a "column profile", or an "insight" looks like.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnType(StrEnum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    DATE = "date"
    BOOLEAN = "boolean"
    IDENTIFIER = "identifier"
    TEXT = "text"
    UNKNOWN = "unknown"


class JoinType(StrEnum):
    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"


class JoinCardinality(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class SourceLabel(StrEnum):
    """Anti-hallucination provenance label attached to every numeric claim."""

    VERIFIED_FROM_DATA = "VERIFIED_FROM_DATA"
    CALCULATED = "CALCULATED"
    DERIVED = "DERIVED"
    AI_INTERPRETATION = "AI_INTERPRETATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class TopValue(BaseModel):
    value: str
    count: int
    percentage: float


class ColumnProfile(BaseModel):
    name: str
    inferred_type: ColumnType
    row_count: int
    non_null_count: int
    missing_count: int
    missing_percentage: float
    unique_count: int
    is_likely_identifier: bool = False
    quality_flags: list[str] = Field(default_factory=list)

    # Numeric-only
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None

    # Categorical-only
    cardinality: int | None = None
    top_values: list[TopValue] | None = None

    # Date-only
    min_date: str | None = None
    max_date: str | None = None
    date_coverage_days: int | None = None


class DatasetQualitySummary(BaseModel):
    duplicate_row_count: int
    duplicate_row_percentage: float
    columns_mostly_missing: list[str] = Field(default_factory=list)
    possible_id_columns: list[str] = Field(default_factory=list)
    possible_date_columns: list[str] = Field(default_factory=list)
    numeric_stored_as_text_columns: list[str] = Field(default_factory=list)
    high_cardinality_columns: list[str] = Field(default_factory=list)
    duplicate_column_names: list[str] = Field(default_factory=list)
    overall_rating: Literal["good", "fair", "poor"]
    notes: list[str] = Field(default_factory=list)


class DatasetKind(StrEnum):
    UPLOADED = "uploaded"
    JOINED = "joined"
    CONNECTED = "connected"


class DatasetSummary(BaseModel):
    id: str
    name: str
    source_file: str
    sheet_name: str | None
    kind: DatasetKind
    row_count: int
    column_count: int
    quality_rating: Literal["good", "fair", "poor"]
    created_at: datetime


class JoinLineage(BaseModel):
    """Provenance for a joined/derived dataset -- who it was built from and how.

    Persisted alongside the profile so a derived dataset's ancestry survives
    a server restart (both live in the same on-disk JSON, see
    app/semantic/store.py), and so the relationship engine can suppress
    self-referential "orders-products.csv is related to orders.csv" noise
    (see app/relationships/service.py's parent-suppression check).
    """

    parent_dataset_ids: list[str]
    left_dataset_id: str
    left_dataset_name: str
    left_column: str
    right_dataset_id: str
    right_dataset_name: str
    right_column: str
    join_type: JoinType
    created_by_user_id: str


class DatasetProfile(BaseModel):
    id: str
    name: str
    source_file: str
    sheet_name: str | None
    kind: DatasetKind
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    numeric_columns: list[str]
    categorical_columns: list[str]
    date_columns: list[str]
    identifier_columns: list[str]
    text_columns: list[str] = Field(default_factory=list)
    quality: DatasetQualitySummary
    created_at: datetime
    lineage: JoinLineage | None = None


class UploadWarning(BaseModel):
    file: str
    sheet: str | None = None
    message: str


class UploadError(BaseModel):
    file: str
    sheet: str | None = None
    message: str


class UploadResult(BaseModel):
    datasets: list[DatasetSummary]
    warnings: list[UploadWarning] = Field(default_factory=list)
    errors: list[UploadError] = Field(default_factory=list)


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RelationshipSuggestion(BaseModel):
    left_dataset_id: str
    left_dataset_name: str
    left_column: str
    right_dataset_id: str
    right_dataset_name: str
    right_column: str
    confidence: ConfidenceLevel
    confidence_score: float
    cardinality: JoinCardinality
    reasons: list[str]
    value_overlap_percentage: float | None
    left_cardinality: int
    right_cardinality: int
    suggested_join_type: Literal["inner", "left", "right", "full"]


class JoinRequest(BaseModel):
    left_dataset_id: str
    left_column: str
    right_dataset_id: str
    right_column: str
    join_type: JoinType = JoinType.INNER
    result_name: str | None = None
    # A many-to-many join (duplicate keys on both sides) is refused by
    # default -- see app/relationships/joins.perform_join -- because it
    # silently multiplies rows. Set True only once the caller has actually
    # inspected the cardinality/fan-out estimate and wants it anyway.
    allow_fan_out: bool = False


class JoinPreviewResult(BaseModel):
    """Dry-run stats for a proposed join -- computed but nothing persisted."""

    left_dataset_name: str
    left_column: str
    right_dataset_name: str
    right_column: str
    join_type: JoinType
    rows_before_left: int
    rows_before_right: int
    rows_after: int
    matched_both: int
    unmatched_left: int
    unmatched_right: int
    duplicate_key_warning: bool
    cardinality: JoinCardinality
    key_overlap_percentage: float
    estimated_fan_out_rows: int | None = None
    notes: list[str] = Field(default_factory=list)


class JoinResult(BaseModel):
    new_dataset_id: str
    new_dataset: DatasetSummary
    reused_existing: bool = False
    left_dataset_id: str
    left_column: str
    right_dataset_id: str
    right_column: str
    join_type: JoinType
    rows_before_left: int
    rows_before_right: int
    rows_after: int
    matched_both: int
    unmatched_left: int
    unmatched_right: int
    duplicate_key_warning: bool
    cardinality: JoinCardinality
    key_overlap_percentage: float
    estimated_fan_out_rows: int | None = None
    notes: list[str] = Field(default_factory=list)


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    IN = "in"


class FilterCondition(BaseModel):
    column: str
    operator: FilterOperator
    value: Any


class Aggregation(StrEnum):
    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    NUNIQUE = "nunique"


class ChartType(StrEnum):
    KPI_CARD = "kpi_card"
    BAR = "bar"
    COLUMN = "column"
    LINE = "line"
    PIE = "pie"
    DONUT = "donut"
    SCATTER = "scatter"
    TABLE = "table"
    RANKING = "ranking"
    TIME_SERIES = "time_series"
    GROUPED_BAR = "grouped_bar"
    STACKED_BAR = "stacked_bar"
    MAP = "map"
    INSUFFICIENT_DATA = "insufficient_data"


class AnalysisRequest(BaseModel):
    dataset_id: str
    metric_column: str | None = None
    aggregation: Aggregation = Aggregation.SUM
    dimension_column: str | None = None
    second_dimension_column: str | None = None
    date_column: str | None = None
    filters: list[FilterCondition] = Field(default_factory=list)
    top_n: int | None = None
    sort: Literal["desc", "asc"] = "desc"
    # User's explicit chart-type override (Phase 4 continuation section 18) --
    # must still be one the ChartCompatibility engine considers valid for
    # these fields; None means "let the engine recommend one" (unchanged
    # default behavior).
    chart_type: ChartType | None = None


class ChartSpec(BaseModel):
    chart_type: ChartType
    dataset_id: str
    # Human-readable title describing what this chart shows, e.g.
    # "Total Sales Amount by Color" or "Monthly Sales Amount Trend".
    # Generated by the analysis engine; displayed above every chart.
    title: str = ""
    # Source lineage — which dataset/sheet produced this chart.
    dataset_name: str = ""
    dataset_sheet: str | None = None
    x_column: str | None = None
    y_column: str | None = None
    # Set only for grouped/stacked charts: the field in `data` that splits
    # each x_column value into multiple series (the second dimension).
    series_column: str | None = None
    aggregation: str | None = None
    filters: list[FilterCondition] = Field(default_factory=list)
    reason: str
    data: list[dict[str, Any]] | None = None
    # Map charts only: country values that had no deterministic centroid
    # match (see app/geography/countries.py) -- reported honestly rather
    # than silently dropped or assigned a guessed location.
    unmatched_categories: list[str] | None = None


class AnalysisResult(BaseModel):
    request: AnalysisRequest
    result_type: Literal["scalar", "table", "timeseries", "insufficient_data"]
    scalar_value: float | None = None
    table: list[dict[str, Any]] | None = None
    columns_used: list[str]
    row_count_considered: int
    calculation_description: str
    source: SourceLabel = SourceLabel.CALCULATED
    chart_recommendation: ChartSpec | None = None


class KPISuggestion(BaseModel):
    name: str
    dataset_id: str
    # Source lineage — which dataset and sheet this KPI was calculated from.
    # Populated by discover_kpis(); exposed in the API response so the frontend
    # can display "Source: Sales_data" under each KPI card.
    dataset_name: str = ""
    dataset_sheet: str | None = None
    metric_column: str | None
    aggregation: Aggregation
    dimension_column: str | None = None
    date_column: str | None = None
    rationale: str
    label: Literal["Suggested KPI"] = "Suggested KPI"
    preview_value: float | None = None
    preview_source: SourceLabel = SourceLabel.CALCULATED


class Evidence(BaseModel):
    description: str
    supporting_values: dict[str, Any]


class Insight(BaseModel):
    id: str
    dataset_id: str
    category: Literal[
        "top_performer",
        "concentration_risk",
        "significant_change",
        "anomaly",
        "data_quality",
        "distribution",
    ]
    finding: str
    evidence: Evidence
    calculation: str
    interpretation: str
    confidence_label: SourceLabel
