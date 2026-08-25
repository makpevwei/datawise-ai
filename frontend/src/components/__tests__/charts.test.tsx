import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChartFromSpec, StatCard } from "../charts";
import { Table } from "../ui";
import type { ChartSpec } from "@/lib/types";

function makeSpec(overrides: Partial<ChartSpec>): ChartSpec {
  return {
    chart_type: "bar",
    dataset_id: "d1",
    x_column: "region",
    y_column: "revenue",
    series_column: null,
    aggregation: "sum",
    filters: [],
    reason: "test",
    data: [
      { region: "North", revenue: 1000 },
      { region: "South", revenue: 2000 },
    ],
    unmatched_categories: null,
    ...overrides,
  };
}

describe("currency-aware value formatting (Settings currency must reach every figure, not just AnalysisWorkspace)", () => {
  it("StatCard shows the currency symbol for a monetary label", () => {
    render(<StatCard label="Total Revenue" value={69166.61} currency="USD" decimalPlaces={2} />);
    expect(screen.getByText("$69,166.61")).toBeInTheDocument();
  });

  it("StatCard leaves a non-monetary label as a plain number even when a currency is set", () => {
    render(<StatCard label="Total Orders" value={342} currency="USD" decimalPlaces={2} />);
    expect(screen.getByText("342")).toBeInTheDocument();
    expect(screen.queryByText("$342.00")).not.toBeInTheDocument();
  });

  it("ChartFromSpec renders a bar chart's values in the selected currency when the y-axis column looks monetary", () => {
    render(<ChartFromSpec spec={makeSpec({ chart_type: "bar" })} currency="USD" decimalPlaces={2} />);
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
    expect(screen.getByText("$2,000.00")).toBeInTheDocument();
  });

  it("ChartFromSpec renders plain numbers when no currency is passed (unauthenticated/default state)", () => {
    render(<ChartFromSpec spec={makeSpec({ chart_type: "bar" })} />);
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.queryByText("$1,000.00")).not.toBeInTheDocument();
  });

  it("ChartFromSpec renders a kpi_card in the selected currency", () => {
    render(
      <ChartFromSpec
        spec={makeSpec({
          chart_type: "kpi_card",
          x_column: null,
          y_column: "total_revenue",
          data: [{ total_revenue: 69166.61 }],
        })}
        currency="USD"
        decimalPlaces={2}
      />,
    );
    expect(screen.getByText("$69,166.61")).toBeInTheDocument();
  });

  it("Table formats a monetary-looking column with the selected currency and leaves other numeric columns alone", () => {
    render(
      <Table
        columns={["region", "revenue", "order_count"]}
        rows={[{ region: "North", revenue: 1000, order_count: 12 }]}
        currency="USD"
        decimalPlaces={2}
      />,
    );
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("respects a different currency and decimal-places setting (e.g. NGN, 0 decimals)", () => {
    render(<StatCard label="Total Sales" value={69166.61} currency="NGN" decimalPlaces={0} />);
    expect(screen.getByText(/NGN\s*69,167|₦69,167/)).toBeInTheDocument();
  });
});
