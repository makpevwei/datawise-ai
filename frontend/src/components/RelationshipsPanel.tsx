"use client";

import { useEffect, useState } from "react";
import { ApiError, joinDatasets, listRelationships, previewJoin } from "@/lib/api";
import type {
  DatasetSummary,
  JoinPreviewResult,
  JoinResult,
  JoinType,
  RelationshipSuggestion,
} from "@/lib/types";
import { Button, Card, ConfidenceBadge, EmptyState, ErrorBanner, SectionHeading, Spinner } from "./ui";

const JOIN_TYPES: { value: JoinType; label: string; description: string }[] = [
  { value: "inner", label: "Inner Join", description: "Keep only rows with matching keys in both tables." },
  { value: "left", label: "Left Join", description: "Keep every row from the left table and matching rows from the right." },
  { value: "right", label: "Right Join", description: "Keep every row from the right table and matching rows from the left." },
  { value: "full", label: "Full Outer Join", description: "Keep all rows from both tables, including unmatched rows." },
];

const CARDINALITY_LABELS: Record<string, string> = {
  one_to_one: "One-to-One",
  one_to_many: "One-to-Many",
  many_to_one: "Many-to-One",
  many_to_many: "Many-to-Many",
};

export function RelationshipsPanel({
  datasets,
  onJoined,
}: {
  datasets: DatasetSummary[];
  onJoined: () => void;
}) {
  const [filter, setFilter] = useState<"high" | "all">("high");

  if (datasets.length < 2) {
    return (
      <EmptyState
        title="Upload at least two datasets"
        description="Relationship detection compares columns across datasets to suggest possible joins. Upload a second file to get started."
      />
    );
  }

  const datasetSetKey = datasets
    .map((d) => d.id)
    .sort()
    .join(",");

  return (
    <div className="flex flex-col gap-6">
      <SectionHeading
        title="Relationships"
        subtitle="Likely primary-key / foreign-key relationships between your datasets, backed by actual data evidence. Nothing is joined automatically."
      />

      <div className="flex items-center gap-2 text-xs">
        <button
          onClick={() => setFilter("high")}
          className={`rounded-full px-3 py-1 font-medium ${filter === "high" ? "bg-[var(--series-1)]/10 text-[var(--series-1)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
        >
          High Confidence
        </button>
        <button
          onClick={() => setFilter("all")}
          className={`rounded-full px-3 py-1 font-medium ${filter === "all" ? "bg-[var(--series-1)]/10 text-[var(--series-1)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
        >
          All
        </button>
      </div>

      <RelationshipsList key={datasetSetKey} filter={filter} onJoined={onJoined} />
    </div>
  );
}

function RelationshipsList({
  filter,
  onJoined,
}: {
  filter: "high" | "all";
  onJoined: () => void;
}) {
  // Keyed by the dataset-id set in the parent, so a change in which
  // datasets exist (upload, join) remounts this list and refetches --
  // no reset-then-fetch effect needed.
  const [relationships, setRelationships] = useState<RelationshipSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listRelationships()
      .then((data) => !cancelled && setRelationships(data))
      .catch(
        (e) => !cancelled && setError(e instanceof Error ? e.message : "Failed to detect relationships."),
      );
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <ErrorBanner message={error} />;

  if (relationships === null) {
    return (
      <div className="flex items-center gap-2 py-8 text-sm text-[var(--text-secondary)]">
        <Spinner /> Scanning columns for relationships…
      </div>
    );
  }

  const visible = filter === "high" ? relationships.filter((r) => r.confidence === "HIGH") : relationships;

  if (visible.length === 0) {
    return (
      <EmptyState
        title="No strong table relationships detected."
        description="DataWise looks for primary-key / foreign-key-like relationships supported by actual data evidence -- not just columns with similar values. This is normal for unrelated datasets."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {visible.map((rel) => (
        <RelationshipCard key={relKey(rel)} rel={rel} onJoined={onJoined} />
      ))}
    </div>
  );
}

type Stage = "suggested" | "reviewing" | "configuring" | "previewing" | "created";

function RelationshipCard({ rel, onJoined }: { rel: RelationshipSuggestion; onJoined: () => void }) {
  const [stage, setStage] = useState<Stage>("suggested");
  const [joinType, setJoinType] = useState<JoinType>(
    (JOIN_TYPES.find((j) => j.value === rel.suggested_join_type)?.value as JoinType) ?? "inner",
  );
  const [preview, setPreview] = useState<JoinPreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joined, setJoined] = useState<JoinResult | null>(null);
  const [confirmingFanOut, setConfirmingFanOut] = useState(false);

  async function handlePreview(type: JoinType) {
    setLoading(true);
    setError(null);
    try {
      const result = await previewJoin({
        left_dataset_id: rel.left_dataset_id,
        left_column: rel.left_column,
        right_dataset_id: rel.right_dataset_id,
        right_column: rel.right_column,
        join_type: type,
      });
      setPreview(result);
      setStage("previewing");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(allowFanOut = false) {
    setLoading(true);
    setError(null);
    try {
      const result = await joinDatasets({
        left_dataset_id: rel.left_dataset_id,
        left_column: rel.left_column,
        right_dataset_id: rel.right_dataset_id,
        right_column: rel.right_column,
        join_type: joinType,
        allow_fan_out: allowFanOut,
      });
      setJoined(result);
      setStage("created");
      setConfirmingFanOut(false);
      onJoined();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setConfirmingFanOut(true);
      } else {
        setError(e instanceof Error ? e.message : "Join failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="font-mono text-sm">
            <span className="font-semibold text-[var(--text-primary)]">{rel.left_dataset_name}</span>
            <span className="text-[var(--text-muted)]">.{rel.left_column}</span>
            <span className="mx-2 text-[var(--text-muted)]">→</span>
            <span className="font-semibold text-[var(--text-primary)]">{rel.right_dataset_name}</span>
            <span className="text-[var(--text-muted)]">.{rel.right_column}</span>
          </div>
          <div className="flex items-center gap-2">
            <ConfidenceBadge level={rel.confidence} />
            <span className="rounded-full bg-[var(--background)] px-2.5 py-0.5 text-xs font-medium text-[var(--text-secondary)]">
              {CARDINALITY_LABELS[rel.cardinality] ?? rel.cardinality}
            </span>
          </div>
        </div>

        <ul className="flex flex-col gap-1 text-sm text-[var(--text-secondary)]">
          {rel.reasons.map((reason, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-[var(--series-1)]">✓</span>
              {reason}
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
          <span>{rel.left_cardinality.toLocaleString()} distinct on the left</span>
          <span>{rel.right_cardinality.toLocaleString()} distinct on the right</span>
          {rel.value_overlap_percentage !== null && <span>{rel.value_overlap_percentage}% value overlap</span>}
        </div>

        {error && <ErrorBanner message={error} />}

        {stage === "suggested" && (
          <Button variant="secondary" onClick={() => setStage("reviewing")}>
            Review Relationship
          </Button>
        )}

        {stage === "reviewing" && (
          <div className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
            <p className="text-sm text-[var(--text-primary)]">
              DataWise found a likely relationship between {rel.left_dataset_name}.{rel.left_column} and{" "}
              {rel.right_dataset_name}.{rel.right_column}.
            </p>
            <div>
              <Button onClick={() => setStage("configuring")}>Use Relationship</Button>
            </div>
          </div>
        )}

        {(stage === "configuring" || stage === "previewing") && (
          <div className="flex flex-col gap-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
            <p className="text-sm font-medium text-[var(--text-primary)]">How would you like to join these tables?</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {JOIN_TYPES.map((jt) => (
                <label
                  key={jt.value}
                  className={`flex cursor-pointer flex-col gap-0.5 rounded-lg border p-2.5 text-xs ${
                    joinType === jt.value
                      ? "border-[var(--series-1)] bg-[var(--series-1)]/5"
                      : "border-[var(--border)]"
                  }`}
                >
                  <span className="flex items-center gap-2 font-medium text-[var(--text-primary)]">
                    <input
                      type="radio"
                      name={`join-type-${relKey(rel)}`}
                      checked={joinType === jt.value}
                      onChange={() => {
                        setJoinType(jt.value);
                        setPreview(null);
                        setStage("configuring");
                      }}
                    />
                    {jt.label}
                  </span>
                  <span className="text-[var(--text-muted)]">{jt.description}</span>
                </label>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
              <div>
                <p className="text-[var(--text-muted)]">Left table</p>
                <p className="font-mono text-[var(--text-primary)]">{rel.left_dataset_name}.{rel.left_column}</p>
              </div>
              <div>
                <p className="text-[var(--text-muted)]">Join type</p>
                <p className="font-medium uppercase text-[var(--text-primary)]">{joinType} join</p>
              </div>
              <div>
                <p className="text-[var(--text-muted)]">Right table</p>
                <p className="font-mono text-[var(--text-primary)]">{rel.right_dataset_name}.{rel.right_column}</p>
              </div>
            </div>

            <div>
              <Button variant="secondary" onClick={() => handlePreview(joinType)} disabled={loading}>
                {loading ? <Spinner /> : null} Preview Join
              </Button>
            </div>

            {stage === "previewing" && preview && (
              <div className="flex flex-col gap-2 rounded-lg border border-[var(--border)] p-3">
                <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
                  <Stat label="Left rows" value={preview.rows_before_left} />
                  <Stat label="Right rows" value={preview.rows_before_right} />
                  <Stat label="Expected result rows" value={preview.rows_after} />
                  <Stat label="Matched" value={preview.matched_both} />
                  <Stat label="Unmatched left" value={preview.unmatched_left} />
                  <Stat label="Unmatched right" value={preview.unmatched_right} />
                </div>
                {preview.duplicate_key_warning && (
                  <div className="rounded-lg bg-[var(--status-warning)]/15 px-3 py-2 text-xs text-[var(--status-warning)]">
                    <strong>Many-to-many join.</strong> This relationship may multiply rows and significantly
                    increase the result size
                    {preview.estimated_fan_out_rows !== null && ` (estimated ~${preview.estimated_fan_out_rows.toLocaleString()} rows)`}.
                  </div>
                )}
                {preview.notes.map((note, i) => (
                  <p key={i} className="text-xs text-[var(--text-muted)]">{note}</p>
                ))}

                {confirmingFanOut ? (
                  <div className="flex flex-col gap-2 rounded-lg bg-[var(--status-warning)]/10 p-2.5">
                    <p className="text-xs text-[var(--text-primary)]">
                      This join may multiply rows because both tables contain repeated values for the selected key.
                    </p>
                    <div className="flex gap-2">
                      <Button onClick={() => handleCreate(true)} disabled={loading}>
                        {loading ? <Spinner /> : null} Continue
                      </Button>
                      <Button variant="secondary" onClick={() => setConfirmingFanOut(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <Button onClick={() => handleCreate(false)} disabled={loading}>
                      {loading ? <Spinner /> : null} Create Joined Dataset
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {stage === "created" && joined && (
          <div className="rounded-lg bg-[var(--status-good)]/10 px-3 py-2 text-sm text-[var(--status-good)]">
            {joined.reused_existing
              ? "An identical joined dataset already existed and was reused: "
              : "Joined as "}
            &ldquo;{joined.new_dataset.name}&rdquo; — {joined.rows_after.toLocaleString()} rows
            ({joined.unmatched_left} unmatched left, {joined.unmatched_right} unmatched right)
          </div>
        )}
      </div>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-[var(--text-muted)]">{label}</p>
      <p className="font-semibold tabular-nums text-[var(--text-primary)]">{value.toLocaleString()}</p>
    </div>
  );
}

function relKey(rel: RelationshipSuggestion): string {
  return `${rel.left_dataset_id}.${rel.left_column}__${rel.right_dataset_id}.${rel.right_column}`;
}
