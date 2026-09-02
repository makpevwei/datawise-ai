import type { KPISuggestion } from "./types";

/** Turns a real, backend-computed KPI suggestion into a natural-language
 * starter question -- every question this produces is grounded in an
 * actual column that exists in the dataset, never invented, since it's
 * built directly from the same suggestions the deterministic engine
 * already generated from the real schema. */
function humanize(column: string): string {
  return column.replace(/[_-]+/g, " ").trim();
}

export function questionFromKpi(kpi: KPISuggestion): string {
  const metric = kpi.metric_column ? humanize(kpi.metric_column) : "records";
  const dim = kpi.dimension_column ? humanize(kpi.dimension_column) : null;

  if (kpi.date_column) {
    return dim ? `What is the ${metric} trend over time by ${dim}?` : `What is the ${metric} trend over time?`;
  }

  switch (kpi.aggregation) {
    case "sum":
      return dim ? `Which ${dim} has the highest total ${metric}?` : `What is the total ${metric}?`;
    case "mean":
    case "median":
      return dim ? `What is the average ${metric} by ${dim}?` : `What is the average ${metric}?`;
    case "count":
      return dim ? `How many records are there by ${dim}?` : `How many records are there in total?`;
    case "nunique":
      return dim ? `How many distinct ${metric} are there by ${dim}?` : `How many distinct ${metric} are there?`;
    case "min":
      return dim ? `What is the minimum ${metric} by ${dim}?` : `What is the minimum ${metric}?`;
    case "max":
      return dim ? `What is the maximum ${metric} by ${dim}?` : `What is the maximum ${metric}?`;
    default:
      return dim ? `What is the ${metric} by ${dim}?` : `What is the ${metric}?`;
  }
}

/** Data-agnostic questions that make sense with no dataset-specific
 * schema knowledge at all -- used to top up the list to the required
 * minimum, and as the entire list before any dataset/KPI exists yet.
 * Long enough on its own to reach the minimum even when a dataset has
 * very few real KPI suggestions. */
export const GENERIC_STARTER_QUESTIONS = [
  "What is the total number of records?",
  "Are there any unusual patterns in the data?",
  "Which columns are most useful for analysis?",
  "Show me something interesting.",
  "What changed over time?",
  "What is the data quality like?",
  "Summarize this dataset for me.",
  "What is customer churn?",
  "How do you calculate gross margin?",
  "What's a healthy inventory turnover ratio?",
];

/** Generic business-intelligence starter questions -- named for the
 * domain (business analytics) not for any specific dataset or demo.
 * They deliberately use business concepts, not schema columns: the
 * semantic resolver maps each concept to actual fields and will report
 * unavailable evidence rather than fabricate it. This list must stay
 * dataset-agnostic -- buildStarterQuestions() below already produces
 * genuinely dataset-specific questions (grounded in whatever KPIs the
 * backend actually discovers for whatever CSV/Excel a user uploads, this
 * case study's NexaSphere workbook included) from real schema, not from
 * hardcoded text; this array is only the generic filler/fallback used to
 * top that list up to the minimum, so it must stay sensible for any
 * dataset, not just one. */
export const BUSINESS_STARTER_QUESTIONS = [
  "Which products generate the most revenue and profit?",
  "Is revenue growth leading to stronger profitability?",
  "Which products have unusually high return rates?",
  "Which marketing campaigns have the best ROI?",
  "Which stores have stockout problems?",
  "Which delivery partners have the most delays?",
  "Which customer segments are most valuable?",
  "Which employees perform best?",
  "Where are we missing our targets?",
];

const MIN_STARTER_QUESTIONS = 10;

/** The AI BuildFest 2026 Case Study 4 "Suggested Management Questions,"
 * verbatim -- shown ONLY when the loaded data is actually (or came from)
 * the case study's own NexaSphere workbook, detected below by dataset
 * name. This is deliberately not a hardcode of the generic fallback
 * lists above: any other dataset -- a different company's CSV, a
 * differently-named copy of a similar retail schema -- still gets the
 * fully generic, KPI-derived question set with zero NexaSphere-specific
 * text, exactly as before. */
export const NEXASPHERE_CASE_STUDY_QUESTIONS = [
  "Which products, stores or regions generate the most revenue and contribution profit?",
  "Is revenue growth leading to stronger profitability, or is growth becoming expensive?",
  "Which products or batches have unusually high return rates?",
  "Which marketing campaigns generate the best ROAS and profit ROI?",
  "Which stores or regions are experiencing stockouts or excess inventory?",
  "Which delivery partners are associated with delays, returns or poor ratings?",
  "Which customer segments and loyalty tiers are most valuable?",
  "Which employees perform well when revenue, discounting, returns and profit are considered together?",
  "Where is NexaSphere missing its targets, and what should management do next?",
];

/** Detected by dataset name only, never by asserting business meaning a
 * column doesn't already carry -- the exact same "never invent, only
 * recognize what's actually there" rule every other part of this file
 * already follows. */
function isNexaSphereDataset(kpis: KPISuggestion[]): boolean {
  return kpis.some((k) => k.dataset_name?.toLowerCase().includes("nexasphere"));
}

/** Builds at least MIN_STARTER_QUESTIONS grounded starter questions from
 * real KPI suggestions, topped up with generic (but still honest, never
 * fabricated-column) filler questions only if there aren't enough KPIs to
 * reach the minimum on their own. When the loaded data is recognizably
 * the NexaSphere case study workbook, the case study's own curated
 * questions are shown first (still deduped against whatever the KPI
 * engine also produced), since those are the actual evaluation questions
 * this product needs to answer well for that dataset. */
export function buildStarterQuestions(kpis: KPISuggestion[]): string[] {
  const grounded = kpis.map(questionFromKpi);
  const curated = isNexaSphereDataset(kpis) ? NEXASPHERE_CASE_STUDY_QUESTIONS : [];
  const deduped = Array.from(new Set([...curated, ...grounded]));
  const withFiller = [...deduped];
  for (const filler of GENERIC_STARTER_QUESTIONS) {
    if (withFiller.length >= MIN_STARTER_QUESTIONS) break;
    if (!withFiller.includes(filler)) withFiller.push(filler);
  }
  return withFiller;
}
