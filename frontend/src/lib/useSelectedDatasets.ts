"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "datawise:selected-dataset-ids";

/** Persists a dataset selection across navigation -- found live: deselecting
 * some datasets on one page (Dashboard, Insights, Ask DataWise all show a
 * DatasetPicker) then navigating to another reset back to "all selected",
 * because each page owned its own local useState that naturally resets on
 * remount. This is the ONE shared source of truth every page with a
 * DatasetPicker should use instead, backed by localStorage so it survives
 * both a client-side route change and a full page reload.
 *
 * null means "all datasets" (unscoped), matching AskRequest.dataset_ids'
 * own "omit it for everything" semantics -- nothing changes for a user who
 * never narrows their selection.
 *
 * A stored id referring to a since-deleted dataset is left as-is rather
 * than actively pruned: DatasetPicker's own effectiveSelected/allSelected
 * math already only counts ids that still exist in its `datasets` prop, so
 * a stale id just quietly does nothing until the user next changes their
 * selection -- not worth the extra complexity of reconciling against a
 * live dataset list from a hook that doesn't otherwise need one. */
export function useSelectedDatasets(): [string[] | null, (ids: string[] | null) => void] {
  const [selected, setSelected] = useState<string[] | null>(null);
  const [hydrated, setHydrated] = useState(false);

  // Read the persisted selection once on mount. Deferred to an effect (not
  // read synchronously during render) both because localStorage isn't
  // available during SSR and to avoid a synchronous setState inside an
  // effect body (react-hooks/set-state-in-effect, the same pattern used
  // throughout this codebase).
  useEffect(() => {
    Promise.resolve().then(() => {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) setSelected(JSON.parse(raw));
      } catch {
        // Private browsing, disabled storage, corrupted JSON, ... -- falls
        // back to "all datasets" rather than breaking the page.
      } finally {
        setHydrated(true);
      }
    });
  }, []);

  // Persist on every change, but only once hydration has actually run --
  // otherwise the very first render's default (null) would overwrite
  // whatever was already stored before the read above gets a chance to
  // run.
  useEffect(() => {
    if (!hydrated) return;
    try {
      if (selected === null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
    } catch {
      // Same tolerance as the read above -- a failed write just means the
      // selection won't survive this reload, not a broken page.
    }
  }, [selected, hydrated]);

  return [selected, setSelected];
}
