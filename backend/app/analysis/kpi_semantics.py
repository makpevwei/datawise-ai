"""LLM-assisted aggregation-type classification for KPI discovery.

A fixed keyword list (kpi_discovery.py's own deterministic fallback) can't
know that "Age" or "Years at Company" is a per-person attribute that should
be averaged, not summed into a meaningless "Total Age" -- but an LLM
reliably makes that call the same way a human analyst would. This module's
ONLY job is that one classification, per column: SUM or MEAN. It never
produces, sees, or influences the actual numeric value shown on a KPI
card -- that always comes from app.analysis.engine.aggregate_scalar()
running on the real dataframe, exactly the same deterministic function the
keyword-heuristic path already uses. So this preserves the "never invents
numbers" guarantee the same way every other LLM-touched surface in this
codebase does (see app/agent/verification.py): the LLM chooses which
arithmetic operation is meaningful, pandas does the arithmetic.

Best-effort by design: returns {} (an empty mapping) for every column on
any failure -- no LLM configured, a network/API error, a malformed or
partial response. Callers already have a deterministic fallback for every
column (see kpi_discovery._choose_aggregation), so KPI discovery must
never block, error, or slow down waiting on this.
"""

import json

from app.ai.base import LLMProvider
from app.ai.types import ConversationTurn
from app.semantic.models import Aggregation

_SYSTEM_PROMPT = """You are a business intelligence analyst choosing how to summarize numeric spreadsheet columns as single headline numbers on an executive dashboard.

For each column, decide whether SUM or MEAN (average) is the meaningful, non-misleading way to summarize it across every row.

Guidance:
- SUM fits genuinely additive quantities that grow as more records are added: money moved (revenue, cost, salary paid out, bonus paid out), counts of things (units sold, orders, quantity).
- MEAN fits per-entity attributes where adding them together produces a meaningless number: age, tenure/years at a company, ratings/scores, percentages, rates, prices, or any "how big is a typical X" question about a person, product, or record.
- When genuinely unsure, prefer MEAN for anything that reads as an attribute of a person/thing (per-entity) rather than a transaction or flow.

Respond with ONLY a JSON object mapping each given column name to exactly "sum" or "mean" -- no other text, no markdown fences, no explanation."""


def classify_aggregations(columns: list[str], provider: LLMProvider | None) -> dict[str, Aggregation]:
    """Returns a {column: Aggregation.SUM | Aggregation.MEAN} mapping for
    as many of `columns` as the LLM classified with a valid answer -- a
    column missing from the result (including every column, if this
    returns {} entirely) simply falls back to the caller's own
    deterministic heuristic."""
    if provider is None or not columns:
        return {}
    prompt = "Columns:\n" + "\n".join(f"- {c}" for c in columns)
    try:
        turn = provider.send(_SYSTEM_PROMPT, [ConversationTurn(role="user", text=prompt)], tools=[])
    except Exception:  # noqa: BLE001 -- any provider/network failure degrades to the deterministic fallback, never raises past KPI discovery
        return {}
    if turn.stop_reason == "error" or not turn.text:
        return {}

    parsed = _parse_json_object(turn.text)
    if not isinstance(parsed, dict):
        return {}

    result: dict[str, Aggregation] = {}
    for column in columns:
        value = parsed.get(column)
        if value == "sum":
            result[column] = Aggregation.SUM
        elif value == "mean":
            result[column] = Aggregation.MEAN
        # Anything else (missing, misspelled, an unexpected value) is left
        # out on purpose -- the caller's deterministic heuristic covers it.
    return result


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
