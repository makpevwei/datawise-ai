import type { ChartType, DatasetProfile } from "./types";

/** Which chart types are technically valid for the currently selected
 * fields -- Phase 4 continuation section 17. This mirrors (does not
 * replace) the backend's own chart-type recommendation
 * (app/visualization/recommender.py, app/analysis/engine.py): the backend
 * remains the sole source of truth for what it actually returns, this is
 * only used to decide what to OFFER in the UI selector so a user is never
 * shown an option that can't produce a real chart. */
export interface ChartFieldSelection {
  metricColumn: string;
  secondMetricColumn?: string;
  dimensionColumn: string;
  secondDimensionColumn: string;
  dateColumn: string;
}

const GEO_LAT_NAMES = ["lat", "latitude"];
const GEO_LNG_NAMES = ["lng", "lon", "long", "longitude"];
const GEO_REGION_NAMES = ["country", "country_name", "state", "state_name", "region", "city"];
// Mirrors app/geography/countries.py's COUNTRY_COLUMN_NAME_ALIASES -- only
// a genuinely country-named column gets the deterministic centroid lookup
// (Phase 4 continuation section 20-28). State/city intentionally do NOT
// qualify here: there's no reliable deterministic lookup for those, and
// the spec explicitly says not to add an external geocoding API for them.
const COUNTRY_COLUMN_NAMES = [
  "country", "country name", "countryname", "nation", "country code",
  "countrycode", "iso country", "iso country code", "isocountry", "isocountrycode",
  "country_name", "country_code", "iso_country", "iso_country_code",
];

export function detectGeographicColumns(profile: DatasetProfile): { lat: string | null; lng: string | null; region: string | null } {
  const names = profile.columns.map((c) => c.name);
  const find = (candidates: string[]) => names.find((n) => candidates.includes(n.toLowerCase())) ?? null;
  return { lat: find(GEO_LAT_NAMES), lng: find(GEO_LNG_NAMES), region: find(GEO_REGION_NAMES) };
}

function isCountryColumn(columnName: string): boolean {
  return COUNTRY_COLUMN_NAMES.includes(columnName.toLowerCase().trim());
}

export function compatibleChartTypes(profile: DatasetProfile, sel: ChartFieldSelection): ChartType[] {
  const hasMetric = !!sel.metricColumn;
  const hasSecondMetric = !!sel.secondMetricColumn;
  const hasDimension = !!sel.dimensionColumn;
  const hasSecondDimension = !!sel.secondDimensionColumn;
  const hasDate = !!sel.dateColumn;
  const { lat, lng } = detectGeographicColumns(profile);
  const hasGeo = !!lat && !!lng;

  const types: ChartType[] = [];

  if (hasSecondMetric && !hasDimension) {
    // Two numeric measures, no breakdown -- scatter is the only fit.
    types.push("scatter");
    return types;
  }

  if (hasGeo) types.push("map");

  if (hasDate && hasMetric) {
    types.push("line", "column");
    return types; // date branch doesn't combine with dimension/second-dimension charts
  }

  if (hasDimension && hasSecondDimension && hasMetric) {
    types.push("grouped_bar", "stacked_bar");
    return types;
  }

  if (hasDimension && hasMetric) {
    types.push("bar", "column");
    // Donut/pie only make sense for a handful of categories -- mirror the
    // backend's DONUT_MAX_CATEGORIES rule using the profiled cardinality
    // where we can determine it.
    const col = profile.columns.find((c) => c.name === sel.dimensionColumn);
    if (!col || col.unique_count <= 6) types.push("donut", "pie");
    // A country-named dimension gets a deterministic centroid lookup
    // server-side (app/geography/countries.py) -- no lat/lng columns
    // required, unlike the raw-coordinate case above.
    if (isCountryColumn(sel.dimensionColumn) && !types.includes("map")) types.push("map");
    return types;
  }

  if (hasMetric && !hasDimension) {
    types.push("kpi_card", "bar", "column");
    return types;
  }

  return types;
}

export function defaultChartType(available: ChartType[]): ChartType | null {
  return available[0] ?? null;
}
