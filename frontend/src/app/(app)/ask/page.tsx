"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { listDatasets } from "@/lib/api";
import type { DatasetSummary } from "@/lib/types";
import { AskDataWise } from "@/components/AskDataWise";

function AskPageInner() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session") ?? undefined;

  useEffect(() => {
    let cancelled = false;
    listDatasets()
      .then((d) => !cancelled && setDatasets(d))
      .catch(() => !cancelled && setDatasets([]));
    return () => {
      cancelled = true;
    };
  }, []);

  // No forced-remount key here: AskDataWise tracks its own session sync
  // (see its syncedSessionRef) so it can tell "the URL changed because I
  // just answered a question" apart from "the URL changed because the
  // user opened a different session" without losing in-memory state.
  return <AskDataWise datasets={datasets} initialSessionId={sessionId} />;
}

export default function AskPage() {
  return (
    <Suspense fallback={null}>
      <AskPageInner />
    </Suspense>
  );
}
