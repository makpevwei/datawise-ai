"use client";

import { useRef, useState } from "react";
import {
  checkDatasetDuplicate,
  checkDocumentDuplicate,
  uploadDatasets,
  uploadDocuments,
  type DuplicateCheckResult,
} from "@/lib/api";
import type { DocumentUploadResult, UploadResult } from "@/lib/types";
import { Button, Card, ErrorBanner, SectionHeading, Spinner } from "./ui";

const DATASET_EXTENSIONS = [".csv", ".xlsx"];
const DOCUMENT_EXTENSIONS = [".pdf", ".docx", ".pptx", ".txt", ".md", ".py", ".html", ".htm"];

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type PendingFile = { file: File; kind: "dataset" | "document"; check: DuplicateCheckResult };
type DialogChoice = "use_existing" | "replace" | "cancel" | "confirm_version";

export function UploadPanel({ onUploaded }: { onUploaded: () => void }) {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [datasetResult, setDatasetResult] = useState<UploadResult | null>(null);
  const [documentResult, setDocumentResult] = useState<DocumentUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogFile, setDialogFile] = useState<PendingFile | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function waitForChoice(): Promise<DialogChoice> {
    return new Promise((resolve) => {
      resolveChoiceRef.current = resolve;
    });
  }
  const resolveChoiceRef = useRef<((choice: DialogChoice) => void) | null>(null);

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const files = Array.from(fileList);
    const datasetFiles = files.filter((f) => DATASET_EXTENSIONS.includes(extensionOf(f.name)));
    const documentFiles = files.filter((f) => DOCUMENT_EXTENSIONS.includes(extensionOf(f.name)));

    setError(null);
    setDatasetResult(null);
    setDocumentResult(null);
    setChecking(true);

    // Duplicate detection happens before anything is processed (section 5-6):
    // one dry-run hash check per file, no parsing, so the user can choose
    // Use Existing / Replace / Cancel before any expensive work starts.
    //
    // The checks themselves are read-only (a hash + one DB lookup, no
    // mutation) and independent of each other, so they run concurrently
    // instead of one HTTP round-trip at a time -- with several files, the
    // sequential version made "Checking for existing versions..." scale
    // with file count x network latency instead of just the slowest single
    // check. The dialog-approval loop below stays sequential on purpose: a
    // person can only answer one confirmation dialog at a time, and that
    // order must still match the order files were selected in.
    const toUploadDatasets: { file: File; force: boolean }[] = [];
    const toUploadDocuments: { file: File; force: boolean }[] = [];
    const reusedDatasetNotes: string[] = [];
    const reusedDocumentNotes: string[] = [];

    try {
      const [datasetChecks, documentChecks] = await Promise.all([
        Promise.all(datasetFiles.map(async (file) => ({ file, check: await checkDatasetDuplicate(file) }))),
        Promise.all(documentFiles.map(async (file) => ({ file, check: await checkDocumentDuplicate(file) }))),
      ]);

      for (const { file, check } of datasetChecks) {
        if (check.status === "new") {
          toUploadDatasets.push({ file, force: false });
          continue;
        }
        setDialogFile({ file, kind: "dataset", check });
        const choice = await waitForChoice();
        setDialogFile(null);
        if (choice === "cancel") continue;
        if (choice === "use_existing") {
          reusedDatasetNotes.push(`${file.name} — using the existing version.`);
          continue;
        }
        toUploadDatasets.push({ file, force: choice === "replace" });
      }

      for (const { file, check } of documentChecks) {
        if (check.status === "new") {
          toUploadDocuments.push({ file, force: false });
          continue;
        }
        setDialogFile({ file, kind: "document", check });
        const choice = await waitForChoice();
        setDialogFile(null);
        if (choice === "cancel") continue;
        if (choice === "use_existing") {
          reusedDocumentNotes.push(`${file.name} — using the existing version.`);
          continue;
        }
        toUploadDocuments.push({ file, force: choice === "replace" });
      }
    } finally {
      setChecking(false);
    }

    if (toUploadDatasets.length === 0 && toUploadDocuments.length === 0) {
      if (reusedDatasetNotes.length || reusedDocumentNotes.length) {
        setDatasetResult({ datasets: [], warnings: reusedDatasetNotes.map((message) => ({ file: "", sheet: null, message })), errors: [] });
      }
      return;
    }

    setUploading(true);
    try {
      const datasetResults: UploadResult[] = [];
      for (const { file, force } of toUploadDatasets) {
        datasetResults.push(await uploadDatasets([file], force));
      }
      const documentResults: DocumentUploadResult[] = [];
      for (const { file, force } of toUploadDocuments) {
        documentResults.push(await uploadDocuments([file], force));
      }

      const mergedDatasets: UploadResult | null = toUploadDatasets.length
        ? {
            datasets: datasetResults.flatMap((r) => r.datasets),
            warnings: [...reusedDatasetNotes.map((message) => ({ file: "", sheet: null, message })), ...datasetResults.flatMap((r) => r.warnings)],
            errors: datasetResults.flatMap((r) => r.errors),
          }
        : reusedDatasetNotes.length
          ? { datasets: [], warnings: reusedDatasetNotes.map((message) => ({ file: "", sheet: null, message })), errors: [] }
          : null;
      const mergedDocuments: DocumentUploadResult | null = toUploadDocuments.length
        ? { documents: documentResults.flatMap((r) => r.documents), errors: documentResults.flatMap((r) => r.errors) }
        : null;

      setDatasetResult(mergedDatasets);
      setDocumentResult(mergedDocuments);
      if ((mergedDatasets && mergedDatasets.datasets.length > 0) || (mergedDocuments && mergedDocuments.documents.length > 0)) {
        onUploaded();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading
        title="Upload datasets & documents"
        subtitle="Datasets: CSV or Excel (.xlsx) — multi-sheet workbooks split into one dataset per sheet. Documents: PDF, DOCX, PPTX, TXT, MD, PY, or HTML — indexed for the AI analyst to search and cite."
      />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-16 text-center transition-colors ${
          dragOver
            ? "border-[var(--series-1)] bg-[var(--series-1)]/5"
            : "border-[var(--border)] hover:border-[var(--series-1)]/50"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={[...DATASET_EXTENSIONS, ...DOCUMENT_EXTENSIONS].join(",")}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        {checking ? (
          <>
            <Spinner />
            <p className="text-sm text-[var(--text-secondary)]">Checking for existing versions…</p>
          </>
        ) : uploading ? (
          <>
            <Spinner />
            <p className="text-sm text-[var(--text-secondary)]">
              Uploading and processing — this can take a while for large workbooks or PDFs.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-[var(--text-primary)]">
              Drop files here, or click to browse
            </p>
            <p className="text-xs text-[var(--text-muted)]">
              .csv, .xlsx, .pdf, .docx, .pptx, .txt, .md, .py, .html — multiple files supported
            </p>
          </>
        )}
      </div>

      {dialogFile && (
        <DuplicateDialog
          pending={dialogFile}
          onChoice={(choice) => resolveChoiceRef.current?.(choice)}
        />
      )}

      {error && <ErrorBanner message={error} />}

      {(datasetResult || documentResult) && (
        <div className="flex flex-col gap-4">
          {datasetResult && datasetResult.datasets.length > 0 && (
            <Card>
              <p className="mb-2 text-sm font-medium text-[var(--status-good)]">
                DATASET · {datasetResult.datasets.length} loaded
              </p>
              <ul className="flex flex-col gap-1 text-sm text-[var(--text-secondary)]">
                {datasetResult.datasets.map((d) => (
                  <li key={d.id}>
                    {d.name} — {d.row_count.toLocaleString()} rows, {d.column_count} columns
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {documentResult && documentResult.documents.length > 0 && (
            <Card>
              <p className="mb-2 text-sm font-medium text-[var(--series-2)]">
                DOCUMENT · {documentResult.documents.length} loaded
              </p>
              <ul className="flex flex-col gap-1 text-sm text-[var(--text-secondary)]">
                {documentResult.documents.map((d) => (
                  <li key={d.id}>
                    {d.filename} — {d.document_type.toUpperCase()}, {d.chunk_count} chunks
                    {d.extraction_warnings.length > 0 && (
                      <span className="text-[var(--status-warning)]"> ({d.extraction_warnings.join("; ")})</span>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {datasetResult && datasetResult.warnings.length > 0 && (
            <Card className="border-[var(--status-warning)]/40">
              <p className="mb-2 text-sm font-medium text-[var(--status-warning)]">Dataset notices</p>
              <ul className="flex flex-col gap-1 text-sm text-[var(--text-secondary)]">
                {datasetResult.warnings.map((w, i) => (
                  <li key={i}>
                    {w.file ? `${w.file}${w.sheet ? ` (${w.sheet})` : ""}: ` : ""}
                    {w.message}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {((datasetResult && datasetResult.errors.length > 0) ||
            (documentResult && documentResult.errors.length > 0)) && (
            <Card className="border-[var(--status-critical)]/40">
              <p className="mb-2 text-sm font-medium text-[var(--status-critical)]">Errors</p>
              <ul className="flex flex-col gap-1 text-sm text-[var(--text-secondary)]">
                {datasetResult?.errors.map((err, i) => (
                  <li key={`d-${i}`}>
                    {err.file}: {err.message}
                  </li>
                ))}
                {documentResult?.errors.map((err, i) => (
                  <li key={`doc-${i}`}>
                    {err.file}: {err.message}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <div>
            <Button variant="secondary" onClick={() => inputRef.current?.click()}>
              Upload more files
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function DuplicateDialog({
  pending,
  onChoice,
}: {
  pending: PendingFile;
  onChoice: (choice: DialogChoice) => void;
}) {
  const { file, check } = pending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <Card className="w-full max-w-md">
        {check.status === "exact_duplicate" ? (
          <>
            <p className="mb-1 text-sm font-semibold text-[var(--text-primary)]">
              This dataset already exists in your workspace.
            </p>
            <p className="mb-4 text-xs text-[var(--text-secondary)]">{file.name}</p>
            {check.existing && (
              <dl className="mb-5 flex flex-col gap-1 text-xs text-[var(--text-secondary)]">
                <div>
                  <dt className="inline font-semibold">Current version:</dt> <dd className="inline">v{check.existing.version}</dd>
                </div>
                <div>
                  <dt className="inline font-semibold">Uploaded:</dt>{" "}
                  <dd className="inline">{new Date(check.existing.created_at).toLocaleString()}</dd>
                </div>
                {"row_count" in check.existing && check.existing.row_count !== null && (
                  <div>
                    <dt className="inline font-semibold">Rows:</dt> <dd className="inline">{check.existing.row_count.toLocaleString()}</dd>
                  </div>
                )}
                <div>
                  <dt className="inline font-semibold">Size:</dt> <dd className="inline">{formatBytes(check.existing.file_size)}</dd>
                </div>
              </dl>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => onChoice("cancel")}>
                Cancel
              </Button>
              <Button variant="secondary" onClick={() => onChoice("replace")}>
                Replace
              </Button>
              <Button onClick={() => onChoice("use_existing")}>Use Existing</Button>
            </div>
          </>
        ) : (
          <>
            <p className="mb-1 text-sm font-semibold text-[var(--text-primary)]">
              This file has changed since the last upload.
            </p>
            <p className="mb-4 text-xs text-[var(--text-secondary)]">
              {file.name} — this will create Version {check.next_version} and make it active. The previous version
              stays available until you delete it.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => onChoice("cancel")}>
                Cancel
              </Button>
              <Button onClick={() => onChoice("confirm_version")}>Create Version {check.next_version}</Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
