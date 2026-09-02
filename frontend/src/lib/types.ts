export type ColumnType =
  | "numeric"
  | "categorical"
  | "date"
  | "boolean"
  | "identifier"
  | "text"
  | "unknown";

export type SourceLabel =
  | "VERIFIED_FROM_DATA"
  | "CALCULATED"
  | "DERIVED"
  | "AI_INTERPRETATION"
  | "INSUFFICIENT_DATA";

export type DatasetKind = "uploaded" | "joined" | "connected";

export interface TopValue {
  value: string;
  count: number;
  percentage: number;
}

export interface ColumnProfile {
  name: string;
  inferred_type: ColumnType;
  row_count: number;
  non_null_count: number;
  missing_count: number;
  missing_percentage: number;
  unique_count: number;
  is_likely_identifier: boolean;
  quality_flags: string[];
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
  std: number | null;
  cardinality: number | null;
  top_values: TopValue[] | null;
  min_date: string | null;
  max_date: string | null;
  date_coverage_days: number | null;
}

export interface DatasetQualitySummary {
  duplicate_row_count: number;
  duplicate_row_percentage: number;
  columns_mostly_missing: string[];
  possible_id_columns: string[];
  possible_date_columns: string[];
  numeric_stored_as_text_columns: string[];
  high_cardinality_columns: string[];
  duplicate_column_names: string[];
  overall_rating: "good" | "fair" | "poor";
  notes: string[];
}

export interface DatasetSummary {
  id: string;
  name: string;
  source_file: string;
  sheet_name: string | null;
  kind: DatasetKind;
  row_count: number;
  column_count: number;
  quality_rating: "good" | "fair" | "poor";
  created_at: string;
}

export interface DatasetProfile extends DatasetSummary {
  columns: ColumnProfile[];
  numeric_columns: string[];
  categorical_columns: string[];
  date_columns: string[];
  identifier_columns: string[];
  text_columns: string[];
  quality: DatasetQualitySummary;
}

export interface UploadWarning {
  file: string;
  sheet: string | null;
  message: string;
}

export interface UploadError {
  file: string;
  sheet: string | null;
  message: string;
}

export interface UploadResult {
  datasets: DatasetSummary[];
  warnings: UploadWarning[];
  errors: UploadError[];
}

export type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW";
export type JoinType = "inner" | "left" | "right" | "full";
export type JoinCardinality = "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";

export interface RelationshipSuggestion {
  left_dataset_id: string;
  left_dataset_name: string;
  left_column: string;
  right_dataset_id: string;
  right_dataset_name: string;
  right_column: string;
  confidence: ConfidenceLevel;
  confidence_score: number;
  cardinality: JoinCardinality;
  reasons: string[];
  value_overlap_percentage: number | null;
  left_cardinality: number;
  right_cardinality: number;
  suggested_join_type: JoinType;
}

export interface JoinPreviewResult {
  left_dataset_name: string;
  left_column: string;
  right_dataset_name: string;
  right_column: string;
  join_type: JoinType;
  rows_before_left: number;
  rows_before_right: number;
  rows_after: number;
  matched_both: number;
  unmatched_left: number;
  unmatched_right: number;
  duplicate_key_warning: boolean;
  cardinality: JoinCardinality;
  key_overlap_percentage: number;
  estimated_fan_out_rows: number | null;
  notes: string[];
}

export interface JoinResult {
  new_dataset_id: string;
  new_dataset: DatasetSummary;
  reused_existing: boolean;
  left_dataset_id: string;
  left_column: string;
  right_dataset_id: string;
  right_column: string;
  join_type: JoinType;
  rows_before_left: number;
  rows_before_right: number;
  rows_after: number;
  matched_both: number;
  unmatched_left: number;
  unmatched_right: number;
  duplicate_key_warning: boolean;
  cardinality: JoinCardinality;
  key_overlap_percentage: number;
  estimated_fan_out_rows: number | null;
  notes: string[];
}

export type Aggregation = "sum" | "mean" | "median" | "min" | "max" | "count" | "nunique";

export interface FilterCondition {
  column: string;
  operator: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "in";
  value: string | number | string[];
}

export interface AnalysisRequest {
  dataset_id: string;
  metric_column?: string | null;
  aggregation: Aggregation;
  dimension_column?: string | null;
  second_dimension_column?: string | null;
  date_column?: string | null;
  filters?: FilterCondition[];
  top_n?: number | null;
  sort?: "desc" | "asc";
  session_id?: string | null;
  chart_type?: ChartType | null;
}

export type ChartType =
  | "kpi_card"
  | "bar"
  | "column"
  | "line"
  | "pie"
  | "donut"
  | "scatter"
  | "table"
  | "ranking"
  | "time_series"
  | "grouped_bar"
  | "stacked_bar"
  | "map"
  | "insufficient_data";

export interface ChartSpec {
  chart_type: ChartType;
  dataset_id: string;
  title?: string;
  dataset_name?: string;
  dataset_sheet?: string | null;
  x_column: string | null;
  y_column: string | null;
  series_column: string | null;
  aggregation: string | null;
  filters: FilterCondition[];
  reason: string;
  data: Record<string, unknown>[] | null;
  unmatched_categories: string[] | null;
}

export interface AnalysisResult {
  request: AnalysisRequest;
  result_type: "scalar" | "table" | "timeseries" | "insufficient_data";
  scalar_value: number | null;
  table: Record<string, unknown>[] | null;
  columns_used: string[];
  row_count_considered: number;
  calculation_description: string;
  source: SourceLabel;
  chart_recommendation: ChartSpec | null;
}

export interface KPISuggestion {
  name: string;
  dataset_id: string;
  dataset_name?: string;
  dataset_sheet?: string | null;
  metric_column: string | null;
  aggregation: Aggregation;
  dimension_column: string | null;
  date_column: string | null;
  rationale: string;
  label: "Suggested KPI";
  preview_value: number | null;
  preview_source: SourceLabel;
}

export interface Evidence {
  description: string;
  supporting_values: Record<string, unknown>;
}

export interface Insight {
  id: string;
  dataset_id: string;
  category:
  | "top_performer"
  | "concentration_risk"
  | "significant_change"
  | "anomaly"
  | "data_quality"
  | "distribution";
  finding: string;
  evidence: Evidence;
  calculation: string;
  interpretation: string;
  confidence_label: SourceLabel;
}

// ---- Phase 3: Documents / RAG ----

export type DocumentType = "pdf" | "docx" | "pptx" | "txt" | "md";

export interface ChunkLocation {
  page?: number | null;
  slide?: number | null;
  slide_title?: string | null;
  heading?: string | null;
  line_start?: number | null;
  line_end?: number | null;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  document_type: DocumentType;
  chunk_count: number;
  char_count: number;
  created_at: string;
  extraction_warnings: string[];
}

export interface DocumentUploadError {
  file: string;
  message: string;
}

export interface DocumentUploadResult {
  documents: DocumentSummary[];
  errors: DocumentUploadError[];
}

// ---- Phase 3: Agent ----

export type EvidenceLabel =
  | "VERIFIED_FROM_DATA"
  | "CALCULATED"
  | "DERIVED"
  | "DOCUMENT_EVIDENCE"
  | "VERIFIED_FROM_WEB"
  | "AI_INTERPRETATION"
  | "INSUFFICIENT_DATA";

export type CrossCheckLabel =
  | "SUPPORTED_BY_DATA"
  | "DOCUMENT_CLAIM"
  | "NOT_VERIFIED_BY_DATA"
  | "CONTRADICTED_BY_DATA"
  | "INSUFFICIENT_EVIDENCE";

export interface ToolInvocation {
  id: string;
  tool_name: string;
  input: Record<string, unknown>;
  output_summary: string;
  succeeded: boolean;
  duration_ms: number;
}

export type TraceStage =
  | "understanding_question"
  | "routing"
  | "datasets"
  | "documents"
  | "relationships"
  | "analysis"
  | "document_research"
  | "web_research"
  | "verification"
  | "answer";

export interface TraceStep {
  stage: TraceStage;
  label: string;
  detail: string;
}

export interface Citation {
  document_id: string;
  document_name: string;
  chunk_id: string;
  location: Record<string, unknown>;
  excerpt: string;
  relevance_score: number;
}

export interface AgentFinding {
  text: string;
  label: EvidenceLabel;
  verification_note: string | null;
  citations: Citation[];
}

export interface ClaimComparison {
  document_claim: string;
  citation: Citation | null;
  data_finding: string | null;
  label: CrossCheckLabel;
  explanation: string;
}

export interface LLMMetadata {
  provider: string;
  model: string;
  fallback_used: boolean;
  attempt_count: number;
  latency_ms: number;
}

export interface AgentAnswer {
  question: string;
  session_id: string;
  configured: boolean;
  executive_summary: string | null;
  key_findings: AgentFinding[];
  risks: AgentFinding[];
  recommendations: AgentFinding[];
  claim_comparisons: ClaimComparison[];
  charts: ChartSpec[];
  citations: Citation[];
  trace: TraceStep[];
  tool_invocations: ToolInvocation[];
  raw_answer_text: string | null;
  error: string | null;
  llm_metadata?: LLMMetadata | null;
  created_at: string;
  message_id?: string | null;
}

export interface AskRequest {
  question: string;
  session_id?: string | null;
  dataset_ids?: string[] | null;
  document_ids?: string[] | null;
}
