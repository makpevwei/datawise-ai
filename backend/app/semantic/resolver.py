"""Deterministic natural-language-concept -> column resolution.

The agent's tools (app/agent/tools.py) receive column names as free-text
arguments (metric_column, dimension_column, ...) picked by the LLM from the
question. Unlike aggregation or chart_type, column names are open
vocabulary -- there's no enum to force an exact real name onto -- so a
request for "product" or "prodcut" against a dataset that actually has
'product_name' (and, separately, an unrelated 'product_id') should resolve
to the right column without a failed tool call and a wasted retry
round-trip.

This is a scoring layer, not a new engine: it reuses the same
tokenization/identifier-detection primitives app/relationships/service.py
already uses for join-key matching (app/profiling/type_inference.py), and
runs entirely offline and deterministically -- no LLM call, no new
dependency (typo tolerance uses the stdlib difflib).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

from app.profiling.type_inference import ID_TOKENS, tokenize_column_name
from app.semantic.models import ColumnProfile, ColumnType, DatasetProfile

Role = Literal["dimension", "measure", "date", "any"]

# Common business-analytics synonym groups. Deliberately small -- this only
# needs to cover pairs that share no text stem at all (e.g. "revenue" and
# "sales" share no letters, so no amount of token/fuzzy matching below would
# ever connect them on its own). Everything else is handled by token overlap
# plus typo-tolerant fuzzy matching.
_SYNONYM_GROUPS: list[set[str]] = [
    {"sales", "sale", "revenue", "income", "turnover"},
    {"cost", "expense", "expenses", "spend", "spending"},
    {"quantity", "qty", "units", "unit", "volume"},
    {"product", "item", "sku"},
    {"customer", "client", "account"},
    {"region", "territory", "area", "zone"},
    {"category", "group", "class", "segment"},
    {"profit", "margin", "earnings"},
    # A bare "rate" is too ambiguous to treat as a price synonym. In
    # particular, it can turn an unsupported "return rate" question into
    # an unrelated numeric risk/price field, which is worse than asking for
    # the missing return indicator.
    {"discount", "markdown"},
]
_SYNONYM_OF: dict[str, set[str]] = {}
for _group in _SYNONYM_GROUPS:
    for _word in _group:
        _SYNONYM_OF[_word] = _group

# Aggregation-verb tokens that describe the operation, not the column concept
# -- e.g. in "average sales", "average" must not compete for column-name
# matching against "sales".
_AGGREGATION_WORDS = {
    "total", "sum", "average", "avg", "mean", "minimum", "min", "maximum",
    "max", "median", "count", "distinct",
}

# difflib.SequenceMatcher.ratio() below this is treated as "a different
# word", not a typo of the concept.
_FUZZY_MATCH_FLOOR = 0.72
MIN_CONFIDENCE_TO_AUTO_RESOLVE = 35.0
# Below-threshold candidates still worth surfacing as "did you mean" hints.
_MIN_SCORE_FOR_HINT = 1.0


@dataclass
class ColumnMatch:
    """Always returned (never bare None) so callers can inspect why a
    concept didn't resolve. `resolved` is the thing to branch on; `column`
    is only meaningful when `resolved` is True."""

    column: str | None
    resolved: bool
    confidence: float = 0.0
    note: str | None = None
    alternatives: list[str] = field(default_factory=list)


def _unresolved(alternatives: list[str] | None = None) -> ColumnMatch:
    return ColumnMatch(column=None, resolved=False, confidence=0.0, note=None, alternatives=alternatives or [])


def _role_incompatible(column_type: ColumnType, role: Role) -> bool:
    """Hard type gate for an exact name match -- a column named exactly
    'region' still isn't a valid measure just because its name was typed
    verbatim. (The fuzzy/token-scoring path below applies the equivalent
    exclusion via _role_bonus's large negative penalties; this mirrors it
    for the exact-match shortcut so role gating is consistent either way.)
    """
    if role == "measure":
        return column_type != ColumnType.NUMERIC
    if role == "date":
        return column_type != ColumnType.DATE
    return False


def _normalize_tokens(text: str) -> list[str]:
    return [t for t in tokenize_column_name(text) if t not in _AGGREGATION_WORDS]


def _token_score(concept_tokens: list[str], column_tokens: list[str]) -> float:
    if not concept_tokens or not column_tokens:
        return 0.0
    column_set = set(column_tokens)
    matched = 0
    for token in set(concept_tokens):
        if token in column_set:
            matched += 1
            continue
        if token in _SYNONYM_OF and _SYNONYM_OF[token] & column_set:
            matched += 1
            continue
        if difflib.get_close_matches(token, column_set, n=1, cutoff=_FUZZY_MATCH_FLOOR):
            matched += 1
    return matched / len(set(concept_tokens))


def _role_bonus(column: ColumnProfile, role: Role, wants_identifier: bool) -> float:
    if role == "measure":
        if column.inferred_type == ColumnType.NUMERIC:
            return 15.0
        if column.inferred_type == ColumnType.IDENTIFIER:
            return -50.0  # an identifier is never a measure, however well the name matches
        return -60.0  # categorical/text/date/etc. are never measures either
    if role == "dimension":
        if column.inferred_type == ColumnType.IDENTIFIER:
            return 15.0 if wants_identifier else -25.0
        if column.inferred_type in (ColumnType.CATEGORICAL, ColumnType.TEXT, ColumnType.BOOLEAN):
            return 15.0
        if column.inferred_type == ColumnType.DATE:
            return -10.0  # a real date grouping should go through role="date"
        return 0.0
    if role == "date":
        return 15.0 if column.inferred_type == ColumnType.DATE else -50.0
    return 0.0


def resolve_column(concept: str | None, profile: DatasetProfile, role: Role = "any") -> ColumnMatch:
    """Best-effort match of a free-text concept (e.g. "product", "sales
    amount", "prodcut") onto one of `profile`'s real columns.

    Always returns a ColumnMatch; check `.resolved` before trusting
    `.column`. Never fabricates a column -- when nothing scores high enough,
    `.resolved` is False and `.alternatives` carries the closest (but not
    trustworthy) candidates for an error message or clarifying question.
    """
    if not concept or not concept.strip() or not profile.columns:
        return _unresolved()

    stripped = concept.strip()
    for column in profile.columns:
        if column.name == stripped or column.name.lower() == stripped.lower():
            if _role_incompatible(column.inferred_type, role):
                break  # fall through to scoring, which will correctly exclude it too
            return ColumnMatch(column=column.name, resolved=True, confidence=100.0)

    concept_tokens = _normalize_tokens(concept)
    if not concept_tokens:
        return _unresolved()
    wants_identifier = any(t in ID_TOKENS for t in tokenize_column_name(concept))

    scored: list[tuple[float, ColumnProfile]] = []
    for column in profile.columns:
        column_tokens = tokenize_column_name(column.name)
        # Fuzzy matching is useful for harmless typos, but must not bridge
        # distinct business domains. For example, the "rate" in "return
        # rate" is close to "late", which could otherwise misroute a
        # missing return metric to late_delivery_risk.
        col_set = set(column_tokens)
        concept_set = set(concept_tokens)
        if "return" in concept_tokens and not ({"return", "returns", "refund", "refunded"} & col_set):
            continue
        if ({"marketing", "roi", "campaign", "adspend"} & concept_set) and not ({"marketing", "roi", "campaign", "adspend", "ad_spend", "promotion", "promotions"} & col_set):
            continue
        if ({"stockout", "inventory", "backorder"} & concept_set) and not ({"stock", "stockout", "inventory", "warehouse", "backorder"} & col_set):
            continue
        if ({"partner", "carrier", "courier"} & concept_set) and not ({"partner", "carrier", "courier", "transporter"} & col_set):
            continue
        if ({"employee", "staff"} & concept_set) and ({"revenue", "profit", "profitability", "sales"} & concept_set) and not ({"employee", "staff", "rep", "agent", "seller"} & col_set):
            continue
        if ({"target", "attainment", "quota"} & concept_set) and not ({"target", "attainment", "quota", "goal"} & col_set):
            continue
        token_score = _token_score(concept_tokens, column_tokens)
        if token_score == 0.0:
            continue
        scored.append((token_score * 70.0 + _role_bonus(column, role, wants_identifier), column))

    if not scored:
        return _unresolved()

    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best_column = scored[0]
    if best_score < MIN_CONFIDENCE_TO_AUTO_RESOLVE:
        hints = [c.name for score, c in scored if score >= _MIN_SCORE_FOR_HINT][:3]
        return _unresolved(hints)

    alternatives = [c.name for score, c in scored[1:3] if score >= _MIN_SCORE_FOR_HINT]
    return ColumnMatch(
        column=best_column.name,
        resolved=True,
        confidence=round(min(best_score, 99.0), 1),
        note=f"interpreted '{stripped}' as '{best_column.name}'",
        alternatives=alternatives,
    )
