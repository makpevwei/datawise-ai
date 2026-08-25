import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u1", full_name: "Ada Lovelace", email: "ada@example.com", currency: "USD", decimal_places: 2 },
    loading: false,
    logout: vi.fn(),
    setUser: vi.fn(),
  }),
}));

import { AnalysisWorkspace } from "../AnalysisWorkspace";
import * as api from "@/lib/api";
import type { DatasetProfile, DatasetSummary } from "@/lib/types";

const summary: DatasetSummary = {
  id: "d1",
  name: "orders.csv",
  source_file: "orders.csv",
  sheet_name: null,
  kind: "uploaded",
  row_count: 20,
  column_count: 5,
  quality_rating: "good",
  created_at: new Date().toISOString(),
};

const profile: DatasetProfile = {
  ...summary,
  columns: [],
  numeric_columns: ["amount"],
  categorical_columns: ["region"],
  date_columns: ["date"],
  identifier_columns: [],
  text_columns: [],
  quality: {
    duplicate_row_count: 0,
    duplicate_row_percentage: 0,
    columns_mostly_missing: [],
    possible_id_columns: [],
    possible_date_columns: [],
    numeric_stored_as_text_columns: [],
    high_cardinality_columns: [],
    duplicate_column_names: [],
    overall_rating: "good",
    notes: [],
  },
};

describe("AnalysisWorkspace", () => {
  it("shows an empty state with no datasets", () => {
    render(<AnalysisWorkspace datasets={[]} />);
    expect(screen.getByText(/no datasets yet/i)).toBeInTheDocument();
  });

  it("runs an analysis and renders a scalar KPI card result", async () => {
    vi.spyOn(api, "getDataset").mockResolvedValue(profile);
    vi.spyOn(api, "getKpiSuggestions").mockResolvedValue([]);
    vi.spyOn(api, "runAnalysis").mockResolvedValue({
      request: { dataset_id: "d1", aggregation: "sum", metric_column: "amount" },
      result_type: "scalar",
      scalar_value: 4200,
      table: null,
      columns_used: ["amount"],
      row_count_considered: 20,
      calculation_description: "sum(amount) over 20 row(s)",
      source: "CALCULATED",
      chart_recommendation: {
        chart_type: "kpi_card",
        dataset_id: "d1",
        x_column: null,
        y_column: "amount",
        series_column: null,
        unmatched_categories: null,
        aggregation: "sum",
        filters: [],
        reason: "A single aggregated value is best shown as a KPI card.",
        data: [{ amount: 4200 }],
      },
    });

    render(<AnalysisWorkspace datasets={[summary]} />);

    const runButton = await screen.findByRole("button", { name: /run analysis/i });
    fireEvent.click(runButton);

    // metric_column "amount" reads as monetary, so it's formatted with the
    // user's currency/decimal-place preference (USD, 2 places from the mock).
    await waitFor(() => expect(screen.getByText("$4,200.00")).toBeInTheDocument());
    expect(screen.getByText("CALCULATED")).toBeInTheDocument();
  });

  it("shows an error banner when the analysis request fails", async () => {
    vi.spyOn(api, "getDataset").mockResolvedValue(profile);
    vi.spyOn(api, "getKpiSuggestions").mockResolvedValue([]);
    vi.spyOn(api, "runAnalysis").mockRejectedValue(new Error("Column 'amount' not found."));

    render(<AnalysisWorkspace datasets={[summary]} />);

    const runButton = await screen.findByRole("button", { name: /run analysis/i });
    fireEvent.click(runButton);

    await waitFor(() => expect(screen.getByText(/column 'amount' not found/i)).toBeInTheDocument());
  });

  it("shows insufficient-data messaging when the backend reports it", async () => {
    vi.spyOn(api, "getDataset").mockResolvedValue(profile);
    vi.spyOn(api, "getKpiSuggestions").mockResolvedValue([]);
    vi.spyOn(api, "runAnalysis").mockResolvedValue({
      request: { dataset_id: "d1", aggregation: "sum" },
      result_type: "insufficient_data",
      scalar_value: null,
      table: null,
      columns_used: [],
      row_count_considered: 0,
      calculation_description: "No rows remain after applying the requested filters.",
      source: "INSUFFICIENT_DATA",
      chart_recommendation: {
        chart_type: "insufficient_data",
        dataset_id: "d1",
        x_column: null,
        y_column: null,
        series_column: null,
        unmatched_categories: null,
        aggregation: null,
        filters: [],
        reason: "Not enough data to recommend a chart.",
        data: null,
      },
    });

    render(<AnalysisWorkspace datasets={[summary]} />);

    const runButton = await screen.findByRole("button", { name: /run analysis/i });
    fireEvent.click(runButton);

    await waitFor(() =>
      expect(screen.getByText(/insufficient data to determine this/i)).toBeInTheDocument(),
    );
  });
});
