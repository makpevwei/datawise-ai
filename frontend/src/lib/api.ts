import type {
  AgentAnswer,
  AnalysisRequest,
  AnalysisResult,
  AskRequest,
  ChartSpec,
  DatasetProfile,
  DatasetSummary,
  DocumentSummary,
  DocumentUploadResult,
  Insight,
  JoinPreviewResult,
  JoinResult,
  JoinType,
  KPISuggestion,
  RelationshipSuggestion,
  UploadResult,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

const TOKEN_STORAGE_KEY = "datawise_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...authHeaders(),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // Error body wasn't JSON (HTML error page, empty body, etc.) -- fall back to statusText.
    }
    throw new ApiError(detail, res.status);
  }
  // 204 No Content (all DELETE endpoints) and any other empty-bodied response
  // have nothing for res.json() to parse -- it throws "Unexpected end of JSON
  // input" if called unconditionally. Read as text first and only parse when
  // there's actually a body.
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

export async function uploadDatasets(files: File[], forceNewVersion = false): Promise<UploadResult> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  if (forceNewVersion) form.append("force_new_version", "true");
  return request<UploadResult>("/datasets/upload", { method: "POST", body: form });
}

export interface DuplicateCheckResult {
  status: "new" | "exact_duplicate" | "changed_version";
  existing: DatasetLibraryItem | DocumentLibraryItem | null;
  next_version: number | null;
}

export function checkDatasetDuplicate(file: File): Promise<DuplicateCheckResult> {
  const form = new FormData();
  form.append("file", file);
  return request<DuplicateCheckResult>("/datasets/check-duplicate", { method: "POST", body: form });
}

export function checkDocumentDuplicate(file: File): Promise<DuplicateCheckResult> {
  const form = new FormData();
  form.append("file", file);
  return request<DuplicateCheckResult>("/documents/check-duplicate", { method: "POST", body: form });
}

export function listDatasetVersions(datasetId: string): Promise<DatasetLibraryItem[]> {
  return request<DatasetLibraryItem[]>(`/datasets/${datasetId}/versions`);
}

export function listDocumentVersions(documentId: string): Promise<DocumentLibraryItem[]> {
  return request<DocumentLibraryItem[]>(`/documents/${documentId}/versions`);
}

export function activateDatasetVersion(datasetId: string): Promise<DatasetLibraryItem> {
  return request<DatasetLibraryItem>(`/datasets/${datasetId}/activate`, { method: "POST" });
}

export function activateDocumentVersion(documentId: string): Promise<DocumentLibraryItem> {
  return request<DocumentLibraryItem>(`/documents/${documentId}/activate`, { method: "POST" });
}

export function listDatasets(): Promise<DatasetSummary[]> {
  return request<DatasetSummary[]>("/datasets");
}

export function getDataset(id: string): Promise<DatasetProfile> {
  return request<DatasetProfile>(`/datasets/${id}`);
}

export function getDatasetSample(id: string, n = 20): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>(`/datasets/${id}/sample?n=${n}`);
}

export function listRelationships(datasetIds?: string[]): Promise<RelationshipSuggestion[]> {
  const query = datasetIds?.length ? `?dataset_ids=${datasetIds.join(",")}` : "";
  return request<RelationshipSuggestion[]>(`/relationships${query}`);
}

export interface JoinRequestPayload {
  left_dataset_id: string;
  left_column: string;
  right_dataset_id: string;
  right_column: string;
  join_type: JoinType;
  allow_fan_out?: boolean;
  result_name?: string;
}

export function previewJoin(payload: JoinRequestPayload): Promise<JoinPreviewResult> {
  return request<JoinPreviewResult>("/relationships/join/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function joinDatasets(payload: JoinRequestPayload): Promise<JoinResult> {
  return request<JoinResult>("/relationships/join", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runAnalysis(payload: AnalysisRequest): Promise<AnalysisResult> {
  return request<AnalysisResult>("/analysis/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getKpiSuggestions(datasetId: string): Promise<KPISuggestion[]> {
  return request<KPISuggestion[]>(`/analysis/kpis/${datasetId}`);
}

export function getInsights(datasetId: string): Promise<Insight[]> {
  return request<Insight[]>(`/analysis/insights/${datasetId}`);
}

export function getDashboardCharts(datasetId: string): Promise<ChartSpec[]> {
  return request<ChartSpec[]>(`/analysis/dashboard-charts/${datasetId}`);
}

export function getDashboardChartsMulti(datasetIds: string[]): Promise<ChartSpec[]> {
  if (datasetIds.length === 0) return Promise.resolve([]);
  return request<ChartSpec[]>(`/analysis/dashboard-charts-multi?dataset_ids=${datasetIds.join(",")}`);
}

// ---- Phase 3: Documents / RAG ----

export async function uploadDocuments(files: File[], forceNewVersion = false): Promise<DocumentUploadResult> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  if (forceNewVersion) form.append("force_new_version", "true");
  return request<DocumentUploadResult>("/documents/upload", { method: "POST", body: form });
}

export function listDocuments(): Promise<DocumentSummary[]> {
  return request<DocumentSummary[]>("/documents");
}

// ---- Phase 3: Agent ----

export function getAgentStatus(): Promise<{ configured: boolean }> {
  return request<{ configured: boolean }>("/agent/status");
}

export function askAgent(payload: AskRequest): Promise<AgentAnswer> {
  return request<AgentAnswer>("/agent/ask", { method: "POST", body: JSON.stringify(payload) });
}

export async function exportAnalysisPdf(answer: AgentAnswer): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/agent/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(answer),
  });
  if (!res.ok) {
    throw new ApiError(`Export failed (${res.status})`, res.status);
  }
  return res.blob();
}

// ---- Auth ----

export const SUPPORTED_CURRENCIES = ["NGN", "USD", "EUR", "GBP", "JPY", "INR", "CAD", "AUD"] as const;
export type CurrencyCode = (typeof SUPPORTED_CURRENCIES)[number];

export interface UserPublic {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  currency: CurrencyCode;
  decimal_places: number;
  created_at: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
  user: UserPublic;
}

export function registerUser(payload: { email: string; password: string; full_name: string }): Promise<AuthToken> {
  return request<AuthToken>("/auth/register", { method: "POST", body: JSON.stringify(payload) });
}

export function loginUser(payload: { email: string; password: string }): Promise<AuthToken> {
  return request<AuthToken>("/auth/login", { method: "POST", body: JSON.stringify(payload) });
}

export function getCurrentUser(): Promise<UserPublic> {
  return request<UserPublic>("/auth/me");
}

export function updateUserSettings(payload: { currency?: CurrencyCode; decimal_places?: number }): Promise<UserPublic> {
  return request<UserPublic>("/auth/me/settings", { method: "PATCH", body: JSON.stringify(payload) });
}

export function logoutUser(): Promise<{ status: string }> {
  return request<{ status: string }>("/auth/logout", { method: "POST" });
}

// ---- Dataset / document library (My Data) ----

export interface DatasetLibraryItem {
  id: string;
  original_filename: string;
  display_name: string;
  file_type: string;
  file_size: number;
  row_count: number | null;
  column_count: number | null;
  processing_status: string;
  processing_error: string | null;
  version: number;
  is_active: boolean;
  created_at: string;
}

export interface DocumentLibraryItem {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number | null;
  processing_status: string;
  extraction_status: string;
  embedding_status: string;
  version: number;
  is_active: boolean;
  created_at: string;
}

export function listDatasetLibrary(includeInactive = false): Promise<DatasetLibraryItem[]> {
  return request<DatasetLibraryItem[]>(`/datasets/library${includeInactive ? "?include_inactive=true" : ""}`);
}

export function listDocumentLibrary(includeInactive = false): Promise<DocumentLibraryItem[]> {
  return request<DocumentLibraryItem[]>(`/documents/library${includeInactive ? "?include_inactive=true" : ""}`);
}

export function deleteDataset(id: string): Promise<void> {
  return request<void>(`/datasets/${id}`, { method: "DELETE" });
}

export function deleteDocument(id: string): Promise<void> {
  return request<void>(`/documents/${id}`, { method: "DELETE" });
}

// ---- Analysis sessions (Ask DataWise / Analysis Workspace history) ----

export interface MessageOut {
  id: string;
  role: string;
  kind: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SessionOut {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  message_count: number;
}

export interface SessionDetailOut extends SessionOut {
  messages: MessageOut[];
}

export function listSessions(): Promise<SessionOut[]> {
  return request<SessionOut[]>("/sessions");
}

export function getSession(id: string): Promise<SessionDetailOut> {
  return request<SessionDetailOut>(`/sessions/${id}`);
}

export function deleteSession(id: string): Promise<void> {
  return request<void>(`/sessions/${id}`, { method: "DELETE" });
}

// ---- Reports ----

export interface ReportOut {
  id: string;
  title: string;
  dataset_reference: string | null;
  session_id: string | null;
  email_status: "not_sent" | "pending" | "sent" | "failed";
  email_recipient: string | null;
  email_sent_at: string | null;
  created_at: string;
}

export function emailReport(reportId: string, recipient: string): Promise<ReportOut> {
  return request<ReportOut>(`/reports/${reportId}/email`, { method: "POST", body: JSON.stringify({ recipient }) });
}

export function listReports(): Promise<ReportOut[]> {
  return request<ReportOut[]>("/reports");
}

export function createReport(payload: { message_id: string; title: string }): Promise<ReportOut> {
  return request<ReportOut>("/reports", { method: "POST", body: JSON.stringify(payload) });
}

export async function getReportPdf(id: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/reports/${id}`, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to load report (${res.status})`, res.status);
  return res.blob();
}

export function deleteReport(id: string): Promise<void> {
  return request<void>(`/reports/${id}`, { method: "DELETE" });
}

export { ApiError };
