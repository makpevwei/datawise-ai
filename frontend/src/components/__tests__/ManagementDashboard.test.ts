import { describe, expect, it } from "vitest";
import { rankFindings } from "@/components/ManagementDashboard";
import type { Insight } from "@/lib/types";

function insight(category: Insight["category"], finding: string): Insight {
  return {
    id: finding,
    dataset_id: "d1",
    category,
    finding,
    evidence: { description: "", supporting_values: {} },
    calculation: "",
    interpretation: "",
    confidence_label: "CALCULATED",
  };
}

describe("rankFindings", () => {
  it("ranks a frequency-based concentration_risk finding below an anomaly finding, even when it arrived first", () => {
    // Reproduces the exact bug seen with the AdventureWorks workbook: a
    // sheet with no numeric metric (Sales Order_data) resolved before the
    // sheet with the real business signal (Sales_data), so its bare
    // "50% of records share the same Channel value" frequency stat won the
    // #1 finding slot ahead of a genuine Sales Amount anomaly.
    const channelConcentration = insight("concentration_risk", "50.19% of records share the same 'Channel' value.");
    const salesAnomaly = insight("anomaly", "8.85% of 'Sales Amount' records fall outside the expected range.");

    const ranked = rankFindings([channelConcentration, salesAnomaly]);

    expect(ranked[0]).toBe(salesAnomaly);
    expect(ranked[1]).toBe(channelConcentration);
  });

  it("ranks significant_change and anomaly above top_performer, concentration_risk, and data_quality", () => {
    const dataQuality = insight("data_quality", "dq");
    const concentration = insight("concentration_risk", "cr");
    const topPerformer = insight("top_performer", "tp");
    const anomaly = insight("anomaly", "an");
    const change = insight("significant_change", "sc");

    const ranked = rankFindings([dataQuality, concentration, topPerformer, anomaly, change]);

    expect(ranked.map((i) => i.category)).toEqual([
      "significant_change",
      "anomaly",
      "top_performer",
      "concentration_risk",
      "data_quality",
    ]);
  });

  it("preserves original relative order within the same category (stable sort)", () => {
    const first = insight("anomaly", "first anomaly");
    const second = insight("anomaly", "second anomaly");

    const ranked = rankFindings([first, second]);

    expect(ranked).toEqual([first, second]);
  });

  it("does not mutate the input array", () => {
    const dataQuality = insight("data_quality", "dq");
    const anomaly = insight("anomaly", "an");
    const original = [dataQuality, anomaly];

    rankFindings(original);

    expect(original).toEqual([dataQuality, anomaly]);
  });
});
