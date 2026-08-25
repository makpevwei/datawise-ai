import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UploadPanel } from "../UploadPanel";
import * as api from "@/lib/api";

describe("UploadPanel", () => {
  beforeEach(() => {
    // Every upload now does a duplicate pre-check first (section 5-6);
    // default both to "new" so existing single-upload tests exercise the
    // same straight-through path they did before that feature existed.
    // Tests that specifically exercise the duplicate dialog override these.
    vi.spyOn(api, "checkDatasetDuplicate").mockResolvedValue({ status: "new", existing: null, next_version: null });
    vi.spyOn(api, "checkDocumentDuplicate").mockResolvedValue({ status: "new", existing: null, next_version: null });
  });

  it("shows the drop zone by default", () => {
    render(<UploadPanel onUploaded={vi.fn()} />);
    expect(screen.getByText(/drop files here, or click to browse/i)).toBeInTheDocument();
  });

  it("uploads a file and renders the resulting datasets", async () => {
    const onUploaded = vi.fn();
    vi.spyOn(api, "uploadDatasets").mockResolvedValue({
      datasets: [
        {
          id: "d1",
          name: "customers.csv",
          source_file: "customers.csv",
          sheet_name: null,
          kind: "uploaded",
          row_count: 8,
          column_count: 3,
          quality_rating: "good",
          created_at: new Date().toISOString(),
        },
      ],
      warnings: [],
      errors: [],
    });

    render(<UploadPanel onUploaded={onUploaded} />);

    const file = new File(["a,b\n1,2"], "customers.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText(/dataset · 1 loaded/i)).toBeInTheDocument());
    expect(screen.getByText(/customers\.csv — 8 rows, 3 columns/i)).toBeInTheDocument();
    expect(onUploaded).toHaveBeenCalled();
  });

  it("shows per-file errors without blocking the panel", async () => {
    vi.spyOn(api, "uploadDatasets").mockResolvedValue({
      datasets: [],
      warnings: [],
      errors: [{ file: "bad.xlsx", sheet: null, message: "not a valid .xlsx file" }],
    });

    render(<UploadPanel onUploaded={vi.fn()} />);

    const file = new File(["not a workbook"], "bad.xlsx");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText(/not a valid \.xlsx file/i)).toBeInTheDocument());
  });

  it("routes a document file to the document endpoint and labels it DOCUMENT", async () => {
    const uploadDocsSpy = vi.spyOn(api, "uploadDocuments").mockResolvedValue({
      documents: [
        {
          id: "doc1",
          filename: "report.pdf",
          document_type: "pdf",
          chunk_count: 3,
          char_count: 900,
          created_at: new Date().toISOString(),
          extraction_warnings: [],
        },
      ],
      errors: [],
    });
    const uploadDatasetsSpy = vi.spyOn(api, "uploadDatasets");

    render(<UploadPanel onUploaded={vi.fn()} />);

    const file = new File(["%PDF-1.4 fake"], "report.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText(/document · 1 loaded/i)).toBeInTheDocument());
    expect(screen.getByText(/report\.pdf — PDF, 3 chunks/i)).toBeInTheDocument();
    expect(uploadDocsSpy).toHaveBeenCalled();
    expect(uploadDatasetsSpy).not.toHaveBeenCalled();
  });

  it("uploads a dataset and a document from the same drop and shows both sections", async () => {
    vi.spyOn(api, "uploadDatasets").mockResolvedValue({
      datasets: [
        {
          id: "d1", name: "orders.csv", source_file: "orders.csv", sheet_name: null,
          kind: "uploaded", row_count: 5, column_count: 2, quality_rating: "good",
          created_at: new Date().toISOString(),
        },
      ],
      warnings: [], errors: [],
    });
    vi.spyOn(api, "uploadDocuments").mockResolvedValue({
      documents: [
        {
          id: "doc1", filename: "notes.md", document_type: "md", chunk_count: 1,
          char_count: 50, created_at: new Date().toISOString(), extraction_warnings: [],
        },
      ],
      errors: [],
    });

    render(<UploadPanel onUploaded={vi.fn()} />);

    const files = [
      new File(["a,b\n1,2"], "orders.csv", { type: "text/csv" }),
      new File(["# notes"], "notes.md", { type: "text/markdown" }),
    ];
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files } });

    await waitFor(() => expect(screen.getByText(/dataset · 1 loaded/i)).toBeInTheDocument());
    expect(screen.getByText(/document · 1 loaded/i)).toBeInTheDocument();
  });

  it("shows the duplicate dialog for an exact duplicate and uploads nothing on Cancel", async () => {
    vi.spyOn(api, "checkDatasetDuplicate").mockResolvedValue({
      status: "exact_duplicate",
      existing: {
        id: "d1", original_filename: "customers.csv", display_name: "customers.csv", file_type: "csv",
        file_size: 100, row_count: 8, column_count: 3, processing_status: "ready", processing_error: null,
        version: 1, is_active: true, created_at: new Date().toISOString(),
      },
      next_version: null,
    });
    const uploadSpy = vi.spyOn(api, "uploadDatasets");

    render(<UploadPanel onUploaded={vi.fn()} />);
    const file = new File(["a,b\n1,2"], "customers.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText(/this dataset already exists in your workspace/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByText(/this dataset already exists/i)).not.toBeInTheDocument());
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it("uploads nothing but reuses the existing version when Use Existing is chosen", async () => {
    vi.spyOn(api, "checkDatasetDuplicate").mockResolvedValue({
      status: "exact_duplicate",
      existing: {
        id: "d1", original_filename: "customers.csv", display_name: "customers.csv", file_type: "csv",
        file_size: 100, row_count: 8, column_count: 3, processing_status: "ready", processing_error: null,
        version: 1, is_active: true, created_at: new Date().toISOString(),
      },
      next_version: null,
    });
    const uploadSpy = vi.spyOn(api, "uploadDatasets");

    render(<UploadPanel onUploaded={vi.fn()} />);
    const file = new File(["a,b\n1,2"], "customers.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(await screen.findByRole("button", { name: /use existing/i }));

    await waitFor(() => expect(screen.getByText(/using the existing version/i)).toBeInTheDocument());
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it("uploads with force_new_version when Replace is chosen on an exact duplicate", async () => {
    vi.spyOn(api, "checkDatasetDuplicate").mockResolvedValue({
      status: "exact_duplicate",
      existing: {
        id: "d1", original_filename: "customers.csv", display_name: "customers.csv", file_type: "csv",
        file_size: 100, row_count: 8, column_count: 3, processing_status: "ready", processing_error: null,
        version: 1, is_active: true, created_at: new Date().toISOString(),
      },
      next_version: null,
    });
    const uploadSpy = vi.spyOn(api, "uploadDatasets").mockResolvedValue({
      datasets: [
        { id: "d1", name: "customers.csv", source_file: "customers.csv", sheet_name: null, kind: "uploaded", row_count: 8, column_count: 3, quality_rating: "good", created_at: new Date().toISOString() },
      ],
      warnings: [], errors: [],
    });

    render(<UploadPanel onUploaded={vi.fn()} />);
    const file = new File(["a,b\n1,2"], "customers.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(await screen.findByRole("button", { name: /replace/i }));

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledWith([file], true));
  });

  it("shows the version-confirmation dialog for changed content and uploads without forcing on confirm", async () => {
    vi.spyOn(api, "checkDatasetDuplicate").mockResolvedValue({
      status: "changed_version",
      existing: {
        id: "d1", original_filename: "sales.csv", display_name: "sales.csv", file_type: "csv",
        file_size: 100, row_count: 8, column_count: 3, processing_status: "ready", processing_error: null,
        version: 1, is_active: true, created_at: new Date().toISOString(),
      },
      next_version: 2,
    });
    const uploadSpy = vi.spyOn(api, "uploadDatasets").mockResolvedValue({
      datasets: [
        { id: "d2", name: "sales.csv", source_file: "sales.csv", sheet_name: null, kind: "uploaded", row_count: 9, column_count: 3, quality_rating: "good", created_at: new Date().toISOString() },
      ],
      warnings: [], errors: [],
    });

    render(<UploadPanel onUploaded={vi.fn()} />);
    const file = new File(["a,b\n1,2\n3,4"], "sales.csv", { type: "text/csv" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText(/this file has changed since the last upload/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /create version 2/i }));

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledWith([file], false));
  });

  it("dispatches duplicate checks for multiple files concurrently rather than one at a time", async () => {
    // Each file's check only resolves once every file's check has actually
    // been *dispatched* -- if the checks were still sequential (await one,
    // then start the next), the second check would never even be called
    // and this would hang/timeout instead of resolving.
    let dispatched = 0;
    const resolvers: (() => void)[] = [];
    vi.spyOn(api, "checkDatasetDuplicate").mockImplementation(
      () =>
        new Promise((resolve) => {
          dispatched += 1;
          resolvers.push(() => resolve({ status: "new", existing: null, next_version: null }));
          if (dispatched === 3) resolvers.forEach((r) => r());
        }),
    );
    vi.spyOn(api, "uploadDatasets").mockResolvedValue({ datasets: [], warnings: [], errors: [] });

    render(<UploadPanel onUploaded={vi.fn()} />);
    const files = [
      new File(["a,b\n1,2"], "one.csv", { type: "text/csv" }),
      new File(["a,b\n1,2"], "two.csv", { type: "text/csv" }),
      new File(["a,b\n1,2"], "three.csv", { type: "text/csv" }),
    ];
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files } });

    await waitFor(() => expect(api.checkDatasetDuplicate).toHaveBeenCalledTimes(3));
  });
});
