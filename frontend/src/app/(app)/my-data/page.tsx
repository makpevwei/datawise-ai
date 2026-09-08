"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import {
  activateDatasetVersion,
  activateDocumentVersion,
  deleteDataset,
  deleteDocument,
  listDatasetLibrary,
  listDatasets,
  listDatasetVersions,
  listDocumentLibrary,
  listDocumentVersions,
  type DatasetLibraryItem,
  type DocumentLibraryItem,
} from "@/lib/api";
import Link from "next/link";
import type { DatasetSummary } from "@/lib/types";
import { UploadPanel } from "@/components/UploadPanel";
import { DatasetExplorer } from "@/components/DatasetExplorer";
import { RelationshipsPanel } from "@/components/RelationshipsPanel";
import { Button, Card, EmptyState, ErrorBanner, SectionHeading, Tabs, formatNumber } from "@/components/ui";

const DELETE_FAILED_MESSAGE = "We couldn't delete this item. Please try again.";

type SubTab = "datasets" | "explore" | "documents" | "relationships" | "upload";

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: "datasets", label: "Datasets" },
  { id: "explore", label: "Explore" },
  { id: "documents", label: "Documents" },
  { id: "relationships", label: "Relationships" },
  { id: "upload", label: "Upload" },
];

const STATUS_STYLES: Record<string, string> = {
  ready: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  pending: "bg-[var(--status-warning)]/20 text-[var(--status-warning)]",
  failed: "bg-[var(--status-critical)]/15 text-[var(--status-critical)]",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status] ?? STATUS_STYLES.pending}`}
    >
      {status}
    </span>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  google_drive: "Google Drive",
  google_sheets: "Google Sheets",
};

/** Marks a row synced from a connected source (Settings > Integrations)
 * apart from a manual upload -- omitted entirely for plain uploads, the
 * overwhelmingly common case, so this stays additive rather than adding
 * visual noise to every row. */
function SourceBadge({ source }: { source: string }) {
  const label = SOURCE_LABELS[source];
  if (!label) return null;
  return (
    <span className="ml-2 inline-flex items-center rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--text-secondary)]">
      {label}
    </span>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function MyDataPage() {
  const [subTab, setSubTab] = useState<SubTab>("datasets");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetLibrary, setDatasetLibrary] = useState<DatasetLibraryItem[]>([]);
  const [documentLibrary, setDocumentLibrary] = useState<DocumentLibraryItem[]>([]);
  const [expandedDatasetId, setExpandedDatasetId] = useState<string | null>(null);
  const [datasetVersions, setDatasetVersions] = useState<DatasetLibraryItem[]>([]);
  const [datasetVersionsLoading, setDatasetVersionsLoading] = useState(false);
  const [expandedDocumentId, setExpandedDocumentId] = useState<string | null>(null);
  const [documentVersions, setDocumentVersions] = useState<DocumentLibraryItem[]>([]);
  const [documentVersionsLoading, setDocumentVersionsLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<Set<string>>(new Set());
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  // `isCancelled` guards against React Strict Mode's dev-only double-effect
  // invocation: the first (aborted) instance's late-settling promise must
  // not overwrite state set by the second (live) instance -- see
  // src/lib/auth-context.tsx for the same pattern with the reasoning.
  const refresh = useCallback((isCancelled: () => boolean = () => false) => {
    listDatasets()
      .then((d) => !isCancelled() && setDatasets(d))
      .catch(() => !isCancelled() && setDatasets([]));
    listDatasetLibrary()
      .then((d) => !isCancelled() && setDatasetLibrary(d))
      .catch(() => !isCancelled() && setDatasetLibrary([]));
    listDocumentLibrary()
      .then((d) => !isCancelled() && setDocumentLibrary(d))
      .catch(() => !isCancelled() && setDocumentLibrary([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    refresh(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  async function handleDeleteDataset(item: DatasetLibraryItem) {
    const message =
      item.file_type === "joined"
        ? 'Delete this joined dataset? This will remove the derived dataset but will not delete its source datasets.'
        : "Delete this dataset? This will remove it from your workspace. Saved historical analyses and reports will not automatically be deleted.";
    if (!confirm(message)) return;
    setDeleteError(null);
    try {
      await deleteDataset(item.id);
      refresh();
    } catch {
      setDeleteError(DELETE_FAILED_MESSAGE);
    }
  }

  async function handleDeleteDocument(id: string) {
    if (!confirm("Delete this document? This will remove it from your workspace. Saved historical analyses and reports will not automatically be deleted.")) return;
    setDeleteError(null);
    try {
      await deleteDocument(id);
      refresh();
    } catch {
      setDeleteError(DELETE_FAILED_MESSAGE);
    }
  }

  async function toggleDatasetVersions(id: string) {
    if (expandedDatasetId === id) {
      setExpandedDatasetId(null);
      return;
    }
    setExpandedDatasetId(id);
    setDatasetVersionsLoading(true);
    setDatasetVersions(await listDatasetVersions(id).catch(() => []));
    setDatasetVersionsLoading(false);
  }

  async function handleActivateDatasetVersion(id: string) {
    await activateDatasetVersion(id);
    setDatasetVersions(expandedDatasetId ? await listDatasetVersions(expandedDatasetId).catch(() => []) : []);
    refresh();
  }

  async function handleDeleteDatasetVersion(id: string) {
    if (!confirm("Delete this version? This cannot be undone.")) return;
    setDeleteError(null);
    try {
      await deleteDataset(id);
      setDatasetVersions(expandedDatasetId ? await listDatasetVersions(expandedDatasetId).catch(() => []) : []);
      refresh();
    } catch {
      setDeleteError(DELETE_FAILED_MESSAGE);
    }
  }

  async function toggleDocumentVersions(id: string) {
    if (expandedDocumentId === id) {
      setExpandedDocumentId(null);
      return;
    }
    setExpandedDocumentId(id);
    setDocumentVersionsLoading(true);
    setDocumentVersions(await listDocumentVersions(id).catch(() => []));
    setDocumentVersionsLoading(false);
  }

  async function handleActivateDocumentVersion(id: string) {
    await activateDocumentVersion(id);
    setDocumentVersions(expandedDocumentId ? await listDocumentVersions(expandedDocumentId).catch(() => []) : []);
    refresh();
  }

  async function handleDeleteDocumentVersion(id: string) {
    if (!confirm("Delete this version? This cannot be undone.")) return;
    setDeleteError(null);
    try {
      await deleteDocument(id);
      setDocumentVersions(expandedDocumentId ? await listDocumentVersions(expandedDocumentId).catch(() => []) : []);
      refresh();
    } catch {
      setDeleteError(DELETE_FAILED_MESSAGE);
    }
  }

  function toggleDatasetSelection(id: string) {
    setSelectedDatasetIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllDatasets() {
    setSelectedDatasetIds((prev) =>
      prev.size === datasetLibrary.length ? new Set() : new Set(datasetLibrary.map((d) => d.id)),
    );
  }

  async function handleBulkDeleteDatasets() {
    const count = selectedDatasetIds.size;
    if (count === 0) return;
    if (!confirm(`Delete ${count} dataset${count === 1 ? "" : "s"}? This will remove ${count === 1 ? "it" : "them"} from your workspace. Saved historical analyses and reports will not automatically be deleted.`)) return;
    setDeleteError(null);
    setBulkDeleting(true);
    try {
      const results = await Promise.allSettled([...selectedDatasetIds].map((id) => deleteDataset(id)));
      if (results.some((r) => r.status === "rejected")) setDeleteError(DELETE_FAILED_MESSAGE);
      setSelectedDatasetIds(new Set());
      refresh();
    } finally {
      setBulkDeleting(false);
    }
  }

  function toggleDocumentSelection(id: string) {
    setSelectedDocumentIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllDocuments() {
    setSelectedDocumentIds((prev) =>
      prev.size === documentLibrary.length ? new Set() : new Set(documentLibrary.map((d) => d.id)),
    );
  }

  async function handleBulkDeleteDocuments() {
    const count = selectedDocumentIds.size;
    if (count === 0) return;
    if (!confirm(`Delete ${count} document${count === 1 ? "" : "s"}? This will remove ${count === 1 ? "it" : "them"} from your workspace. Saved historical analyses and reports will not automatically be deleted.`)) return;
    setDeleteError(null);
    setBulkDeleting(true);
    try {
      const results = await Promise.allSettled([...selectedDocumentIds].map((id) => deleteDocument(id)));
      if (results.some((r) => r.status === "rejected")) setDeleteError(DELETE_FAILED_MESSAGE);
      setSelectedDocumentIds(new Set());
      refresh();
    } finally {
      setBulkDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading title="My Data" subtitle="Datasets and documents you've uploaded, and how they were processed." />
      {deleteError && <ErrorBanner message={deleteError} />}
      <Tabs tabs={SUB_TABS} active={subTab} onChange={(id) => setSubTab(id as SubTab)} />

      {subTab === "datasets" && (
        <Card>
          {datasetLibrary.length === 0 ? (
            <EmptyState
              title="No datasets uploaded yet."
              description="Upload a CSV or Excel file to start analyzing your business data."
              action={<Button onClick={() => setSubTab("upload")}>Upload Dataset</Button>}
            />
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    checked={datasetLibrary.length > 0 && selectedDatasetIds.size === datasetLibrary.length}
                    ref={(el) => {
                      if (el) el.indeterminate = selectedDatasetIds.size > 0 && selectedDatasetIds.size < datasetLibrary.length;
                    }}
                    onChange={toggleAllDatasets}
                    className="h-4 w-4 rounded border-[var(--border)]"
                  />
                  Select all
                </label>
                {selectedDatasetIds.size > 0 && (
                  <>
                    <span className="text-xs text-[var(--text-secondary)]">{selectedDatasetIds.size} selected</span>
                    <Button variant="ghost" onClick={() => setSelectedDatasetIds(new Set())} disabled={bulkDeleting}>
                      Clear
                    </Button>
                    <button
                      onClick={handleBulkDeleteDatasets}
                      disabled={bulkDeleting}
                      className="text-xs font-medium text-[var(--status-critical)] hover:underline disabled:opacity-40"
                    >
                      {bulkDeleting ? "Deleting…" : `Delete ${selectedDatasetIds.size} selected`}
                    </button>
                  </>
                )}
              </div>

              {/* Mobile card list — one card per dataset, visible below sm breakpoint.
                  Replaces the 8-column table that required horizontal scroll with no
                  sticky Name column, making rows impossible to use on 390px. */}
              <ul className="flex flex-col divide-y divide-[var(--border)] sm:hidden">
                {datasetLibrary.map((d) => (
                  <li key={d.id} className="flex items-start gap-3 py-3">
                    <input
                      type="checkbox"
                      checked={selectedDatasetIds.has(d.id)}
                      onChange={() => toggleDatasetSelection(d.id)}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-[var(--border)]"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="truncate text-sm font-medium text-[var(--text-primary)]">{d.display_name}</span>
                        <span className="text-xs text-[var(--text-muted)]">v{d.version}</span>
                        <SourceBadge source={d.source} />
                        <StatusBadge status={d.processing_status} />
                      </div>
                      <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                        {d.file_type.toUpperCase()} · {formatBytes(d.file_size)}
                        {d.row_count !== null ? ` · ${formatNumber(d.row_count)} rows` : ""}
                        {" · "}{new Date(d.created_at).toLocaleDateString()}
                      </p>
                      {/* Action row — py-2 gives each link a ~36px tap target within its row */}
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                        <button
                          onClick={() => setSubTab("explore")}
                          className="py-1 text-xs font-medium text-[var(--brand)] hover:underline"
                        >
                          Open
                        </button>
                        <Link href="/analyze" className="py-1 text-xs font-medium text-[var(--brand)] hover:underline">
                          Analyze
                        </Link>
                        <Link href="/ask" className="py-1 text-xs font-medium text-[var(--brand)] hover:underline">
                          Ask DataWise
                        </Link>
                        <button
                          onClick={() => toggleDatasetVersions(d.id)}
                          className="py-1 text-xs font-medium text-[var(--text-secondary)] hover:underline"
                        >
                          {expandedDatasetId === d.id ? "Hide Versions" : "Versions"}
                        </button>
                        <button
                          onClick={() => handleDeleteDataset(d)}
                          className="py-1 text-xs font-medium text-[var(--status-critical)] hover:underline"
                        >
                          Delete
                        </button>
                      </div>
                      {expandedDatasetId === d.id && (
                        <div className="mt-2 rounded-lg bg-[var(--surface-2)] px-3 py-2">
                          {datasetVersionsLoading ? (
                            <p className="text-xs text-[var(--text-muted)]">Loading versions…</p>
                          ) : datasetVersions.length === 0 ? (
                            <p className="text-xs text-[var(--text-muted)]">No versions found.</p>
                          ) : (
                            <div className="flex flex-col gap-1.5">
                              {datasetVersions.map((v) => (
                                <div key={v.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                                  <span className="font-medium text-[var(--text-primary)]">v{v.version}</span>
                                  {v.is_active ? (
                                    <span className="rounded-full bg-[var(--status-good)]/15 px-2 py-0.5 font-medium text-[var(--status-good)]">Active</span>
                                  ) : (
                                    <button onClick={() => handleActivateDatasetVersion(v.id)} className="font-medium text-[var(--brand)] hover:underline">Activate</button>
                                  )}
                                  <span className="text-[var(--text-secondary)]">
                                    {v.row_count !== null ? `${formatNumber(v.row_count)} rows` : "—"} · {new Date(v.created_at).toLocaleDateString()}
                                  </span>
                                  <button onClick={() => handleDeleteDatasetVersion(v.id)} className="text-[var(--status-critical)] hover:underline">Delete</button>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>

              {/* Desktop table — hidden below sm, full 8-column layout above */}
              <div className="hidden overflow-x-auto sm:block">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                      <th className="py-2 pr-2 font-medium"></th>
                      <th className="py-2 pr-4 font-medium">Name</th>
                      <th className="py-2 pr-4 font-medium">Type</th>
                      <th className="py-2 pr-4 font-medium">Size</th>
                      <th className="py-2 pr-4 font-medium">Rows</th>
                      <th className="py-2 pr-4 font-medium">Status</th>
                      <th className="py-2 pr-4 font-medium">Uploaded</th>
                      <th className="py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datasetLibrary.map((d) => (
                      <Fragment key={d.id}>
                        <tr className="border-b border-[var(--border)] last:border-0">
                          <td className="py-2.5 pr-2">
                            <input
                              type="checkbox"
                              checked={selectedDatasetIds.has(d.id)}
                              onChange={() => toggleDatasetSelection(d.id)}
                              className="h-4 w-4 rounded border-[var(--border)]"
                            />
                          </td>
                          <td className="py-2.5 pr-4 text-[var(--text-primary)]">
                            {d.display_name} <span className="text-xs text-[var(--text-muted)]">v{d.version}</span>
                            <SourceBadge source={d.source} />
                          </td>
                          <td className="py-2.5 pr-4 uppercase text-[var(--text-secondary)]">{d.file_type}</td>
                          <td className="py-2.5 pr-4 text-[var(--text-secondary)]">{formatBytes(d.file_size)}</td>
                          <td className="py-2.5 pr-4 text-[var(--text-secondary)]">
                            {d.row_count !== null ? formatNumber(d.row_count) : "—"}
                          </td>
                          <td className="py-2.5 pr-4">
                            <StatusBadge status={d.processing_status} />
                          </td>
                          <td className="py-2.5 pr-4 text-[var(--text-secondary)]">
                            {new Date(d.created_at).toLocaleDateString()}
                          </td>
                          <td className="py-2.5">
                            <div className="flex items-center gap-3">
                              <button onClick={() => setSubTab("explore")} className="text-xs font-medium text-[var(--brand)] hover:underline">Open</button>
                              <Link href="/analyze" className="text-xs font-medium text-[var(--brand)] hover:underline">Analyze</Link>
                              <Link href="/ask" className="text-xs font-medium text-[var(--brand)] hover:underline">Ask DataWise</Link>
                              <button onClick={() => toggleDatasetVersions(d.id)} className="text-xs font-medium text-[var(--text-secondary)] hover:underline">
                                {expandedDatasetId === d.id ? "Hide Versions" : "Versions"}
                              </button>
                              <button onClick={() => handleDeleteDataset(d)} className="text-xs font-medium text-[var(--status-critical)] hover:underline">Delete</button>
                            </div>
                          </td>
                        </tr>
                        {expandedDatasetId === d.id && (
                          <tr className="border-b border-[var(--border)] last:border-0">
                            <td colSpan={8} className="bg-[var(--surface-2)] px-4 py-3">
                              {datasetVersionsLoading ? (
                                <p className="text-xs text-[var(--text-muted)]">Loading versions…</p>
                              ) : datasetVersions.length === 0 ? (
                                <p className="text-xs text-[var(--text-muted)]">No versions found.</p>
                              ) : (
                                <div className="flex flex-col gap-1.5">
                                  {datasetVersions.map((v) => (
                                    <div key={v.id} className="flex items-center gap-3 text-xs">
                                      <span className="font-medium text-[var(--text-primary)]">v{v.version}</span>
                                      {v.is_active ? (
                                        <span className="rounded-full bg-[var(--status-good)]/15 px-2 py-0.5 font-medium text-[var(--status-good)]">Active</span>
                                      ) : (
                                        <button onClick={() => handleActivateDatasetVersion(v.id)} className="font-medium text-[var(--brand)] hover:underline">Activate</button>
                                      )}
                                      <span className="text-[var(--text-secondary)]">
                                        {v.row_count !== null ? `${formatNumber(v.row_count)} rows` : "—"} · {new Date(v.created_at).toLocaleDateString()}
                                      </span>
                                      <button onClick={() => handleDeleteDatasetVersion(v.id)} className="text-[var(--status-critical)] hover:underline">Delete</button>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      )}

      {subTab === "explore" &&
        (datasets.length === 0 ? (
          <EmptyState title="No datasets available yet." description="Upload a dataset to inspect its schema and quality." />
        ) : (
          <DatasetExplorer datasets={datasets} />
        ))}

      {subTab === "documents" && (
        <Card>
          {documentLibrary.length === 0 ? (
            <EmptyState
              title="No documents uploaded yet."
              description="Upload a PDF, DOCX, PPTX, TXT, MD, PY, or HTML file so DataWise can search and cite it."
              action={<Button onClick={() => setSubTab("upload")}>Upload Document</Button>}
            />
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    checked={documentLibrary.length > 0 && selectedDocumentIds.size === documentLibrary.length}
                    ref={(el) => {
                      if (el) el.indeterminate = selectedDocumentIds.size > 0 && selectedDocumentIds.size < documentLibrary.length;
                    }}
                    onChange={toggleAllDocuments}
                    className="h-4 w-4 rounded border-[var(--border)]"
                  />
                  Select all
                </label>
                {selectedDocumentIds.size > 0 && (
                  <>
                    <span className="text-xs text-[var(--text-secondary)]">{selectedDocumentIds.size} selected</span>
                    <Button variant="ghost" onClick={() => setSelectedDocumentIds(new Set())} disabled={bulkDeleting}>
                      Clear
                    </Button>
                    <button
                      onClick={handleBulkDeleteDocuments}
                      disabled={bulkDeleting}
                      className="text-xs font-medium text-[var(--status-critical)] hover:underline disabled:opacity-40"
                    >
                      {bulkDeleting ? "Deleting…" : `Delete ${selectedDocumentIds.size} selected`}
                    </button>
                  </>
                )}
              </div>

              {/* Mobile card list — same pattern as Datasets tab */}
              <ul className="flex flex-col divide-y divide-[var(--border)] sm:hidden">
                {documentLibrary.map((d) => (
                  <li key={d.id} className="flex items-start gap-3 py-3">
                    <input
                      type="checkbox"
                      checked={selectedDocumentIds.has(d.id)}
                      onChange={() => toggleDocumentSelection(d.id)}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-[var(--border)]"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="truncate text-sm font-medium text-[var(--text-primary)]">{d.filename}</span>
                        <span className="text-xs text-[var(--text-muted)]">v{d.version}</span>
                        <SourceBadge source={d.source} />
                        <StatusBadge status={d.embedding_status} />
                      </div>
                      <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                        {d.file_type.toUpperCase()} · {formatBytes(d.file_size)}
                        {d.chunk_count != null ? ` · ${d.chunk_count} chunks` : ""}
                        {" · "}{new Date(d.created_at).toLocaleDateString()}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                        <button
                          onClick={() => toggleDocumentVersions(d.id)}
                          className="py-1 text-xs font-medium text-[var(--text-secondary)] hover:underline"
                        >
                          {expandedDocumentId === d.id ? "Hide Versions" : "Versions"}
                        </button>
                        <button
                          onClick={() => handleDeleteDocument(d.id)}
                          className="py-1 text-xs font-medium text-[var(--status-critical)] hover:underline"
                        >
                          Delete
                        </button>
                      </div>
                      {expandedDocumentId === d.id && (
                        <div className="mt-2 rounded-lg bg-[var(--surface-2)] px-3 py-2">
                          {documentVersionsLoading ? (
                            <p className="text-xs text-[var(--text-muted)]">Loading versions…</p>
                          ) : documentVersions.length === 0 ? (
                            <p className="text-xs text-[var(--text-muted)]">No versions found.</p>
                          ) : (
                            <div className="flex flex-col gap-1.5">
                              {documentVersions.map((v) => (
                                <div key={v.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                                  <span className="font-medium text-[var(--text-primary)]">v{v.version}</span>
                                  {v.is_active ? (
                                    <span className="rounded-full bg-[var(--status-good)]/15 px-2 py-0.5 font-medium text-[var(--status-good)]">Active</span>
                                  ) : (
                                    <button onClick={() => handleActivateDocumentVersion(v.id)} className="font-medium text-[var(--brand)] hover:underline">Activate</button>
                                  )}
                                  <span className="text-[var(--text-secondary)]">
                                    {v.chunk_count ?? "—"} chunks · {new Date(v.created_at).toLocaleDateString()}
                                  </span>
                                  <button onClick={() => handleDeleteDocumentVersion(v.id)} className="text-[var(--status-critical)] hover:underline">Delete</button>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>

              {/* Desktop table — hidden below sm */}
              <div className="hidden overflow-x-auto sm:block">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--text-secondary)]">
                      <th className="py-2 pr-2 font-medium"></th>
                      <th className="py-2 pr-4 font-medium">Name</th>
                      <th className="py-2 pr-4 font-medium">Type</th>
                      <th className="py-2 pr-4 font-medium">Size</th>
                      <th className="py-2 pr-4 font-medium">Chunks</th>
                      <th className="py-2 pr-4 font-medium">Status</th>
                      <th className="py-2 pr-4 font-medium">Uploaded</th>
                      <th className="py-2 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documentLibrary.map((d) => (
                      <Fragment key={d.id}>
                        <tr className="border-b border-[var(--border)] last:border-0">
                          <td className="py-2.5 pr-2">
                            <input
                              type="checkbox"
                              checked={selectedDocumentIds.has(d.id)}
                              onChange={() => toggleDocumentSelection(d.id)}
                              className="h-4 w-4 rounded border-[var(--border)]"
                            />
                          </td>
                          <td className="py-2.5 pr-4 text-[var(--text-primary)]">
                            {d.filename} <span className="text-xs text-[var(--text-muted)]">v{d.version}</span>
                            <SourceBadge source={d.source} />
                          </td>
                          <td className="py-2.5 pr-4 uppercase text-[var(--text-secondary)]">{d.file_type}</td>
                          <td className="py-2.5 pr-4 text-[var(--text-secondary)]">{formatBytes(d.file_size)}</td>
                          <td className="py-2.5 pr-4 text-[var(--text-secondary)]">{d.chunk_count ?? "—"}</td>
                          <td className="py-2.5 pr-4">
                            <StatusBadge status={d.embedding_status} />
                          </td>
                          <td className="py-2.5 pr-4 text-[var(--text-secondary)]">
                            {new Date(d.created_at).toLocaleDateString()}
                          </td>
                          <td className="py-2.5">
                            <div className="flex items-center gap-3">
                              <button onClick={() => toggleDocumentVersions(d.id)} className="text-xs font-medium text-[var(--text-secondary)] hover:underline">
                                {expandedDocumentId === d.id ? "Hide Versions" : "Versions"}
                              </button>
                              <button onClick={() => handleDeleteDocument(d.id)} className="text-xs font-medium text-[var(--status-critical)] hover:underline">Delete</button>
                            </div>
                          </td>
                        </tr>
                        {expandedDocumentId === d.id && (
                          <tr className="border-b border-[var(--border)] last:border-0">
                            <td colSpan={8} className="bg-[var(--surface-2)] px-4 py-3">
                              {documentVersionsLoading ? (
                                <p className="text-xs text-[var(--text-muted)]">Loading versions…</p>
                              ) : documentVersions.length === 0 ? (
                                <p className="text-xs text-[var(--text-muted)]">No versions found.</p>
                              ) : (
                                <div className="flex flex-col gap-1.5">
                                  {documentVersions.map((v) => (
                                    <div key={v.id} className="flex items-center gap-3 text-xs">
                                      <span className="font-medium text-[var(--text-primary)]">v{v.version}</span>
                                      {v.is_active ? (
                                        <span className="rounded-full bg-[var(--status-good)]/15 px-2 py-0.5 font-medium text-[var(--status-good)]">Active</span>
                                      ) : (
                                        <button onClick={() => handleActivateDocumentVersion(v.id)} className="font-medium text-[var(--brand)] hover:underline">Activate</button>
                                      )}
                                      <span className="text-[var(--text-secondary)]">
                                        {v.chunk_count ?? "—"} chunks · {new Date(v.created_at).toLocaleDateString()}
                                      </span>
                                      <button onClick={() => handleDeleteDocumentVersion(v.id)} className="text-[var(--status-critical)] hover:underline">Delete</button>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      )}

      {subTab === "relationships" &&
        (datasets.length === 0 ? (
          <EmptyState title="No datasets available yet." description="Upload at least one dataset to discover relationships." />
        ) : (
          <RelationshipsPanel datasets={datasets} onJoined={refresh} />
        ))}

      {subTab === "upload" && <UploadPanel onUploaded={refresh} />}
    </div>
  );
}
