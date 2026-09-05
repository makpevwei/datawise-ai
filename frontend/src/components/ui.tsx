import { IconAlertTriangle, IconCheckCircle, IconDatabase, IconFileText } from "@/components/icons";
import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-[var(--border)] bg-[var(--surface-1)] p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionHeading({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-4">
      <h2 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
      {subtitle && (
        <p className="mt-1 text-sm text-[var(--text-secondary)]">{subtitle}</p>
      )}
    </div>
  );
}

const QUALITY_STYLES: Record<string, string> = {
  good: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  fair: "bg-[var(--status-warning)]/20 text-[var(--status-warning)]",
  poor: "bg-[var(--status-critical)]/15 text-[var(--status-critical)]",
};

export function QualityBadge({ rating }: { rating: "good" | "fair" | "poor" }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${QUALITY_STYLES[rating]}`}
    >
      {rating}
    </span>
  );
}

const CONFIDENCE_STYLES: Record<string, string> = {
  HIGH: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  MEDIUM: "bg-[var(--status-warning)]/20 text-[color:#8a5a00] dark:text-[var(--status-warning)]",
  LOW: "bg-[var(--text-muted)]/15 text-[var(--text-secondary)]",
};

export function ConfidenceBadge({ level }: { level: "HIGH" | "MEDIUM" | "LOW" }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold tracking-wide ${CONFIDENCE_STYLES[level]}`}
    >
      {level} CONFIDENCE
    </span>
  );
}

const LABEL_STYLES: Record<string, string> = {
  VERIFIED_FROM_DATA: "bg-[var(--series-3)]/15 text-[var(--series-3)]",
  CALCULATED: "bg-[var(--series-1)]/15 text-[var(--series-1)]",
  DERIVED: "bg-[var(--series-7)]/15 text-[var(--series-7)]",
  DOCUMENT_EVIDENCE: "bg-[var(--series-2)]/15 text-[var(--series-2)]",
  VERIFIED_FROM_WEB: "bg-[var(--series-4)]/15 text-[var(--series-4)]",
  AI_INTERPRETATION: "bg-[var(--series-5)]/15 text-[var(--series-5)]",
  INSUFFICIENT_DATA: "bg-[var(--text-muted)]/20 text-[var(--text-secondary)]",
  GENERAL_ANSWER: "bg-[var(--series-6)]/15 text-[var(--series-6)]",
};

const CROSS_CHECK_STYLES: Record<string, string> = {
  SUPPORTED_BY_DATA: "bg-[var(--status-good)]/15 text-[var(--status-good)]",
  DOCUMENT_CLAIM: "bg-[var(--series-2)]/15 text-[var(--series-2)]",
  NOT_VERIFIED_BY_DATA: "bg-[var(--status-warning)]/20 text-[color:#8a5a00] dark:text-[var(--status-warning)]",
  CONTRADICTED_BY_DATA: "bg-[var(--status-critical)]/15 text-[var(--status-critical)]",
  INSUFFICIENT_EVIDENCE: "bg-[var(--text-muted)]/20 text-[var(--text-secondary)]",
};

export function CrossCheckBadge({ label }: { label: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${CROSS_CHECK_STYLES[label] ?? CROSS_CHECK_STYLES.INSUFFICIENT_EVIDENCE}`}
    >
      {label.replace(/_/g, " ")}
    </span>
  );
}

export function SourceLabelBadge({ label }: { label: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${LABEL_STYLES[label] ?? LABEL_STYLES.CALCULATED}`}
    >
      {label.replace(/_/g, " ")}
    </span>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  /** A context icon from @/components/icons -- e.g. IconUploadCloud for
   * "no datasets", IconDatabase for "no connected sources". Optional so
   * ad hoc callers keep working; every first-class empty state should
   * pass one so the screen reads as purposeful, not a bare text block. */
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border)] px-6 py-16 text-center">
      {icon && (
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--brand-subtle)] text-[var(--brand)]">
          {icon}
        </span>
      )}
      <p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>
      <p className="max-w-sm text-sm text-[var(--text-secondary)]">{description}</p>
      {action}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-[var(--status-critical)]/30 bg-[var(--status-critical)]/10 px-4 py-3 text-sm text-[var(--status-critical)]">
      <IconAlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function Spinner() {
  return (
    <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--text-muted)] border-t-transparent" />
  );
}

/** Column-name hint used to decide whether a numeric column represents money
 * (price/cost/revenue/...) and should render with the user's currency symbol
 * rather than a bare number -- presentation only. */
// Deliberately excludes a bare "total" -- "Total Orders"/"Total Customers"/
// "Total Records" are common non-monetary KPI labels, and every genuinely
// monetary "Total ..." label (Total Revenue, Total Sales, Total Cost, ...)
// already matches one of the words below on its own.
// Kept in sync with the backend's own monetary-metric vocabulary
// (app/analysis/kpi_discovery.py's METRIC_NAME_HINTS) -- salary/bonus/
// fare/spend/earning/fee/wage/pay are real money too, just not the
// price/cost/revenue words this list originally covered. Missing one here
// doesn't break the KPI itself (the number is still right), only its
// currency-symbol display -- but that's still a real, user-visible bug.
export const MONETARY_LABEL_HINTS = /price|cost|amount|revenue|sales|budget|income|expense|profit|margin|salary|bonus|fare|spend|earning|fee|wage|\bpay\b/i;

/** A column name ending in Key/Id/UUID/GUID (camelCase or snake_case) is an
 * identifier, never a business measure -- mirrors the backend's own strong
 * identifier-suffix rule (app/profiling/type_inference.py). Without this, a
 * name like "SalesOrderLineKey" trips MONETARY_LABEL_HINTS on the "Sales"
 * substring alone and gets rendered as currency, even though it's a raw key. */
const IDENTIFIER_LABEL_HINTS = /(?:Key|Id|UUID|GUID|Pk|Fk|RowId|RowKey)$|(?:_(?:key|id|uuid|guid|pk|fk|rowid|rowkey))$/i;

export function looksMonetary(column: string): boolean {
  return MONETARY_LABEL_HINTS.test(column) && !IDENTIFIER_LABEL_HINTS.test(column);
}

/** True when the column name itself marks it as a key/id -- these are never
 * business measures, so they should never receive ANY numeric formatting
 * (not currency, and not even a thousands separator): a key is a label, not
 * a quantity, and "43,659,001" reads as if it were counted or measured. */
export function looksLikeIdentifier(column: string): boolean {
  return IDENTIFIER_LABEL_HINTS.test(column);
}

/** A calendar/date-part number (Year, Month_Number, Week_Number, Day) --
 * mirrors the backend's own date-part exclusion
 * (app/analysis/kpi_discovery.py's _DATE_PART_PATTERNS). "2024" read as a
 * quantity is "2,024", which is exactly as wrong as putting a thousands
 * separator in a phone number; these get the same plain, unformatted
 * treatment as an identifier for the same reason -- they're a label for
 * *when*, not a count of *how much*. Whole-word/singular only: a plural
 * ("Delivery_Days") is a real duration measure, not a calendar date-part. */
const DATE_PART_LABEL_HINTS = /(?:^|_)(?:year|quarter|month|week|day)(?:_|$)/i;

export function looksLikeDatePart(column: string): boolean {
  return DATE_PART_LABEL_HINTS.test(column);
}

/** Formats a dataset's own `name` (+ optional `sheet_name`) into a
 * user-facing "where did this come from" label -- e.g.
 * "Workbook.xlsx — Fact_Sales". For an auto- or manually-joined dataset
 * (app/relationships/joins.py's perform_join names it
 * "{left.profile.name} ⋈ {right.profile.name}"), renders a clean
 * "Fact_Sales + Dim_Products (joined)" instead of the raw, doubly-
 * prefixed join string (both sides can share the same long workbook
 * filename, which read literally is hard to parse at a glance). Shared
 * by every card/chart/insight that shows source lineage (Dashboard,
 * Insights) so a joined chart's card always names the real tables
 * behind it, not just an opaque derived-dataset id. */
export function formatSourceLabel(name: string | null | undefined, sheet?: string | null): string {
  if (!name) return "";
  if (name.includes(" ⋈ ")) {
    const parts = name.split(" ⋈ ").map((part) => {
      const idx = part.lastIndexOf(" — ");
      return idx === -1 ? part : part.slice(idx + 3);
    });
    return `${parts.join(" + ")} (joined)`;
  }
  if (sheet && name.includes(sheet)) return name;
  if (sheet) return `${name} — ${sheet}`;
  return name;
}

/** Small "where this came from" pill -- a consistent, iconified replacement
 * for the plain "Source: X" text line previously repeated ad hoc across
 * Dashboard chart cards and Insights' KPI/insight cards. */
export function SourceChip({ label }: { label: string }) {
  if (!label) return null;
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-full bg-[var(--background)] px-2 py-0.5 text-[10px] text-[var(--text-muted)]">
      <IconDatabase size={11} className="shrink-0" />
      <span className="truncate">{label}</span>
    </span>
  );
}

/** Evidence labels that count as "grounded in your data" for the purposes
 * of the always-visible provenance badge below: the user's own uploaded
 * datasets and documents, mechanically verified (backend
 * app/agent/verification.py) against a real tool result or cited excerpt.
 * Deliberately excludes VERIFIED_FROM_WEB -- that label is mechanically
 * verified too, but against the open web, not the user's data, so it
 * belongs with the "general/outside" bucket for this specific badge. This
 * mirrors AskDataWise.tsx's own GENERAL_KNOWLEDGE_LABELS split (where
 * VERIFIED_FROM_WEB already sits in the general-knowledge section) --
 * keep the two lists' treatment of VERIFIED_FROM_WEB in sync if either
 * changes. */
export const GROUNDED_EVIDENCE_LABELS = [
  "VERIFIED_FROM_DATA",
  "CALCULATED",
  "DERIVED",
  "DOCUMENT_EVIDENCE",
];

/** Always-visible "is this answer actually grounded" pill -- the direct
 * response to the comparison-pass finding that DataWise's own (more
 * rigorous, mechanically-verified) evidence system existed in the data
 * but was invisible until a user clicked "Show how DataWise worked."
 * Deliberately three honest states: grounded, mixed, or ungrounded. An
 * ungrounded answer is still shown, just clearly labelled, never hidden
 * or blocked. */
export type ProvenanceState = "grounded" | "mixed" | "ungrounded";

export function GroundedBadge({ provenance }: { provenance: ProvenanceState }) {
  if (provenance === "grounded") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--status-good)]/15 px-2.5 py-1 text-xs font-semibold text-[var(--status-good)]">
        <IconCheckCircle size={13} /> Grounded in your data
      </span>
    );
  }
  if (provenance === "mixed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--status-caution)]/15 px-2.5 py-1 text-xs font-semibold text-[var(--status-caution)]">
        <IconAlertTriangle size={13} /> Mixed: some findings grounded, others from general knowledge
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--status-warning)]/20 px-2.5 py-1 text-xs font-semibold text-[color:#8a5a00] dark:text-[var(--status-warning)]">
      <IconAlertTriangle size={13} /> General knowledge — not verified from your data
    </span>
  );
}

/** Renders a Citation's location map ("page": 3, "line_start": 12, ...) as
 * a short human string -- shared by AskDataWise's citation cards so every
 * caller formats a location the same way. */
export function formatCitationLocation(location: Record<string, unknown>): string {
  return Object.entries(location)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
    .join(" · ");
}

/** A single cited source, in the spirit of a NotebookLM-style source card:
 * which file, which location in it, and the exact excerpt the claim was
 * checked against -- replacing a plain citation text line with something
 * that reads as evidence, not a footnote. */
export function CitationCard({
  documentName,
  location,
  excerpt,
}: {
  documentName: string;
  location: Record<string, unknown>;
  excerpt: string;
}) {
  const locationLabel = formatCitationLocation(location);
  return (
    <div className="flex gap-2.5 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-3">
      <IconFileText size={16} className="mt-0.5 shrink-0 text-[var(--text-muted)]" />
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
          <span className="font-semibold text-[var(--text-primary)]">{documentName}</span>
          {locationLabel && <span className="text-[var(--text-muted)]">{locationLabel}</span>}
        </p>
        <p className="mt-1 text-xs italic text-[var(--text-secondary)]">
          &ldquo;{excerpt.slice(0, 200)}
          {excerpt.length > 200 ? "…" : ""}&rdquo;
        </p>
      </div>
    </div>
  );
}

export function Table({
  columns,
  rows,
  currency,
  decimalPlaces,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  /** When set, numeric columns whose name looks monetary render with this
   * currency's symbol -- per the user's Settings preference. */
  currency?: string;
  decimalPlaces?: number;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="w-full min-w-max text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] bg-[var(--background)]">
            {columns.map((col) => (
              <th
                key={col}
                className="whitespace-nowrap px-3 py-2 font-medium text-[var(--text-secondary)]"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-[var(--border)] last:border-0">
              {columns.map((col) => (
                <td key={col} className="whitespace-nowrap px-3 py-2 text-[var(--text-primary)]">
                  {formatCell(row[col], col, currency, decimalPlaces)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: unknown, column: string, currency?: string, decimalPlaces?: number): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    // A key/id (or a calendar date-part like Year/Month_Number) is a
    // label, not a quantity -- show the raw source value exactly as
    // uploaded, with no formatting of any kind applied to it.
    if (looksLikeIdentifier(column) || looksLikeDatePart(column)) return String(value);
    if (currency && looksMonetary(column)) {
      return formatCurrency(value, currency, decimalPlaces ?? 2);
    }
    return decimalPlaces !== undefined
      ? value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: decimalPlaces })
      : formatNumber(value);
  }
  return String(value);
}

export function formatNumber(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Presentation-only currency formatting -- never rounds or otherwise
 * changes the underlying analytical value, only how it's displayed
 * (Phase 4 continuation section 6-7: currency/decimal-place settings). */
export function formatCurrency(value: number, currency: string, decimalPlaces: number): string {
  try {
    return value.toLocaleString(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: decimalPlaces,
      maximumFractionDigits: decimalPlaces,
    });
  } catch {
    return `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: decimalPlaces, maximumFractionDigits: decimalPlaces })}`;
  }
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string; disabled?: boolean }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-[var(--border)]">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          disabled={tab.disabled}
          onClick={() => onChange(tab.id)}
          className={`whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${active === tab.id
              ? "border-[var(--brand)] text-[var(--text-primary)]"
              : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            } ${tab.disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const styles = {
    primary:
      "bg-[var(--brand)] text-[var(--brand-foreground)] hover:bg-[var(--brand-hover)] disabled:opacity-40",
    secondary:
      "border border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--background)] disabled:opacity-40",
    ghost: "text-[var(--brand)] hover:underline disabled:opacity-40",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  );
}
