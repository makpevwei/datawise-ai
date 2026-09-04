"use client";

import { useEffect, useState } from "react";
import { getDataset, getDatasetSample } from "@/lib/api";
import type { ColumnProfile, DatasetProfile, DatasetSummary } from "@/lib/types";
import {
  Card,
  EmptyState,
  ErrorBanner,
  QualityBadge,
  SectionHeading,
  Spinner,
  Table,
  formatNumber,
} from "./ui";

const TYPE_STYLES: Record<string, string> = {
  numeric: "text-[var(--series-1)]",
  categorical: "text-[var(--series-3)]",
  date: "text-[var(--series-4)]",
  identifier: "text-[var(--series-7)]",
  boolean: "text-[var(--series-2)]",
  text: "text-[var(--text-secondary)]",
  unknown: "text-[var(--text-muted)]",
};

export function DatasetExplorer({ datasets }: { datasets: DatasetSummary[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const effectiveId = selectedId ?? datasets[0]?.id ?? null;

  if (datasets.length === 0) {
    return (
      <EmptyState
        title="No datasets yet"
        description="Upload a CSV or Excel file from the Upload tab to see it profiled here."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading
        title="Dataset explorer"
        subtitle="Select a dataset to inspect its schema, statistics, missing values, and quality findings."
      />

      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full min-w-max text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--background)] text-[var(--text-secondary)]">
              <th className="px-3 py-2 font-medium">Dataset</th>
              <th className="px-3 py-2 font-medium">Rows</th>
              <th className="px-3 py-2 font-medium">Columns</th>
              <th className="px-3 py-2 font-medium">Quality</th>
              <th className="px-3 py-2 font-medium">Sheet</th>
              <th className="px-3 py-2 font-medium">Kind</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((d) => (
              <tr
                key={d.id}
                onClick={() => setSelectedId(d.id)}
                className={`cursor-pointer border-b border-[var(--border)] last:border-0 hover:bg-[var(--background)] ${
                  effectiveId === d.id ? "bg-[var(--brand-subtle)]" : ""
                }`}
              >
                <td className="px-3 py-2 font-medium text-[var(--text-primary)]">{d.name}</td>
                <td className="px-3 py-2 tabular-nums text-[var(--text-secondary)]">
                  {d.row_count.toLocaleString()}
                </td>
                <td className="px-3 py-2 tabular-nums text-[var(--text-secondary)]">{d.column_count}</td>
                <td className="px-3 py-2">
                  <QualityBadge rating={d.quality_rating} />
                </td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">{d.sheet_name ?? "—"}</td>
                <td className="px-3 py-2 capitalize text-[var(--text-secondary)]">{d.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {effectiveId && <DatasetDetail key={effectiveId} datasetId={effectiveId} />}
    </div>
  );
}

function DatasetDetail({ datasetId }: { datasetId: string }) {
  // Keyed by datasetId in the parent, so a dataset switch remounts this
  // component and its useState initializers naturally reset -- no manual
  // reset-then-fetch effect needed.
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [sample, setSample] = useState<Record<string, unknown>[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getDataset(datasetId), getDatasetSample(datasetId, 10)])
      .then(([p, s]) => {
        if (cancelled) return;
        setProfile(p);
        setSample(s);
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Failed to load dataset."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-[var(--text-secondary)]">
        <Spinner /> Loading dataset profile…
      </div>
    );
  }
  if (error) return <ErrorBanner message={error} />;
  if (!profile) return null;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <SectionHeading title="Schema & column statistics" />
        <ColumnTable columns={profile.columns} />
      </Card>

      <Card>
        <SectionHeading
          title="Data quality"
          subtitle={`${profile.quality.duplicate_row_count} duplicate row(s), ${profile.quality.duplicate_row_percentage}% of all rows.`}
        />
        {profile.quality.notes.length === 0 ? (
          <p className="text-sm text-[var(--text-secondary)]">No notable quality issues detected.</p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-sm text-[var(--text-secondary)]">
            {profile.quality.notes.map((note, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-[var(--status-warning)]">•</span>
                {note}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {sample && sample.length > 0 && (
        <Card>
          <SectionHeading title="Sample records" subtitle="First 10 rows." />
          <Table columns={Object.keys(sample[0])} rows={sample} />
        </Card>
      )}
    </div>
  );
}

function ColumnTable({ columns }: { columns: ColumnProfile[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="w-full min-w-max text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] bg-[var(--background)] text-[var(--text-secondary)]">
            <th className="px-3 py-2 font-medium">Column</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Missing</th>
            <th className="px-3 py-2 font-medium">Unique</th>
            <th className="px-3 py-2 font-medium">Summary</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((col) => (
            <tr key={col.name} className="border-b border-[var(--border)] last:border-0">
              <td className="px-3 py-2 font-medium text-[var(--text-primary)]">{col.name}</td>
              <td className={`px-3 py-2 font-medium ${TYPE_STYLES[col.inferred_type]}`}>
                {col.inferred_type}
              </td>
              <td className="px-3 py-2 tabular-nums text-[var(--text-secondary)]">
                {col.missing_percentage}%
              </td>
              <td className="px-3 py-2 tabular-nums text-[var(--text-secondary)]">{col.unique_count}</td>
              <td className="px-3 py-2 text-[var(--text-secondary)]">
                <ColumnSummary col={col} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ColumnSummary({ col }: { col: ColumnProfile }) {
  if (col.inferred_type === "numeric" && col.mean !== null) {
    return (
      <span>
        min {formatNumber(col.min ?? 0)} · mean {formatNumber(col.mean)} · max {formatNumber(col.max ?? 0)}
      </span>
    );
  }
  if (col.inferred_type === "date" && col.min_date) {
    return (
      <span>
        {col.min_date.slice(0, 10)} → {col.max_date?.slice(0, 10)} ({col.date_coverage_days} days)
      </span>
    );
  }
  if (col.inferred_type === "categorical" && col.top_values?.length) {
    const top = col.top_values[0];
    return (
      <span>
        top: &ldquo;{top.value}&rdquo; ({top.percentage}%)
      </span>
    );
  }
  return <span className="text-[var(--text-muted)]">—</span>;
}
