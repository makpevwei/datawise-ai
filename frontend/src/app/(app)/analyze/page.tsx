"use client";

import { useEffect, useState } from "react";
import { listDatasets } from "@/lib/api";
import type { DatasetSummary } from "@/lib/types";
import { AnalysisWorkspace } from "@/components/AnalysisWorkspace";
import { EmptyState } from "@/components/ui";

export default function AnalyzePage() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listDatasets()
      .then((d) => !cancelled && setDatasets(d))
      .catch(() => !cancelled && setDatasets([]))
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (loaded && datasets.length === 0) {
    return (
      <EmptyState
        title="No datasets available yet."
        description="Upload a dataset from My Data before building an analysis."
      />
    );
  }

  return <AnalysisWorkspace datasets={datasets} />;
}
