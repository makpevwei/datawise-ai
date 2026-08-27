import { fireEvent, render, screen } from "@testing-library/react";
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
  it("StatCard shows the currency symbol for a monetary label, abbreviated so it never overflows the card, with the exact value available via title", () => {
    render(<StatCard label="Total Revenue" value={69166.61} currency="USD" decimalPlaces={2} />);
    const button = screen.getByText("$69.2K");
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("title", "$69,166.61");
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

  it("ChartFromSpec renders a kpi_card in the selected currency, abbreviated with the exact value on click/title", () => {
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
    const button = screen.getByText("$69.2K");
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("title", "$69,166.61");
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

  it("Table shows key/id columns as their exact raw source value -- no currency, and no thousands separators either", () => {
    // Real bug reproduced live: SalesOrderLineKey matched MONETARY_LABEL_HINTS
    // on the "Sales" substring alone and got rendered as "US$43,659,001.00".
    // A key is a label, not a quantity -- it must render as uploaded, with
    // no numeric formatting of any kind, not even a thousands separator.
    render(
      <Table
        columns={["SalesOrderLineKey", "CustomerKey", "product_id", "revenue"]}
        rows={[{ SalesOrderLineKey: 43659001, CustomerKey: 11000, product_id: 349, revenue: 1000 }]}
        currency="USD"
        decimalPlaces={2}
      />,
    );
    expect(screen.getByText("43659001")).toBeInTheDocument();
    expect(screen.getByText("11000")).toBeInTheDocument();
    expect(screen.getByText("349")).toBeInTheDocument();
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
    expect(screen.queryByText(/US?\$43,659,001/)).not.toBeInTheDocument();
    expect(screen.queryByText("43,659,001")).not.toBeInTheDocument();
  });

  it("StatCard never formats an identifier label as currency", () => {
    render(<StatCard label="SalesOrderLineKey" value={43659001} currency="USD" decimalPlaces={2} />);
    const button = screen.getByText("43.7M"); // abbreviated, but never with a $ prefix
    expect(button).toHaveAttribute("title", "43,659,001");
  });

  it("respects a different currency and decimal-places setting (e.g. NGN, 0 decimals) in the exact value behind the abbreviated display", () => {
    render(<StatCard label="Total Sales" value={69166.61} currency="NGN" decimalPlaces={0} />);
    const button = screen.getByText(/NGN\s*69\.2K/);
    expect(button).toBeInTheDocument();
    expect(button.getAttribute("title")).toMatch(/NGN\s*69,167/);
  });

  it("StatCard clicking an abbreviated value reveals the exact figure, and clicking again collapses it back -- never overflowing the card", () => {
    render(<StatCard label="Total Sales" value={109809274.2} currency="USD" decimalPlaces={2} />);
    const button = screen.getByRole("button", { name: "$109.8M" });
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    expect(screen.getByText("$109,809,274.20")).toBeInTheDocument();
    expect(screen.queryByText("$109.8M")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("$109,809,274.20"));
    expect(screen.getByText("$109.8M")).toBeInTheDocument();
  });

  it("StatCard does not offer to expand a value that already fits (nothing to reveal)", () => {
    render(<StatCard label="Total Orders" value={342} currency="USD" decimalPlaces={2} />);
    const el = screen.getByText("342");
    expect(el.tagName).toBe("BUTTON");
    expect(el).toHaveClass("cursor-default");
    expect(screen.queryByText("Click for exact value")).not.toBeInTheDocument();
  });
});
