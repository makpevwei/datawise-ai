"""Safe data joins.

A join is only ever performed when explicitly requested with an explicit
join type and columns -- nothing here auto-joins. Every join reports rows
before/after, unmatched counts on both sides, and whether duplicate keys
put the join at risk of row multiplication (many-to-many).
"""

import re

import pandas as pd

from app.profiling.service import profile_dataframe
from app.semantic.models import (
    DatasetKind,
    DatasetSummary,
    JoinCardinality,
    JoinLineage,
    JoinPreviewResult,
    JoinRequest,
    JoinResult,
)
from app.semantic.store import DatasetRecord, DatasetStore

_SUFFIX_UNSAFE = re.compile(r"[^a-zA-Z0-9]+")


class JoinError(Exception):
    pass


class JoinSafetyError(JoinError):
    """Raised when a join would silently multiply rows (many-to-many keys
    on both sides) and the caller hasn't explicitly opted in via
    allow_fan_out=True."""


def classify_cardinality(left_col: pd.Series, right_col: pd.Series) -> JoinCardinality:
    left_dup = bool(left_col.duplicated().any())
    right_dup = bool(right_col.duplicated().any())
    if not left_dup and not right_dup:
        return JoinCardinality.ONE_TO_ONE
    if not left_dup and right_dup:
        return JoinCardinality.ONE_TO_MANY
    if left_dup and not right_dup:
        return JoinCardinality.MANY_TO_ONE
    return JoinCardinality.MANY_TO_MANY


def _column_suffix(dataset_name: str) -> str:
    token = _SUFFIX_UNSAFE.sub("_", dataset_name).strip("_").lower()
    return f"_{token[:30]}" if token else "_src"


def _resolve_records(store: DatasetStore, request: JoinRequest) -> tuple[DatasetRecord, DatasetRecord]:
    left = store.get(request.left_dataset_id)
    right = store.get(request.right_dataset_id)
    if left is None:
        raise JoinError(f"Dataset '{request.left_dataset_id}' not found.")
    if right is None:
        raise JoinError(f"Dataset '{request.right_dataset_id}' not found.")
    if request.left_column not in left.dataframe.columns:
        raise JoinError(f"Column '{request.left_column}' not found in '{left.profile.name}'.")
    if request.right_column not in right.dataframe.columns:
        raise JoinError(f"Column '{request.right_column}' not found in '{right.profile.name}'.")
    return left, right


class _JoinComputation:
    """Shared work between the preview (dry-run) and create (persisted)
    paths -- both need the exact same merge, cardinality check, and stats,
    so this exists once instead of being duplicated across two functions."""

    def __init__(self, store: DatasetStore, request: JoinRequest, raise_on_fan_out: bool = True):
        self.left, self.right = _resolve_records(store, request)
        self.request = request
        self.lc, self.rc = request.left_column, request.right_column

        left_df, right_df = self.left.dataframe, self.right.dataframe
        self.cardinality = classify_cardinality(left_df[self.lc], right_df[self.rc])
        self.duplicate_key_warning = self.cardinality == JoinCardinality.MANY_TO_MANY

        left_keys = set(left_df[self.lc].dropna().unique())
        right_keys = set(right_df[self.rc].dropna().unique())
        common_keys = left_keys & right_keys
        smaller_side = min(len(left_keys), len(right_keys)) or 1
        self.key_overlap_percentage = round(len(common_keys) / smaller_side * 100, 2)

        self.estimated_fan_out_rows: int | None = None
        if self.cardinality == JoinCardinality.MANY_TO_MANY:
            left_counts = left_df[self.lc].value_counts()
            right_counts = right_df[self.rc].value_counts()
            self.estimated_fan_out_rows = int(
                sum(int(left_counts.get(k, 0)) * int(right_counts.get(k, 0)) for k in common_keys)
            )
            if raise_on_fan_out and not request.allow_fan_out:
                raise JoinSafetyError(
                    f"Refusing to join '{self.left.profile.name}'.{self.lc} with "
                    f"'{self.right.profile.name}'.{self.rc}: both columns contain duplicate values "
                    f"(many-to-many), which would multiply rows -- an estimated "
                    f"{self.estimated_fan_out_rows} row(s) versus {len(left_df)} ({self.left.profile.name}) "
                    f"and {len(right_df)} ({self.right.profile.name}) today. Key overlap is "
                    f"{self.key_overlap_percentage}%. If this fan-out is actually intended, retry with "
                    "allow_fan_out=true."
                )

        self.notes: list[str] = []
        if self.key_overlap_percentage == 0.0 and left_keys and right_keys:
            left_kind, right_kind = left_df[self.lc].dtype.kind, right_df[self.rc].dtype.kind
            if left_kind != right_kind:
                self.notes.append(
                    f"No overlapping keys were found, and '{self.lc}' ({left_df[self.lc].dtype}) and "
                    f"'{self.rc}' ({right_df[self.rc].dtype}) have different data types -- this may be a "
                    "type mismatch rather than truly unrelated data."
                )
        if self.cardinality == JoinCardinality.ONE_TO_MANY:
            self.notes.append(
                f"This is a one-to-many join: each row in '{self.left.profile.name}' may match multiple "
                f"rows in '{self.right.profile.name}', so the joined dataset can have more rows than "
                f"'{self.left.profile.name}' alone."
            )
        elif self.cardinality == JoinCardinality.MANY_TO_ONE:
            self.notes.append(
                f"This is a many-to-one join: each row in '{self.right.profile.name}' may match multiple "
                f"rows in '{self.left.profile.name}', so the joined dataset can have more rows than "
                f"'{self.right.profile.name}' alone."
            )
        elif self.cardinality == JoinCardinality.MANY_TO_MANY:
            self.notes.append(
                f"Many-to-many join performed with allow_fan_out=true: estimated "
                f"{self.estimated_fan_out_rows} result row(s) from {len(left_df)} x {len(right_df)} "
                "source rows."
            )

        suffixes = (_column_suffix(self.left.profile.name), _column_suffix(self.right.profile.name))
        outer = pd.merge(
            left_df, right_df, left_on=self.lc, right_on=self.rc, how="outer", indicator=True, suffixes=suffixes
        )
        self.matched_both = int((outer["_merge"] == "both").sum())
        self.unmatched_left = int((outer["_merge"] == "left_only").sum())
        self.unmatched_right = int((outer["_merge"] == "right_only").sum())

        if request.join_type.value == "inner":
            keep = outer["_merge"] == "both"
        elif request.join_type.value == "left":
            keep = outer["_merge"].isin(["both", "left_only"])
        elif request.join_type.value == "right":
            keep = outer["_merge"].isin(["both", "right_only"])
        else:  # full outer -- keep every row from both sides
            keep = pd.Series(True, index=outer.index)
        self.result_df = outer.loc[keep].drop(columns="_merge").reset_index(drop=True)

        self.notes.insert(0, f"{self.matched_both} row(s) matched on both sides.")
        if self.unmatched_left:
            self.notes.append(
                f"{self.unmatched_left} row(s) in '{self.left.profile.name}' had no matching "
                f"'{self.rc}' in '{self.right.profile.name}'."
            )
        if self.unmatched_right:
            self.notes.append(
                f"{self.unmatched_right} row(s) in '{self.right.profile.name}' had no matching "
                f"'{self.lc}' in '{self.left.profile.name}'."
            )


def preview_join(store: DatasetStore, request: JoinRequest) -> JoinPreviewResult:
    """Compute the same stats a real join would produce, without persisting
    anything -- used for the "Preview Join" step before the user commits to
    "Create Joined Dataset". Unlike perform_join, a preview never refuses a
    many-to-many pairing -- it reports the row-multiplication warning and
    estimate instead, so the UI can show it *before* asking for
    confirmation (see app/api/relationships.py's /join/preview)."""
    computation = _JoinComputation(store, request, raise_on_fan_out=False)
    return JoinPreviewResult(
        left_dataset_name=computation.left.profile.name,
        left_column=computation.lc,
        right_dataset_name=computation.right.profile.name,
        right_column=computation.rc,
        join_type=request.join_type,
        rows_before_left=len(computation.left.dataframe),
        rows_before_right=len(computation.right.dataframe),
        rows_after=len(computation.result_df),
        matched_both=computation.matched_both,
        unmatched_left=computation.unmatched_left,
        unmatched_right=computation.unmatched_right,
        duplicate_key_warning=computation.duplicate_key_warning,
        cardinality=computation.cardinality,
        key_overlap_percentage=computation.key_overlap_percentage,
        estimated_fan_out_rows=computation.estimated_fan_out_rows,
        notes=computation.notes,
    )


def join_content_hash(request: JoinRequest) -> str:
    """Canonical identity of a join's *inputs*: same source dataset ids
    (which already change per version -- see the dataset-versioning
    system, each version is a distinct row/id) + same keys + same join
    type => the same derived dataset. Used to detect and reuse an
    identical prior join instead of creating a duplicate (spec section 46)."""
    return (
        f"join:{request.left_dataset_id}:{request.left_column}:"
        f"{request.right_dataset_id}:{request.right_column}:{request.join_type.value}"
    )


def perform_join(store: DatasetStore, request: JoinRequest, created_by_user_id: str) -> JoinResult:
    computation = _JoinComputation(store, request)
    left, right = computation.left, computation.right

    new_id = store.new_id()
    result_name = request.result_name or f"{left.profile.name} ⋈ {right.profile.name}"
    profile = profile_dataframe(
        df=computation.result_df,
        dataset_id=new_id,
        name=result_name,
        source_file=f"{left.profile.source_file} + {right.profile.source_file}",
        sheet_name=None,
        kind=DatasetKind.JOINED,
    )
    profile.lineage = JoinLineage(
        parent_dataset_ids=[left.profile.id, right.profile.id],
        left_dataset_id=left.profile.id,
        left_dataset_name=left.profile.name,
        left_column=computation.lc,
        right_dataset_id=right.profile.id,
        right_dataset_name=right.profile.name,
        right_column=computation.rc,
        join_type=request.join_type,
        created_by_user_id=created_by_user_id,
    )
    store.put(new_id, computation.result_df, profile)

    return JoinResult(
        new_dataset_id=new_id,
        new_dataset=DatasetSummary(
            id=profile.id,
            name=profile.name,
            source_file=profile.source_file,
            sheet_name=profile.sheet_name,
            kind=profile.kind,
            row_count=profile.row_count,
            column_count=profile.column_count,
            quality_rating=profile.quality.overall_rating,
            created_at=profile.created_at,
        ),
        left_dataset_id=request.left_dataset_id,
        left_column=computation.lc,
        right_dataset_id=request.right_dataset_id,
        right_column=computation.rc,
        join_type=request.join_type,
        rows_before_left=len(left.dataframe),
        rows_before_right=len(right.dataframe),
        rows_after=len(computation.result_df),
        matched_both=computation.matched_both,
        unmatched_left=computation.unmatched_left,
        unmatched_right=computation.unmatched_right,
        duplicate_key_warning=computation.duplicate_key_warning,
        cardinality=computation.cardinality,
        key_overlap_percentage=computation.key_overlap_percentage,
        estimated_fan_out_rows=computation.estimated_fan_out_rows,
        notes=computation.notes,
    )
