"use client";

import { useEffect, useState } from "react";
import { listDatasets } from "@/lib/api";
import type { DatasetSummary } from "@/lib/types";
import { InsightsPanel } from "@/components/InsightsPanel";

export default function InsightsPage() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    listDatasets()
      .then((d) => !cancelled && setDatasets(d))
      .catch(() => !cancelled && setDatasets([]));
    return () => {
      cancelled = true;
    };
  }, []);

  return <InsightsPanel datasets={datasets} />;
}
