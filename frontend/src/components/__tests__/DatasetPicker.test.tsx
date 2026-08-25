import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DatasetSummary } from "@/lib/types";
import { DatasetPicker } from "../DatasetPicker";
import { InsightsPanel } from "../InsightsPanel";

vi.mock("@/lib/api", () => ({
  getInsights: vi.fn().mockResolvedValue([]),
  getKpiSuggestions: vi.fn().mockResolvedValue([]),
  getDatasetSample: vi.fn().mockResolvedValue([]),
  askAgent: vi.fn().mockResolvedValue({
    session_id: "s1",
    question: "test",
    configured: true,
    executive_summary: "",
    key_findings: [],
    risks: [],
    recommendations: [],
    claim_comparisons: [],
    charts: [],
    citations: [],
    trace: [],
    tool_invocations: [],
    raw_answer_text: "",
    error: null,
    llm_metadata: null,
    created_at: new Date().toISOString(),
    message_id: null,
  }),
  runAnalysis: vi.fn().mockResolvedValue({
    request: { dataset_id: "orders", aggregation: "sum" },
    result_type: "insufficient_data",
    scalar_value: null,
    table: null,
    columns_used: [],
    row_count_considered: 0,
    calculation_description: "",
    source: "CALCULATED",
    chart_recommendation: null,
  }),
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
const products = summary({ id: "products", name: "products.csv", source_file: "products.csv" });

describe("DatasetPicker", () => {
  it("renders nothing when there are no datasets", () => {
    const { container } = render(<DatasetPicker datasets={[]} selectedIds={null} onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows 'All datasets (N)' when selectedIds is null", () => {
    render(<DatasetPicker datasets={[orders, customers]} selectedIds={null} onChange={vi.fn()} />);
    expect(screen.getByText("All datasets (2)")).toBeInTheDocument();
  });

  it("shows the selected count when a subset is chosen", () => {
    render(<DatasetPicker datasets={[orders, customers, products]} selectedIds={["orders"]} onChange={vi.fn()} />);
    expect(screen.getByText("1 dataset selected")).toBeInTheDocument();
  });

  it("expands to show every dataset as a checkbox on click", () => {
    render(<DatasetPicker datasets={[orders, customers]} selectedIds={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByText("All datasets (2)"));
    expect(screen.getByText("orders.csv")).toBeInTheDocument();
    expect(screen.getByText("customers.csv")).toBeInTheDocument();
  });

  it("unchecking one dataset out of all reports the remaining ids (not null)", () => {
    const onChange = vi.fn();
    render(<DatasetPicker datasets={[orders, customers]} selectedIds={null} onChange={onChange} />);
    fireEvent.click(screen.getByText("All datasets (2)"));
    fireEvent.click(screen.getByRole("checkbox", { name: /orders\.csv/i }));
    expect(onChange).toHaveBeenCalledWith(["customers"]);
  });

  it("re-checking the last missing dataset reports null (back to 'all')", () => {
    const onChange = vi.fn();
    render(<DatasetPicker datasets={[orders, customers]} selectedIds={["customers"]} onChange={onChange} />);
    fireEvent.click(screen.getByText("1 dataset selected"));
    fireEvent.click(screen.getByRole("checkbox", { name: /orders\.csv/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("Select All calls onChange(null) and Clear All calls onChange([])", () => {
    const onChange = vi.fn();
    render(<DatasetPicker datasets={[orders, customers]} selectedIds={["orders"]} onChange={onChange} />);
    fireEvent.click(screen.getByText("1 dataset selected"));
    fireEvent.click(screen.getByText("Select All"));
    expect(onChange).toHaveBeenCalledWith(null);
    fireEvent.click(screen.getByText("Clear All"));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("groups sheets of the same workbook under the workbook name", () => {
    const sheet1 = summary({ id: "s1", name: "Sales", source_file: "sales.xlsx", sheet_name: "Sales" });
    const sheet2 = summary({ id: "s2", name: "Customers", source_file: "sales.xlsx", sheet_name: "Customers" });
    render(<DatasetPicker datasets={[sheet1, sheet2]} selectedIds={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByText("All datasets (2)"));
    expect(screen.getByText("sales.xlsx")).toBeInTheDocument();
  });

  it("filters by search when there are enough datasets to show the search box", () => {
    const many = Array.from({ length: 7 }, (_, i) => summary({ id: `d${i}`, name: `dataset${i}.csv`, source_file: `dataset${i}.csv` }));
    render(<DatasetPicker datasets={many} selectedIds={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByText("All datasets (7)"));
    fireEvent.change(screen.getByPlaceholderText(/search datasets/i), { target: { value: "dataset3" } });
    expect(screen.getByText("dataset3.csv")).toBeInTheDocument();
    expect(screen.queryByText("dataset0.csv")).not.toBeInTheDocument();
  });

  it("InsightsPanel uses the shared dataset picker by default for multiple datasets", async () => {
    render(<InsightsPanel datasets={[orders, customers]} />);
    expect(screen.getByText("All datasets (2)")).toBeInTheDocument();
    expect(screen.getByText("Visual Insights")).toBeInTheDocument();
  });
});
