import { describe, expect, it } from "vitest";
import {
  buildStarterQuestions,
  GENERIC_STARTER_QUESTIONS,
  NEXASPHERE_CASE_STUDY_QUESTIONS,
  questionFromKpi,
} from "../starterQuestions";
import type { KPISuggestion } from "../types";

function kpi(overrides: Partial<KPISuggestion>): KPISuggestion {
  return {
    name: "Total price",
    dataset_id: "d1",
    metric_column: "price",
    aggregation: "sum",
    dimension_column: null,
    date_column: null,
    rationale: "",
    label: "Suggested KPI",
    preview_value: 100,
    preview_source: "CALCULATED",
    ...overrides,
  };
}

describe("questionFromKpi", () => {
  it("phrases a scalar sum as a total question", () => {
    expect(questionFromKpi(kpi({ aggregation: "sum", metric_column: "price", dimension_column: null }))).toBe(
      "What is the total price?",
    );
  });

  it("phrases a sum-by-dimension as a 'which X has the highest' question", () => {
    expect(
      questionFromKpi(kpi({ aggregation: "sum", metric_column: "price", dimension_column: "region" })),
    ).toBe("Which region has the highest total price?");
  });

  it("phrases a mean as an average question", () => {
    expect(questionFromKpi(kpi({ aggregation: "mean", metric_column: "order_value" }))).toBe(
      "What is the average order value?",
    );
  });

  it("phrases a date-bound KPI as a trend question", () => {
    expect(questionFromKpi(kpi({ aggregation: "sum", metric_column: "price", date_column: "date" }))).toBe(
      "What is the price trend over time?",
    );
  });

  it("phrases a nunique KPI as a distinct-count question", () => {
    expect(
      questionFromKpi(kpi({ aggregation: "nunique", metric_column: "order_id", dimension_column: "customer_id" })),
    ).toBe("How many distinct order id are there by customer id?");
  });

  it("never references a column that wasn't actually passed in", () => {
    // metric_column null -> falls back to "records", never invents a name.
    const q = questionFromKpi(kpi({ aggregation: "count", metric_column: null, dimension_column: "region" }));
    expect(q).toBe("How many records are there by region?");
  });
});

describe("buildStarterQuestions", () => {
  it("produces at least 10 questions even with only a handful of real KPIs", () => {
    const kpis = [
      kpi({ aggregation: "sum", metric_column: "price" }),
      kpi({ aggregation: "sum", metric_column: "price", dimension_column: "region" }),
      kpi({ aggregation: "mean", metric_column: "price" }),
    ];
    const questions = buildStarterQuestions(kpis);
    expect(questions.length).toBeGreaterThanOrEqual(10);
  });

  it("never duplicates a question and prefers real grounded ones over generic filler", () => {
    // 12 distinct real KPIs should need zero generic filler.
    const kpis = Array.from({ length: 12 }, (_, i) =>
      kpi({ aggregation: "sum", metric_column: `metric_${i}` }),
    );
    const questions = buildStarterQuestions(kpis);
    expect(new Set(questions).size).toBe(questions.length);
    expect(questions.some((q) => GENERIC_STARTER_QUESTIONS.includes(q))).toBe(false);
  });

  it("tops up with generic questions when there aren't enough real KPIs", () => {
    const questions = buildStarterQuestions([kpi({ aggregation: "sum", metric_column: "price" })]);
    expect(questions.length).toBeGreaterThanOrEqual(10);
    expect(questions.some((q) => GENERIC_STARTER_QUESTIONS.includes(q))).toBe(true);
  });

  it("shows the case study's curated questions only when the loaded data is actually the NexaSphere workbook", () => {
    const nexasphereKpis = [
      kpi({ metric_column: "Gross_Sales_NGN", dataset_name: "NexaSphere_BI_Case_Study_Dataset.xlsx — Fact_Sales" }),
    ];
    const questions = buildStarterQuestions(nexasphereKpis);
    for (const q of NEXASPHERE_CASE_STUDY_QUESTIONS) {
      expect(questions).toContain(q);
    }
  });

  it("never shows the NexaSphere-specific questions for an unrelated dataset", () => {
    const otherKpis = [kpi({ metric_column: "price", dataset_name: "some_other_shop.csv" })];
    const questions = buildStarterQuestions(otherKpis);
    for (const q of NEXASPHERE_CASE_STUDY_QUESTIONS) {
      expect(questions).not.toContain(q);
    }
  });
});
