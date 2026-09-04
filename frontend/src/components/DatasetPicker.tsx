"use client";

import { useMemo, useState } from "react";
import type { DatasetSummary } from "@/lib/types";

/** Compact multi-select dataset picker. `selectedIds === null` means "all
 * datasets" (the default, unscoped state -- matches the backend's own
 * AskRequest.dataset_ids semantics where omitting it means "everything the
 * user owns"), so nothing changes for existing behavior until the user
 * actually narrows the selection. */
export function DatasetPicker({
  datasets,
  selectedIds,
  onChange,
}: {
  datasets: DatasetSummary[];
  selectedIds: string[] | null;
  onChange: (ids: string[] | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const effectiveSelected = selectedIds ?? datasets.map((d) => d.id);
  const allSelected = effectiveSelected.length === datasets.length;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return datasets;
    return datasets.filter((d) => d.name.toLowerCase().includes(q));
  }, [datasets, search]);

  // Multi-sheet workbooks (same source_file, each sheet its own dataset)
  // group under the workbook name rather than listing as unrelated rows.
  const groups = useMemo(() => {
    const map = new Map<string, DatasetSummary[]>();
    for (const d of filtered) {
      const key = d.sheet_name ? d.source_file : d.name;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(d);
    }
    return map;
  }, [filtered]);

  function toggle(id: string) {
    const next = effectiveSelected.includes(id)
      ? effectiveSelected.filter((x) => x !== id)
      : [...effectiveSelected, id];
    onChange(next.length === datasets.length ? null : next);
  }

  if (datasets.length === 0) return null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-1.5 text-sm text-[var(--text-primary)] hover:border-[var(--brand)]"
      >
        <span>
          {allSelected
            ? `All datasets (${datasets.length})`
            : effectiveSelected.length === 0
              ? "No datasets selected"
              : `${effectiveSelected.length} dataset${effectiveSelected.length === 1 ? "" : "s"} selected`}
        </span>
        <span className="text-[var(--text-muted)]">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="absolute z-10 mt-1 w-80 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-3 shadow-lg">
          {datasets.length > 6 && (
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search datasets..."
              className="mb-2 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-xs text-[var(--text-primary)]"
            />
          )}
          <div className="mb-2 flex items-center gap-3 text-xs">
            <button type="button" onClick={() => onChange(null)} className="text-[var(--brand)] hover:underline">
              Select All
            </button>
            <button type="button" onClick={() => onChange([])} className="text-[var(--brand)] hover:underline">
              Clear All
            </button>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {Array.from(groups.entries()).map(([groupKey, items]) => (
              <div key={groupKey} className="mb-2">
                {items[0].sheet_name && (
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    {groupKey}
                  </p>
                )}
                {items.map((d) => (
                  <label
                    key={d.id}
                    className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-[var(--background)]"
                  >
                    <input
                      type="checkbox"
                      checked={effectiveSelected.includes(d.id)}
                      onChange={() => toggle(d.id)}
                      className="h-3.5 w-3.5"
                    />
                    <span className="flex-1 truncate text-[var(--text-primary)]">{d.sheet_name ?? d.name}</span>
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {d.row_count.toLocaleString()}×{d.column_count}
                    </span>
                  </label>
                ))}
              </div>
            ))}
            {filtered.length === 0 && (
              <p className="px-1.5 py-2 text-xs text-[var(--text-muted)]">No datasets match your search.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
