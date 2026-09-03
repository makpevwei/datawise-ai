"use client";

import { useState } from "react";
import type { ChartSpec } from "@/lib/types";
import { formatCurrency, formatNumber, looksMonetary } from "./ui";

const SERIES_1 = "var(--series-1)";
const DONUT_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
];

/** Shared value formatter for chart axes/tooltips: currency when the value's
 * own label looks monetary and a currency is set, otherwise a plain number.
 * Presentation only -- never changes the underlying calculated value. */
function formatChartValue(value: number, valueLabel: string | undefined, currency?: string, decimalPlaces?: number): string {
  if (currency && valueLabel && looksMonetary(valueLabel)) {
    return formatCurrency(value, currency, decimalPlaces ?? 2);
  }
  return formatNumber(value);
}

/** Same job as formatChartValue, but abbreviated (via scaleNumber/
 * scaleCurrency below) -- for the tight, fixed-width spaces inside a chart
 * itself: axis labels, hover tooltips, per-bar value labels. A full-
 * precision figure like "NGN 21,450,000.00" doesn't fit those, and inside
 * an SVG with overflow-visible set it doesn't even get clipped -- it
 * visually bleeds outside the chart's own card, found live on mobile.
 * Full precision stays one hover/tap away via each caller's own `title`. */
function formatChartValueShort(value: number, valueLabel: string | undefined, currency?: string, decimalPlaces?: number): string {
  if (currency && valueLabel && looksMonetary(valueLabel)) {
    return scaleCurrency(value, currency, decimalPlaces ?? 2).display;
  }
  return scaleNumber(value).display;
}

/** Scale large numbers to an executive-friendly abbreviated form that always
 *  fits a card, e.g. 109_809_274 -> "109.8M" | 274_776 -> "274.8K" | 905 -> "905".
 *  The full-precision value is always available (hover title + click-to-reveal).
 */
export function scaleNumber(value: number): { display: string; full: string } {
  const full = value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000_000) return { display: `${sign}${(abs / 1_000_000_000).toFixed(1)}B`, full };
  if (abs >= 1_000_000) return { display: `${sign}${(abs / 1_000_000).toFixed(1)}M`, full };
  if (abs >= 10_000) return { display: `${sign}${(abs / 1_000).toFixed(1)}K`, full };
  return { display: full, full };
}

export function scaleCurrency(value: number, currency: string, decimalPlaces: number): { display: string; full: string } {
  const full = formatCurrency(value, currency, decimalPlaces);
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  const sym = full.replace(/[\d,. ]/g, "").trim().slice(0, 3); // extract currency symbol
  if (abs >= 1_000_000_000) return { display: `${sign}${sym}${(abs / 1_000_000_000).toFixed(1)}B`, full };
  if (abs >= 1_000_000) return { display: `${sign}${sym}${(abs / 1_000_000).toFixed(1)}M`, full };
  if (abs >= 10_000) return { display: `${sign}${sym}${(abs / 1_000).toFixed(1)}K`, full };
  return { display: full, full };
}

export function StatCard({
  label,
  value,
  description,
  currency,
  decimalPlaces,
  compact = false,
}: {
  label: string;
  value: number | string;
  description?: string;
  /** When set, a numeric value whose label looks monetary (price/cost/
   * revenue/...) is shown with this currency's symbol instead of a bare
   * number -- presentation only, per the user's Settings preference. */
  currency?: string;
  decimalPlaces?: number;
  /** Smaller type/padding for dense grids (e.g. a 6-up KPI row) where the
   * default size truncates a 3-letter currency code like "NGN" down to
   * unreadable dots. Same tap-to-expand behavior either way. */
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isMonetary = typeof value === "number" && !!currency && looksMonetary(label);

  let display: string;
  let full: string | null = null;
  // Whether there's actually an abbreviation to toggle -- computed from the
  // scaled value itself, never from what's currently on screen (that flips
  // with `expanded`, so comparing against it would make this go false the
  // moment the user expands, leaving no way to click back to collapsed).
  let canExpand = false;
  if (typeof value !== "number") {
    display = value;
  } else {
    const scaled = isMonetary ? scaleCurrency(value, currency!, decimalPlaces ?? 2) : scaleNumber(value);
    canExpand = scaled.display !== scaled.full;
    display = expanded ? scaled.full : scaled.display;
    full = scaled.full;
  }

  return (
    <div className={`rounded-xl border border-[var(--border)] bg-[var(--surface-1)] min-w-0 ${compact ? "p-4" : "p-6"}`}>
      {/* line-clamp-2, not truncate -- a single-line ellipsis was cutting
          "Total Years at Company" down to "TOTAL YEARS AT CO...", hiding
          the metric's real identity. Two lines fits every label seen in
          practice; title=label is still there as a fallback for the rare
          one that doesn't. */}
      <p
        title={label}
        className={`font-medium text-[var(--text-secondary)] line-clamp-2 ${compact ? "min-h-8 text-xs uppercase tracking-wide" : "min-h-10 text-sm"}`}
      >
        {label}
      </p>
      <button
        type="button"
        onClick={canExpand ? () => setExpanded((v) => !v) : undefined}
        title={full ?? undefined}
        className={`mt-2 block w-full truncate text-left font-semibold tabular-nums text-[var(--text-primary)] ${compact ? "text-xl" : "text-4xl"} ${canExpand ? "cursor-pointer hover:text-[var(--series-1)]" : "cursor-default"}`}
      >
        {display}
      </button>
      {canExpand && (
        <p className="mt-1 text-xs text-[var(--text-muted)]">{expanded ? "Tap to collapse" : "Tap for exact value"}</p>
      )}
      {/* line-clamp-2, not truncate, same reasoning as the title above --
          a source label like "NexaSphere_BI_Case_Study_Dataset.xlsx —
          Fact_Sales" was getting cut off illegibly on narrow (mobile)
          cards. title=description stays as a hover fallback on desktop. */}
      {description && (
        <p className="mt-2 line-clamp-2 text-xs text-[var(--text-muted)]" title={description}>{description}</p>
      )}
    </div>
  );
}

interface BarDatum {
  label: string;
  value: number;
}

export function BarChart({
  data,
  height = 28,
  onBarClick,
  valueLabel,
  currency,
  decimalPlaces,
}: {
  data: BarDatum[];
  height?: number;
  onBarClick?: (label: string) => void;
  valueLabel?: string;
  currency?: string;
  decimalPlaces?: number;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => Math.abs(d.value)), 1);

  return (
    <div className="flex flex-col gap-2">
      {data.map((d, i) => (
        <div key={d.label} className="flex items-center gap-3">
          <div className="w-32 shrink-0 truncate text-right text-xs text-[var(--text-secondary)]" title={d.label}>
            {d.label}
          </div>
          <div className="relative flex-1">
            <div
              role={onBarClick ? "button" : undefined}
              tabIndex={onBarClick ? 0 : undefined}
              className={`rounded-full transition-opacity ${onBarClick ? "cursor-pointer" : ""}`}
              style={{
                height,
                width: `${Math.max((Math.abs(d.value) / max) * 100, 2)}%`,
                background: SERIES_1,
                opacity: hovered === null || hovered === i ? 1 : 0.45,
              }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onClick={onBarClick ? () => onBarClick(d.label) : undefined}
              title={onBarClick ? `Drill down into ${d.label}` : undefined}
            />
          </div>
          <div
            className="w-24 shrink-0 truncate text-xs tabular-nums text-[var(--text-primary)]"
            title={formatChartValue(d.value, valueLabel, currency, decimalPlaces)}
          >
            {formatChartValueShort(d.value, valueLabel, currency, decimalPlaces)}
          </div>
        </div>
      ))}
    </div>
  );
}

interface LinePoint {
  label: string;
  value: number;
}

export function LineChart({
  data,
  width = 640,
  height = 220,
  valueLabel,
  currency,
  decimalPlaces,
}: {
  data: LinePoint[];
  width?: number;
  height?: number;
  valueLabel?: string;
  currency?: string;
  decimalPlaces?: number;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  if (data.length < 2) return null;

  const padding = { top: 16, right: 16, bottom: 28, left: 48 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const values = data.map((d) => d.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  const range = max - min || 1;

  const x = (i: number) => padding.left + (i / (data.length - 1)) * innerW;
  const y = (v: number) => padding.top + innerH - ((v - min) / range) * innerH;

  const pathD = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(d.value)}`).join(" ");
  const gridLines = 4;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      {Array.from({ length: gridLines + 1 }).map((_, i) => {
        const gy = padding.top + (innerH / gridLines) * i;
        const value = max - (range / gridLines) * i;
        return (
          <g key={i}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={gy}
              y2={gy}
              stroke="var(--gridline)"
              strokeWidth={1}
            />
            <text x={padding.left - 8} y={gy + 3} textAnchor="end" fontSize={10} fill="var(--text-muted)">
              {formatChartValueShort(Math.round(value), valueLabel, currency, decimalPlaces)}
            </text>
          </g>
        );
      })}

      <path d={pathD} fill="none" stroke={SERIES_1} strokeWidth={2} strokeLinecap="round" />

      {data.map((d, i) => (
        <g key={d.label}>
          <circle
            cx={x(i)}
            cy={y(d.value)}
            r={hoverIndex === i ? 5 : 3}
            fill={SERIES_1}
            stroke="var(--surface-1)"
            strokeWidth={2}
            onMouseEnter={() => setHoverIndex(i)}
            onMouseLeave={() => setHoverIndex(null)}
          />
          {i % Math.ceil(data.length / 6) === 0 && (
            <text x={x(i)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--text-muted)">
              {d.label}
            </text>
          )}
          {hoverIndex === i && (
            <g>
              <rect
                x={x(i) - 34}
                y={y(d.value) - 34}
                width={68}
                height={22}
                rx={4}
                fill="var(--text-primary)"
              />
              <text x={x(i)} y={y(d.value) - 19} textAnchor="middle" fontSize={11} fill="var(--surface-1)">
                {formatChartValueShort(d.value, valueLabel, currency, decimalPlaces)}
              </text>
            </g>
          )}
        </g>
      ))}
    </svg>
  );
}

interface DonutDatum {
  label: string;
  value: number;
}

export function DonutChart({
  data,
  size = 180,
  onSliceClick,
}: {
  data: DonutDatum[];
  size?: number;
  onSliceClick?: (label: string) => void;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const total = data.reduce((sum, d) => sum + d.value, 0);
  if (total === 0) return null;

  const radius = size / 2;
  const inner = radius * 0.62;

  const withOffsets = data.reduce<{ start: number; end: number; label: string; value: number }[]>(
    (acc, d) => {
      const start = acc.length > 0 ? acc[acc.length - 1].end : 0;
      acc.push({ start, end: start + d.value, label: d.label, value: d.value });
      return acc;
    },
    [],
  );

  const arcs = withOffsets.map((d, i) => {
    const startAngle = (d.start / total) * 2 * Math.PI - Math.PI / 2;
    const endAngle = (d.end / total) * 2 * Math.PI - Math.PI / 2;
    const large = endAngle - startAngle > Math.PI ? 1 : 0;
    const x1 = radius + radius * Math.cos(startAngle);
    const y1 = radius + radius * Math.sin(startAngle);
    const x2 = radius + radius * Math.cos(endAngle);
    const y2 = radius + radius * Math.sin(endAngle);
    const xi1 = radius + inner * Math.cos(startAngle);
    const yi1 = radius + inner * Math.sin(startAngle);
    const xi2 = radius + inner * Math.cos(endAngle);
    const yi2 = radius + inner * Math.sin(endAngle);
    const path = [
      `M${x1},${y1}`,
      `A${radius},${radius} 0 ${large} 1 ${x2},${y2}`,
      `L${xi2},${yi2}`,
      `A${inner},${inner} 0 ${large} 0 ${xi1},${yi1}`,
      "Z",
    ].join(" ");
    return { path, color: DONUT_COLORS[i % DONUT_COLORS.length], ...d };
  });

  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg width={size} height={size}>
        {arcs.map((arc, i) => (
          <path
            key={arc.label}
            d={arc.path}
            fill={arc.color}
            stroke="var(--surface-1)"
            strokeWidth={2}
            opacity={hovered === null || hovered === i ? 1 : 0.45}
            role={onSliceClick ? "button" : undefined}
            tabIndex={onSliceClick ? 0 : undefined}
            className={onSliceClick ? "cursor-pointer" : undefined}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
            onClick={onSliceClick ? () => onSliceClick(arc.label) : undefined}
          >
            {onSliceClick && <title>{`Drill down into ${arc.label}`}</title>}
          </path>
        ))}
      </svg>
      <ul className="flex flex-col gap-1.5 text-sm">
        {arcs.map((arc, i) => (
          <li
            key={arc.label}
            className={`flex items-center gap-2 ${onSliceClick ? "cursor-pointer" : ""}`}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
            onClick={onSliceClick ? () => onSliceClick(arc.label) : undefined}
          >
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: arc.color }}
            />
            <span className="text-[var(--text-primary)]">{arc.label}</span>
            <span className="text-[var(--text-muted)]">
              {((arc.value / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface GroupedDatum {
  label: string;
  series: string;
  value: number;
}

export function GroupedBarChart({
  data,
  stacked = false,
  valueLabel,
  currency,
  decimalPlaces,
}: {
  data: GroupedDatum[];
  stacked?: boolean;
  valueLabel?: string;
  currency?: string;
  decimalPlaces?: number;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  if (data.length === 0) return null;

  const labels = Array.from(new Set(data.map((d) => d.label)));
  const seriesNames = Array.from(new Set(data.map((d) => d.series)));
  const byLabel = new Map<string, GroupedDatum[]>();
  for (const d of data) {
    const list = byLabel.get(d.label) ?? [];
    list.push(d);
    byLabel.set(d.label, list);
  }
  const maxValue = stacked
    ? Math.max(...labels.map((l) => (byLabel.get(l) ?? []).reduce((sum, d) => sum + Math.abs(d.value), 0)), 1)
    : Math.max(...data.map((d) => Math.abs(d.value)), 1);

  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-wrap gap-3 text-xs">
        {seriesNames.map((s, i) => (
          <li key={s} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: DONUT_COLORS[i % DONUT_COLORS.length] }} />
            <span className="text-[var(--text-secondary)]">{s}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-3">
        {labels.map((label) => {
          const rows = byLabel.get(label) ?? [];
          return (
            <div key={label} className="flex items-center gap-3">
              <div className="w-32 shrink-0 truncate text-right text-xs text-[var(--text-secondary)]" title={label}>
                {label}
              </div>
              <div className={`flex flex-1 ${stacked ? "" : "gap-1"}`} style={{ height: stacked ? 20 : undefined }}>
                {rows.map((d) => {
                  const seriesIndex = seriesNames.indexOf(d.series);
                  const key = `${label}::${d.series}`;
                  const width = stacked
                    ? `${(Math.abs(d.value) / maxValue) * 100}%`
                    : `${Math.max((Math.abs(d.value) / maxValue) * 100, 2)}%`;
                  return (
                    <div
                      key={d.series}
                      className={stacked ? "h-full" : "rounded-full"}
                      style={{
                        height: stacked ? "100%" : 16,
                        width: stacked ? width : `${Math.max((Math.abs(d.value) / maxValue) * 100, 2)}%`,
                        background: DONUT_COLORS[seriesIndex % DONUT_COLORS.length],
                        opacity: hovered === null || hovered === key ? 1 : 0.4,
                      }}
                      onMouseEnter={() => setHovered(key)}
                      onMouseLeave={() => setHovered(null)}
                      title={`${d.series}: ${formatChartValue(d.value, valueLabel, currency, decimalPlaces)}`}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface ScatterDatum {
  x: number;
  y: number;
  label?: string;
}

export function ScatterChart({
  data,
  xLabel,
  yLabel,
  width = 640,
  height = 320,
}: {
  data: ScatterDatum[];
  xLabel?: string;
  yLabel?: string;
  width?: number;
  height?: number;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  if (data.length === 0) return null;

  const padding = { top: 16, right: 16, bottom: 32, left: 56 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const xs = data.map((d) => d.x);
  const ys = data.map((d) => d.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1;
  const yRange = yMax - yMin || 1;

  const px = (v: number) => padding.left + ((v - xMin) / xRange) * innerW;
  const py = (v: number) => padding.top + innerH - ((v - yMin) / yRange) * innerH;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <line x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} stroke="var(--gridline)" />
      <line x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} stroke="var(--gridline)" />
      {xLabel && (
        <text x={padding.left + innerW / 2} y={height - 4} textAnchor="middle" fontSize={10} fill="var(--text-muted)">
          {xLabel}
        </text>
      )}
      {yLabel && (
        <text x={12} y={padding.top + innerH / 2} textAnchor="middle" fontSize={10} fill="var(--text-muted)" transform={`rotate(-90 12 ${padding.top + innerH / 2})`}>
          {yLabel}
        </text>
      )}
      {data.map((d, i) => (
        <circle
          key={i}
          cx={px(d.x)}
          cy={py(d.y)}
          r={hoverIndex === i ? 5 : 3.5}
          fill={SERIES_1}
          opacity={0.75}
          onMouseEnter={() => setHoverIndex(i)}
          onMouseLeave={() => setHoverIndex(null)}
        />
      ))}
      {hoverIndex !== null && (
        <g>
          <rect x={px(data[hoverIndex].x) + 8} y={py(data[hoverIndex].y) - 24} width={100} height={20} rx={4} fill="var(--text-primary)" />
          <text x={px(data[hoverIndex].x) + 14} y={py(data[hoverIndex].y) - 10} fontSize={10} fill="var(--surface-1)">
            {formatNumber(data[hoverIndex].x)}, {formatNumber(data[hoverIndex].y)}
          </text>
        </g>
      )}
    </svg>
  );
}

interface MapPoint {
  lat: number;
  lng: number;
  label?: string;
  value?: number;
}

/** A plain equirectangular point-plot (longitude as x, latitude as y) --
 * not a tiled basemap. Deliberate: a real basemap needs a tile provider or
 * a GeoJSON dependency neither already present in this project, and the
 * spec explicitly says not to introduce unnecessary dependencies for this.
 * Point positions and relative distances are still geographically correct. */
export function PointMapChart({
  points,
  width = 640,
  height = 360,
  valueLabel,
  currency,
  decimalPlaces,
}: {
  points: MapPoint[];
  width?: number;
  height?: number;
  valueLabel?: string;
  currency?: string;
  decimalPlaces?: number;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  if (points.length === 0) return null;

  const maxValue = Math.max(...points.map((p) => Math.abs(p.value ?? 1)), 1);
  const px = (lng: number) => ((lng + 180) / 360) * width;
  const py = (lat: number) => ((90 - lat) / 180) * height;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="rounded-lg border border-[var(--border)] bg-[var(--background)]">
      <rect x={0} y={0} width={width} height={height} fill="var(--background)" />
      {Array.from({ length: 7 }).map((_, i) => (
        <line key={`lat-${i}`} x1={0} x2={width} y1={(height / 6) * i} y2={(height / 6) * i} stroke="var(--gridline)" strokeWidth={0.5} />
      ))}
      {Array.from({ length: 13 }).map((_, i) => (
        <line key={`lng-${i}`} x1={(width / 12) * i} x2={(width / 12) * i} y1={0} y2={height} stroke="var(--gridline)" strokeWidth={0.5} />
      ))}
      {points.map((p, i) => {
        const r = 3 + (Math.abs(p.value ?? 1) / maxValue) * 9;
        return (
          <circle
            key={i}
            cx={px(p.lng)}
            cy={py(p.lat)}
            r={r}
            fill={SERIES_1}
            opacity={hoverIndex === null || hoverIndex === i ? 0.7 : 0.3}
            stroke="var(--surface-1)"
            strokeWidth={1}
            onMouseEnter={() => setHoverIndex(i)}
            onMouseLeave={() => setHoverIndex(null)}
          />
        );
      })}
      {hoverIndex !== null && points[hoverIndex].label && (
        <text x={px(points[hoverIndex].lng) + 10} y={py(points[hoverIndex].lat)} fontSize={11} fill="var(--text-primary)">
          {points[hoverIndex].label}
          {points[hoverIndex].value !== undefined
            ? ` — ${formatChartValueShort(points[hoverIndex].value!, valueLabel, currency, decimalPlaces)}`
            : ""}
        </text>
      )}
    </svg>
  );
}

function UnmatchedCountriesDisclosure({ values }: { values: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="text-xs text-[var(--text-muted)]">
      <button onClick={() => setOpen((v) => !v)} className="text-[var(--series-1)] hover:underline">
        {open ? "Hide" : "View"} unmatched values ({values.length})
      </button>
      {open && (
        <p className="mt-1">
          Some country values could not be mapped: {values.join(", ")}
        </p>
      )}
    </div>
  );
}

export function ChartFromSpec({
  spec,
  currency,
  decimalPlaces,
}: {
  spec: ChartSpec;
  /** Presentation-only, from the user's Settings preference -- applied to
   * any value whose column/axis name looks monetary. */
  currency?: string;
  decimalPlaces?: number;
}) {
  if (!spec.data || spec.data.length === 0) return null;
  const xKey = spec.x_column ?? Object.keys(spec.data[0])[0];
  const yKey = spec.y_column ?? Object.keys(spec.data[0])[1];
  const valueLabel = spec.y_column ?? yKey;

  if (spec.chart_type === "kpi_card") {
    const value = spec.data[0][yKey] ?? Object.values(spec.data[0])[0];
    return (
      <StatCard
        label={spec.y_column ?? "value"}
        value={typeof value === "number" ? value : String(value)}
        description={spec.reason}
        currency={currency}
        decimalPlaces={decimalPlaces}
      />
    );
  }

  if (spec.chart_type === "line" || spec.chart_type === "time_series") {
    return (
      <LineChart
        data={spec.data.map((row) => ({ label: String(row[xKey]), value: Number(row[yKey]) }))}
        valueLabel={valueLabel}
        currency={currency}
        decimalPlaces={decimalPlaces}
      />
    );
  }

  if (spec.chart_type === "donut" || spec.chart_type === "pie") {
    return (
      <DonutChart
        data={spec.data.map((row) => ({ label: String(row[xKey]), value: Number(row[yKey]) }))}
      />
    );
  }

  if (spec.chart_type === "insufficient_data") return null;

  if (spec.chart_type === "grouped_bar" || spec.chart_type === "stacked_bar") {
    const seriesKey = spec.series_column ?? Object.keys(spec.data[0]).find((k) => k !== xKey && k !== yKey) ?? xKey;
    return (
      <GroupedBarChart
        stacked={spec.chart_type === "stacked_bar"}
        data={spec.data.map((row) => ({ label: String(row[xKey]), series: String(row[seriesKey]), value: Number(row[yKey]) }))}
        valueLabel={valueLabel}
        currency={currency}
        decimalPlaces={decimalPlaces}
      />
    );
  }

  if (spec.chart_type === "scatter") {
    const keys = Object.keys(spec.data[0]);
    const xNumKey = spec.x_column ?? keys[0];
    const yNumKey = spec.y_column ?? keys[1];
    return (
      <ScatterChart
        xLabel={xNumKey}
        yLabel={yNumKey}
        data={spec.data.map((row) => ({ x: Number(row[xNumKey]), y: Number(row[yNumKey]) }))}
      />
    );
  }

  if (spec.chart_type === "map") {
    return (
      <div className="flex flex-col gap-2">
        <PointMapChart
          points={spec.data.map((row) => ({
            lat: Number(row.lat ?? row.latitude),
            lng: Number(row.lng ?? row.longitude),
            label: "label" in row ? String(row.label) : xKey in row ? String(row[xKey]) : undefined,
            value: "value" in row ? Number(row.value) : yKey in row ? Number(row[yKey]) : undefined,
          }))}
          valueLabel={valueLabel}
          currency={currency}
          decimalPlaces={decimalPlaces}
        />
        {spec.unmatched_categories && spec.unmatched_categories.length > 0 && (
          <UnmatchedCountriesDisclosure values={spec.unmatched_categories} />
        )}
      </div>
    );
  }

  return (
    <BarChart
      data={spec.data.map((row) => ({ label: String(row[xKey]), value: Number(row[yKey]) }))}
      valueLabel={valueLabel}
      currency={currency}
      decimalPlaces={decimalPlaces}
    />
  );
}
