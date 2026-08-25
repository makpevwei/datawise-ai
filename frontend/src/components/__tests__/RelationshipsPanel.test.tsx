import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RelationshipsPanel } from "../RelationshipsPanel";
import * as api from "@/lib/api";
import type { DatasetSummary, JoinPreviewResult, JoinResult, RelationshipSuggestion } from "@/lib/types";

function makeDataset(id: string, name: string): DatasetSummary {
  return {
    id,
    name,
    source_file: name,
    sheet_name: null,
    kind: "uploaded",
    row_count: 10,
    column_count: 3,
    quality_rating: "good",
    created_at: new Date().toISOString(),
  };
}

const relationship: RelationshipSuggestion = {
  left_dataset_id: "o1",
  left_dataset_name: "orders.csv",
  left_column: "customer_id",
  right_dataset_id: "c1",
  right_dataset_name: "customers.csv",
  right_column: "customer_id",
  confidence: "HIGH",
  confidence_score: 95,
  cardinality: "many_to_one",
  reasons: [
    "Column names match exactly (after normalizing case/punctuation).",
    "'customers.csv.customer_id' is unique (a likely primary key); 'orders.csv.customer_id' repeats values (a likely foreign key).",
  ],
  value_overlap_percentage: 100,
  left_cardinality: 8,
  right_cardinality: 8,
  suggested_join_type: "inner",
};

const previewResult: JoinPreviewResult = {
  left_dataset_name: "orders.csv",
  left_column: "customer_id",
  right_dataset_name: "customers.csv",
  right_column: "customer_id",
  join_type: "inner",
  rows_before_left: 20,
  rows_before_right: 8,
  rows_after: 20,
  matched_both: 20,
  unmatched_left: 0,
  unmatched_right: 3,
  duplicate_key_warning: false,
  cardinality: "many_to_one",
  key_overlap_percentage: 100,
  estimated_fan_out_rows: null,
  notes: ["20 row(s) matched on both sides."],
};

const joinResult: JoinResult = {
  new_dataset_id: "j1",
  new_dataset: makeDataset("j1", "orders.csv ⋈ customers.csv"),
  reused_existing: false,
  left_dataset_id: "o1",
  left_column: "customer_id",
  right_dataset_id: "c1",
  right_column: "customer_id",
  join_type: "inner",
  rows_before_left: 20,
  rows_before_right: 8,
  rows_after: 20,
  matched_both: 20,
  unmatched_left: 0,
  unmatched_right: 3,
  duplicate_key_warning: false,
  cardinality: "many_to_one",
  key_overlap_percentage: 100,
  estimated_fan_out_rows: null,
  notes: ["20 row(s) matched on both sides."],
};

describe("RelationshipsPanel", () => {
  it("prompts for a second dataset when only one is uploaded", () => {
    render(<RelationshipsPanel datasets={[makeDataset("c1", "customers.csv")]} onJoined={vi.fn()} />);
    expect(screen.getByText(/upload at least two datasets/i)).toBeInTheDocument();
  });

  it("renders suggested relationships with confidence, cardinality, and reasons", async () => {
    vi.spyOn(api, "listRelationships").mockResolvedValue([relationship]);

    render(
      <RelationshipsPanel
        datasets={[makeDataset("c1", "customers.csv"), makeDataset("o1", "orders.csv")]}
        onJoined={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("HIGH CONFIDENCE")).toBeInTheDocument());
    expect(screen.getByText(/column names match exactly/i)).toBeInTheDocument();
    expect(screen.getByText("Many-to-One")).toBeInTheDocument();
  });

  it("requires review, join-type selection, and preview before creating a joined dataset", async () => {
    const onJoined = vi.fn();
    vi.spyOn(api, "listRelationships").mockResolvedValue([relationship]);
    const previewSpy = vi.spyOn(api, "previewJoin").mockResolvedValue(previewResult);
    const joinSpy = vi.spyOn(api, "joinDatasets").mockResolvedValue(joinResult);

    render(
      <RelationshipsPanel
        datasets={[makeDataset("c1", "customers.csv"), makeDataset("o1", "orders.csv")]}
        onJoined={onJoined}
      />,
    );

    const reviewButton = await screen.findByRole("button", { name: /review relationship/i });
    // Joining must not be possible before the user reviews the relationship.
    expect(screen.queryByRole("button", { name: /create joined dataset/i })).not.toBeInTheDocument();
    fireEvent.click(reviewButton);

    expect(screen.getByText(/dataWise found a likely relationship/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /use relationship/i }));

    // Join-type options are shown, defaulting to the backend-suggested type.
    expect(screen.getByText(/how would you like to join these tables/i)).toBeInTheDocument();
    expect(screen.getByText("Inner Join")).toBeInTheDocument();
    expect(screen.getByText("Full Outer Join")).toBeInTheDocument();
    expect(joinSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /preview join/i }));
    await waitFor(() => expect(previewSpy).toHaveBeenCalled());
    expect(await screen.findByText("Expected result rows")).toBeInTheDocument();
    expect(joinSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /create joined dataset/i }));
    await waitFor(() => expect(screen.getByText(/joined as/i)).toBeInTheDocument());
    expect(joinSpy).toHaveBeenCalledWith(
      expect.objectContaining({ left_dataset_id: "o1", right_dataset_id: "c1", join_type: "inner" }),
    );
    expect(onJoined).toHaveBeenCalled();
  });

  it("shows a many-to-many warning from the preview and requires confirmation before creating", async () => {
    vi.spyOn(api, "listRelationships").mockResolvedValue([relationship]);
    vi.spyOn(api, "previewJoin").mockResolvedValue({
      ...previewResult,
      duplicate_key_warning: true,
      cardinality: "many_to_many",
      estimated_fan_out_rows: 500,
    });
    const joinSpy = vi
      .spyOn(api, "joinDatasets")
      .mockRejectedValueOnce(new api.ApiError("many-to-many refused", 409))
      .mockResolvedValueOnce({ ...joinResult, cardinality: "many_to_many" });

    render(
      <RelationshipsPanel
        datasets={[makeDataset("c1", "customers.csv"), makeDataset("o1", "orders.csv")]}
        onJoined={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /review relationship/i }));
    fireEvent.click(screen.getByRole("button", { name: /use relationship/i }));
    fireEvent.click(screen.getByRole("button", { name: /preview join/i }));

    expect(await screen.findByText(/many-to-many join/i)).toBeInTheDocument();
    expect(screen.getByText(/~500 rows/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /create joined dataset/i }));
    expect(await screen.findByText(/this join may multiply rows/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    await waitFor(() => expect(joinSpy).toHaveBeenCalledTimes(2));
    expect(joinSpy).toHaveBeenLastCalledWith(expect.objectContaining({ allow_fan_out: true }));
  });

  it("shows the credible-relationships empty state when none are detected", async () => {
    vi.spyOn(api, "listRelationships").mockResolvedValue([]);

    render(
      <RelationshipsPanel
        datasets={[makeDataset("a1", "a.csv"), makeDataset("b1", "b.csv")]}
        onJoined={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText(/no strong table relationships detected/i)).toBeInTheDocument());
  });
});
