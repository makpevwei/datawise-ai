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

/** Plain-language explanation of what a relationship is and how DataWise detects it. */
function RelationshipExplainer() {
  const [showJoins, setShowJoins] = useState(false);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-1)] p-4 text-sm text-[var(--text-secondary)]">
      <p className="mb-3 font-semibold text-[var(--text-primary)]">What are relationships?</p>
      <p className="mb-3">
        Relationships show how two datasets can be connected using a shared column. DataWise checks
        the actual data before suggesting a relationship — it does <strong>not</strong> guess based
        on column names alone.
      </p>

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <p className="mb-1 font-medium text-[var(--text-primary)]">🔑 Primary key</p>
          <p>A unique ID that identifies one record. For example, if <code className="rounded bg-[var(--border)] px-1 py-0.5 text-xs">Customer_ID</code> appears only once in a Customers table, it is the primary key — it uniquely identifies each customer.</p>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <p className="mb-1 font-medium text-[var(--text-primary)]">🔗 Foreign key</p>
          <p>A column in another table that refers back to the primary key. For example, <code className="rounded bg-[var(--border)] px-1 py-0.5 text-xs">Orders.Customer_ID</code> can contain the same customer many times because one customer can place many orders.</p>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <p className="mb-1 font-medium text-[var(--text-primary)]">📋 Dimension table</p>
          <p>Usually describes <em>who, what, where</em> or <em>when</em> — such as customers, products, stores or dates. Each row represents one distinct entity.</p>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <p className="mb-1 font-medium text-[var(--text-primary)]">📊 Fact table</p>
          <p>Usually records business events or measurements — such as orders, transactions, sales or quantities. Rows repeat for the same entity over time.</p>
        </div>
      </div>

      <div className="mb-3">
        <p className="mb-2 font-medium text-[var(--text-primary)]">Relationship types</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {[
            { label: "One-to-Many", desc: "One record on one side relates to many records on the other. Example: 1 customer → many orders. The most common pattern." },
            { label: "Many-to-One", desc: "Many records point back to one record. Example: many orders → 1 customer. This is the same link viewed from the orders side." },
            { label: "One-to-One", desc: "One record corresponds to exactly one record on the other side." },
            { label: "Many-to-Many", desc: "Many records on both sides can relate to many records on the other. Usually needs an intermediate (bridge) table to work correctly." },
          ].map((t) => (
            <div key={t.label} className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-2.5 text-xs">
              <span className="font-medium text-[var(--text-primary)]">{t.label}: </span>
              {t.desc}
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={() => setShowJoins((v) => !v)}
        className="text-xs font-medium text-[var(--brand)] hover:underline"
      >
        {showJoins ? "Hide" : "Learn about"} join types
      </button>

      {showJoins && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {[
            { label: "Inner Join", desc: "Only records with a match in both datasets. Unmatched rows are excluded." },
            { label: "Left Join", desc: "Keep every record from the left dataset and add matching information from the right. Left-only rows keep empty right columns." },
            { label: "Right Join", desc: "Keep every record from the right dataset and add matching information from the left." },
            { label: "Full Outer Join", desc: "Keep records from both datasets whether or not they have a match. Unmatched rows appear with empty columns on the missing side." },
          ].map((j) => (
            <div key={j.label} className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-2.5 text-xs">
              <span className="font-medium text-[var(--text-primary)]">{j.label}: </span>
              {j.desc}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const CARDINALITY_LABELS: Record<string, string> = {
  one_to_one: "One-to-One",
  one_to_many: "One-to-Many",
  many_to_one: "Many-to-One",
  many_to_many: "Many-to-Many",
};

/** Plain-language sentence describing the relationship cardinality. */
function cardinalityDescription(rel: RelationshipSuggestion): string {
  const L = rel.left_dataset_name;
  const LC = rel.left_column;
  const R = rel.right_dataset_name;
  const RC = rel.right_column;
  switch (rel.cardinality) {
    case "one_to_many":
      return `One record in ${L} (identified by ${LC}) can relate to many records in ${R} (via ${RC}).`;
    case "many_to_one":
      return `Many records in ${L} (via ${LC}) point back to one record in ${R} (identified by ${RC}).`;
    case "one_to_one":
      return `Each record in ${L} (${LC}) corresponds to exactly one record in ${R} (${RC}).`;
    case "many_to_many":
      return `Many records in ${L} (${LC}) relate to many records in ${R} (${RC}). Consider using a bridge table.`;
    default:
      return `${L}.${LC} is linked to ${R}.${RC}.`;
  }
}

/** Simple ASCII diagram for a relationship. */
function RelationshipDiagram({ rel }: { rel: RelationshipSuggestion }) {
  const leftSymbol = rel.cardinality === "one_to_many" || rel.cardinality === "one_to_one" ? "🔑" : "🔗";
  const rightSymbol = rel.cardinality === "one_to_many" || rel.cardinality === "many_to_many" ? "🔗" : "🔑";
  const arrow = rel.cardinality === "one_to_many" ? "1 ──────── ∞" :
    rel.cardinality === "many_to_one" ? "∞ ──────── 1" :
      rel.cardinality === "one_to_one" ? "1 ──────── 1" : "∞ ──────── ∞";

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 font-mono text-xs">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold text-[var(--text-primary)]">{rel.left_dataset_name}</span>
          <span className="text-[var(--text-muted)]">{leftSymbol} {rel.left_column}</span>
        </div>
        <div className="flex-1 text-center text-[var(--text-muted)] pt-3">{arrow}</div>
        <div className="flex flex-col gap-0.5 text-right">
          <span className="font-semibold text-[var(--text-primary)]">{rel.right_dataset_name}</span>
          <span className="text-[var(--text-muted)]">{rel.right_column} {rightSymbol}</span>
        </div>
      </div>
      <p className="mt-2 text-center text-[var(--text-secondary)] font-sans not-italic">
        {cardinalityDescription(rel)}
      </p>
    </div>
  );
}

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
      <div className="flex flex-col gap-6">
        <RelationshipExplainer />
        <EmptyState
          title="Upload at least two datasets"
          description="Relationship detection compares columns across datasets to suggest possible joins. Upload a second file to get started."
        />
      </div>
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

      <RelationshipExplainer />

      <div className="flex items-center gap-2 text-xs">
        <button
          onClick={() => setFilter("high")}
          className={`rounded-full px-3 py-1 font-medium ${filter === "high" ? "bg-[var(--brand)]/10 text-[var(--brand)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
        >
          High Confidence
        </button>
        <button
          onClick={() => setFilter("all")}
          className={`rounded-full px-3 py-1 font-medium ${filter === "all" ? "bg-[var(--brand)]/10 text-[var(--brand)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
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
              <span className="text-[var(--brand)]">✓</span>
              {reason}
            </li>
          ))}
        </ul>

        <RelationshipDiagram rel={rel} />

        <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
          <span>{rel.left_cardinality.toLocaleString()} distinct on the left</span>
          <span>{rel.right_cardinality.toLocaleString()} distinct on the right</span>
          {rel.value_overlap_percentage !== null && <span>{rel.value_overlap_percentage}% value overlap</span>}
        </div>

        <details className="text-xs text-[var(--text-muted)]">
          <summary className="cursor-pointer select-none font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            Technical details
          </summary>
          <div className="mt-2 flex flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2.5">
            <p><span className="font-medium">Left distinct values:</span> {rel.left_cardinality.toLocaleString()}</p>
            <p><span className="font-medium">Right distinct values:</span> {rel.right_cardinality.toLocaleString()}</p>
            {rel.value_overlap_percentage !== null && (
              <p><span className="font-medium">Value overlap:</span> {rel.value_overlap_percentage}%</p>
            )}
            <p><span className="font-medium">Confidence:</span> {rel.confidence} — {rel.confidence === "HIGH"
              ? `${rel.left_column} is unique (or near-unique) in ${rel.left_dataset_name}, appears repeatedly in ${rel.right_dataset_name}, and values overlap strongly. DataWise considers this a strong candidate relationship.`
              : `Some evidence of a relationship, but uniqueness, overlap, or cardinality is weaker than a high-confidence match. Review before joining.`
            }</p>
          </div>
        </details>

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
                  className={`flex cursor-pointer flex-col gap-0.5 rounded-lg border p-2.5 text-xs ${joinType === jt.value
                    ? "border-[var(--brand)] bg-[var(--brand)]/5"
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
