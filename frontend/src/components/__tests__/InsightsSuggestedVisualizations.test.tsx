import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DatasetSummary, KPISuggestion } from "@/lib/types";
import { InsightsPanel } from "../InsightsPanel";

function kpi(overrides: Partial<KPISuggestion>): KPISuggestion {
  return {
    name: "Some KPI",
    dataset_id: "orders",
    dataset_name: "orders.csv",
    dataset_sheet: null,
    metric_column: "amount",
    aggregation: "sum",
    dimension_column: null,
    date_column: null,
    rationale: "test",
    label: "Suggested KPI",
    preview_value: 1,
    preview_source: "CALCULATED",
    ...overrides,
  };
}

const getKpiSuggestions = vi.fn((datasetId: string) => {
  if (datasetId === "orders") {
    // Five suggestions -- exactly fills MAX_CHARTS (5) on its own, so
    // "customers"'s own suggestion below has no room left unless it's
    // actively prioritized.
    return Promise.resolve(
      Array.from({ length: 5 }, (_, i) => kpi({ name: `Orders KPI ${i + 1}`, dataset_id: "orders" })),
    );
  }
  if (datasetId === "customers") {
    return Promise.resolve([kpi({ name: "Customers KPI", dataset_id: "customers", dataset_name: "customers.csv" })]);
  }
  return Promise.resolve([]);
});

vi.mock("@/lib/api", () => ({
  getInsights: vi.fn().mockResolvedValue([]),
  getKpiSuggestions: (datasetId: string) => getKpiSuggestions(datasetId),
  getDatasetSample: vi.fn().mockResolvedValue([]),
  askAgent: vi.fn(),
  runAnalysis: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { currency: "USD", decimal_places: 2 } }),
}));

function summary(overrides: Partial<DatasetSummary>): DatasetSummary {
  return {
    id: "d1",
    name: "orders.csv",
    source_file: "orders.csv",
    sheet_name: null,
    kind: "uploaded",
    row_count: 20,
    column_count: 5,
    quality_rating: "good",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

const orders = summary({ id: "orders", name: "orders.csv", source_file: "orders.csv" });
const customers = summary({ id: "customers", name: "customers.csv", source_file: "customers.csv" });

describe("Suggested Visualizations reacts to Data Explorer's preview dataset", () => {
  it("surfaces the previewed dataset's own suggestions even when another dataset's already fill the cap", async () => {
    // Real gap, reported live: switching Data Explorer's preview dataset
    // had zero visible effect on Suggested Visualizations -- the two
    // selectors felt completely disconnected.
    render(<InsightsPanel datasets={[orders, customers]} />);

    // Default preview is the first dataset (orders) -- its 5 suggestions
    // fill the cap; customers' own suggestion isn't shown yet.
    await waitFor(() => expect(screen.getByText("Orders KPI 1")).toBeInTheDocument());
    expect(screen.queryByText("Customers KPI")).not.toBeInTheDocument();

    // Switch Data Explorer's preview to "customers".
    fireEvent.click(screen.getByRole("radio", { name: /preview customers\.csv/i }));

    // Its suggestion is now prioritized into the visible slice.
    await waitFor(() => expect(screen.getByText("Customers KPI")).toBeInTheDocument());
  });
});
