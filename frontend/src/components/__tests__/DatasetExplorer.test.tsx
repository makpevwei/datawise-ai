import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DatasetExplorer } from "../DatasetExplorer";
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
  columns: [
    {
      name: "amount",
      inferred_type: "numeric",
      row_count: 20,
      non_null_count: 20,
      missing_count: 0,
      missing_percentage: 0,
      unique_count: 20,
      is_likely_identifier: false,
      quality_flags: [],
      min: 100,
      max: 300,
      mean: 200,
      median: 200,
      std: 50,
      cardinality: null,
      top_values: null,
      min_date: null,
      max_date: null,
      date_coverage_days: null,
    },
  ],
  numeric_columns: ["amount"],
  categorical_columns: [],
  date_columns: [],
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

describe("DatasetExplorer", () => {
  it("shows an empty state with no datasets", () => {
    render(<DatasetExplorer datasets={[]} />);
    expect(screen.getByText(/no datasets yet/i)).toBeInTheDocument();
  });

  it("lists datasets and shows the profile of the first one by default", async () => {
    vi.spyOn(api, "getDataset").mockResolvedValue(profile);
    vi.spyOn(api, "getDatasetSample").mockResolvedValue([{ amount: 150 }]);

    render(<DatasetExplorer datasets={[summary]} />);

    expect(screen.getByText("orders.csv")).toBeInTheDocument();
    // "amount" appears in both the schema table and the sample table header,
    // so assert on the schema-only numeric summary instead.
    await waitFor(() => expect(screen.getByText(/mean 200/i)).toBeInTheDocument());
    expect(screen.getByText(/sample records/i)).toBeInTheDocument();
  });

  it("shows quality notes when present", async () => {
    vi.spyOn(api, "getDataset").mockResolvedValue({
      ...profile,
      quality: { ...profile.quality, notes: ["3 duplicate rows (15% of rows)."] },
    });
    vi.spyOn(api, "getDatasetSample").mockResolvedValue([]);

    render(<DatasetExplorer datasets={[summary]} />);

    await waitFor(() =>
      expect(screen.getByText(/3 duplicate rows/i)).toBeInTheDocument(),
    );
  });
});
