"""Data Relationship Layer -- suggests possible joins between datasets.

Nothing here joins data automatically. Every suggestion carries a
confidence level and an explicit list of reasons so the user can judge
whether to accept it.

Only genuine primary-key / foreign-key-shaped column pairs are suggested.
A shared low-cardinality categorical column (e.g. both datasets have a
"Region" column with overlapping values like "North Africa") is NOT a
relationship on its own -- overlapping values are common for any shared
vocabulary and prove nothing about how the tables relate. The hard
requirement below is that at least one side of a candidate pair actually
behaves like a key in its own table (i.e. its values are close to unique),
which a grouping/category column by definition is not.
"""

import re
from itertools import combinations

import pandas as pd

from app.profiling.type_inference import ID_TOKENS, looks_like_identifier_name, tokenize_column_name
from app.relationships.joins import classify_cardinality
from app.semantic.models import ColumnProfile, ColumnType, ConfidenceLevel, JoinCardinality, RelationshipSuggestion
from app.semantic.store import DatasetRecord

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

MAX_VALUES_FOR_OVERLAP = 200_000
MIN_SCORE_TO_SUGGEST = 45.0
# A column must be within this fraction of fully-unique to count as a
# plausible primary key in its own table. At least one side of a candidate
# pair must clear this bar -- otherwise neither column is actually a key,
# no matter how well the names match or how much the values overlap.
PARENT_UNIQUENESS_THRESHOLD = 0.95
HIGH_NULL_RATE_PENALTY_THRESHOLD = 20.0
# Candidate columns: real identifiers, or anything numeric/categorical/text
# whose *name* reads like a key (product_id, order_no, sku, ...). A plain
# categorical column with no identifier-like name (Region, Segment,
# Category, ...) never qualifies, which is what stops generic categorical
# overlap from being suggested as a relationship.
_NAME_CANDIDATE_TYPES = {ColumnType.NUMERIC, ColumnType.CATEGORICAL, ColumnType.TEXT}


def _is_relationship_candidate(column: ColumnProfile) -> bool:
    if column.inferred_type == ColumnType.IDENTIFIER:
        return True
    return column.inferred_type in _NAME_CANDIDATE_TYPES and looks_like_identifier_name(column.name)


def _stem(name: str) -> str:
    """Business-key stem: tokens with id/code/key/number/... words dropped.

    'product_id', 'product-id', 'ProductID', 'product number', 'product_no'
    and 'product_code' all stem to 'product' so they're recognized as the
    same business key even though their surface spelling differs.
    """
    tokens = [t for t in tokenize_column_name(name) if t not in ID_TOKENS]
    return "".join(tokens)


def _normalize(name: str) -> str:
    return _NON_ALNUM.sub("", name.lower())


def _name_score(a: str, b: str) -> tuple[float, str | None]:
    if _normalize(a) == _normalize(b):
        return 40.0, "Column names match exactly (after normalizing case/punctuation)."
    stem_a, stem_b = _stem(a), _stem(b)
    if stem_a and stem_a == stem_b:
        return 25.0, f"Column names share the same business key ('{stem_a}') once id/code/number-style words are stripped."
    return 0.0, None


def _type_compatible(type_a: ColumnType, type_b: ColumnType) -> bool:
    identifier_like = {ColumnType.IDENTIFIER, ColumnType.NUMERIC}
    if type_a in identifier_like and type_b in identifier_like:
        return True
    if type_a == ColumnType.CATEGORICAL and type_b == ColumnType.CATEGORICAL:
        return True
    if type_a == ColumnType.TEXT and type_b == ColumnType.TEXT:
        return True
    if type_a == ColumnType.IDENTIFIER or type_b == ColumnType.IDENTIFIER:
        return type_a in identifier_like and type_b in identifier_like
    return False


def _uniqueness_ratio(column: ColumnProfile) -> float:
    if column.non_null_count == 0:
        return 0.0
    return column.unique_count / column.non_null_count


def _value_overlap_percentage(series_a: pd.Series, series_b: pd.Series) -> float | None:
    if len(series_a.dropna()) == 0 or len(series_b.dropna()) == 0:
        return None
    unique_a = series_a.dropna().astype(str).unique()
    unique_b = series_b.dropna().astype(str).unique()
    if len(unique_a) > MAX_VALUES_FOR_OVERLAP or len(unique_b) > MAX_VALUES_FOR_OVERLAP:
        return None
    set_a, set_b = set(unique_a), set(unique_b)
    smaller, larger = (set_a, set_b) if len(set_a) <= len(set_b) else (set_b, set_a)
    if not smaller:
        return None
    overlap = len(smaller & larger)
    return round(overlap / len(smaller) * 100, 2)


def _confidence(score: float) -> ConfidenceLevel:
    if score >= 75:
        return ConfidenceLevel.HIGH
    if score >= 55:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _is_self_derived_pair(left: DatasetRecord, right: DatasetRecord) -> bool:
    """True if one dataset was joined directly from the other -- suppresses
    the meaningless "orders-products.csv is related to orders.csv" noise
    a derived dataset would otherwise generate against its own parents
    (they share every original column by construction)."""
    left_parents = set(left.profile.lineage.parent_dataset_ids) if left.profile.lineage else set()
    right_parents = set(right.profile.lineage.parent_dataset_ids) if right.profile.lineage else set()
    return right.profile.id in left_parents or left.profile.id in right_parents


def detect_relationships(records: list[DatasetRecord]) -> list[RelationshipSuggestion]:
    suggestions: list[RelationshipSuggestion] = []

    for left, right in combinations(records, 2):
        if _is_self_derived_pair(left, right):
            continue

        left_candidates = [c for c in left.profile.columns if _is_relationship_candidate(c)]
        right_candidates = [c for c in right.profile.columns if _is_relationship_candidate(c)]

        for lc in left_candidates:
            for rc in right_candidates:
                if not _type_compatible(lc.inferred_type, rc.inferred_type):
                    continue

                # Hard gate: at least one side must actually behave like a
                # primary key in its own table. Two columns that both repeat
                # values (e.g. two "Region" columns) can never pass this,
                # regardless of name or value overlap -- that's what stops
                # generic categorical joins from being suggested.
                left_uniqueness = _uniqueness_ratio(lc)
                right_uniqueness = _uniqueness_ratio(rc)
                if left_uniqueness < PARENT_UNIQUENESS_THRESHOLD and right_uniqueness < PARENT_UNIQUENESS_THRESHOLD:
                    continue

                name_pts, name_reason = _name_score(lc.name, rc.name)

                reasons = [name_reason] if name_reason else []
                reasons.append(
                    f"Both columns hold {lc.inferred_type.value}-compatible values "
                    f"({lc.inferred_type.value} ↔ {rc.inferred_type.value})."
                )

                cardinality = classify_cardinality(left.dataframe[lc.name], right.dataframe[rc.name])
                uniqueness_pts = 0.0
                if cardinality == JoinCardinality.ONE_TO_ONE:
                    uniqueness_pts = 20.0
                    reasons.append(f"'{lc.name}' and '{rc.name}' are both unique in their own table (one-to-one).")
                elif cardinality in (JoinCardinality.ONE_TO_MANY, JoinCardinality.MANY_TO_ONE):
                    uniqueness_pts = 25.0
                    parent_name, parent_col, child_name, child_col = (
                        (left.profile.name, lc.name, right.profile.name, rc.name)
                        if left_uniqueness >= PARENT_UNIQUENESS_THRESHOLD
                        else (right.profile.name, rc.name, left.profile.name, lc.name)
                    )
                    reasons.append(
                        f"'{parent_name}.{parent_col}' is unique (a likely primary key); "
                        f"'{child_name}.{child_col}' repeats values (a likely foreign key)."
                    )

                overlap_pct = _value_overlap_percentage(left.dataframe[lc.name], right.dataframe[rc.name])
                overlap_pts = 0.0
                if overlap_pct is not None:
                    overlap_pts = overlap_pct / 100 * 30
                    reasons.append(
                        f"{overlap_pct}% of the smaller column's distinct values also appear "
                        "in the other column."
                    )
                else:
                    reasons.append(
                        "Value overlap could not be sampled (column too large or empty); "
                        "confidence is based on name, type, and uniqueness only."
                    )

                null_penalty = 0.0
                if lc.missing_percentage > HIGH_NULL_RATE_PENALTY_THRESHOLD or rc.missing_percentage > HIGH_NULL_RATE_PENALTY_THRESHOLD:
                    null_penalty = 10.0
                    reasons.append(
                        f"One side has a high null rate ({max(lc.missing_percentage, rc.missing_percentage)}%), "
                        "which lowers confidence in this key."
                    )

                score = name_pts + uniqueness_pts + overlap_pts - null_penalty
                if score < MIN_SCORE_TO_SUGGEST:
                    continue

                suggestions.append(
                    RelationshipSuggestion(
                        left_dataset_id=left.profile.id,
                        left_dataset_name=left.profile.name,
                        left_column=lc.name,
                        right_dataset_id=right.profile.id,
                        right_dataset_name=right.profile.name,
                        right_column=rc.name,
                        confidence=_confidence(score),
                        confidence_score=round(score, 1),
                        cardinality=cardinality,
                        reasons=reasons,
                        value_overlap_percentage=overlap_pct,
                        left_cardinality=lc.unique_count,
                        right_cardinality=rc.unique_count,
                        suggested_join_type="inner",
                    )
                )

    suggestions.sort(key=lambda s: s.confidence_score, reverse=True)
    return suggestions
