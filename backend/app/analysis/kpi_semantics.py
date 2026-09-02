"""LLM-assisted column classification for KPI discovery.

A fixed keyword list (kpi_discovery.py's own deterministic fallback) can
only ever catch the naming patterns someone thought to write down in
advance -- it correctly excludes a column literally named "Year" or
"CustomerKey", but has no way to recognize an unfamiliar dataset's own
equivalent ("FiscalPeriod", "Wk_No", a column in a language other than
English, ...) as the same kind of thing. The LLM is what makes this
genuinely dataset-agnostic: given nothing but the real column names of
whatever CSV/Excel a user actually uploaded, it classifies each numeric
candidate the same way a human analyst would, no hardcoded vocabulary
required. This is the "brain" this system leans on for any dataset it
hasn't seen a naming convention for before; the deterministic heuristic in
kpi_discovery.py exists only as the always-available fallback when no LLM
is configured or the call fails, not as the primary mechanism.

Two things this module does NOT do, by design: it never produces or
touches the actual computed number (that always comes from
app.analysis.engine.aggregate_scalar() running on the real dataframe --
the "never invents numbers" guarantee holds exactly like every other
LLM-touched surface in this codebase, see app/agent/verification.py), and
it never overrides a business-meaning judgment a column's own name doesn't
already carry (a column named "amount" is not silently reinterpreted as
"revenue").

Best-effort by design: returns an empty classification for every column on
any failure -- no LLM configured, a network/API error, a malformed or
partial response. Callers already have a deterministic fallback for every
column, so KPI discovery must never block, error, or slow down waiting on
this.
"""

import json
from dataclasses import dataclass, field

from app.ai.base import LLMProvider
from app.ai.types import ConversationTurn
from app.semantic.models import Aggregation

_SYSTEM_PROMPT = """You are a business intelligence analyst deciding how numeric spreadsheet columns should be summarized as single headline numbers on an executive dashboard.

For each column, choose exactly one of:
- "sum": a genuinely additive quantity that grows as more records are added -- money moved (revenue, cost, salary paid out, bonus paid out), counts of things (units sold, orders, quantity).
- "mean": a per-entity attribute where adding the values together would be meaningless, but the average is informative -- age, tenure/years at a company, ratings/scores, percentages, rates, prices, or any "how big is a typical X" question about a person, product, or record.
- "exclude": this column should never appear as a headline KPI at all -- neither its sum nor its average means anything as a standalone business number. This covers calendar/date-part numbers (a Year, Month_Number, Week_Number, Day, FiscalPeriod, or similar column that describes *when* something happened, not *how much* of something there was -- "Total Year: 1.5M" and "Average Year: 2024.5" are equally nonsensical), and any other numeric column that is really an identifier, a code, or a label wearing a number's clothes.

When genuinely unsure between "sum" and "mean", prefer "mean" for anything that reads as an attribute of a person/thing (per-entity) rather than a transaction or flow. When unsure whether something is a real business metric at all, prefer "exclude" over guessing.

Respond with ONLY a JSON object mapping each given column name to exactly "sum", "mean", or "exclude" -- no other text, no markdown fences, no explanation."""


@dataclass
class ColumnClassification:
    """aggregations: {column: SUM|MEAN} for columns the LLM gave a usable
    answer for. excluded: columns the LLM said should never be a KPI at
    all (e.g. calendar date-parts) -- kpi_discovery.py drops these from
    candidacy entirely, the same way an identifier column already is."""

    aggregations: dict[str, Aggregation] = field(default_factory=dict)
    excluded: set[str] = field(default_factory=set)


def classify_columns(columns: list[str], provider: LLMProvider | None) -> ColumnClassification:
    """Returns an empty ColumnClassification (no aggregations, nothing
    excluded) for every column on any failure -- the caller's own
    deterministic heuristic covers every column already, this only ever
    refines it, never gates on it."""
    if provider is None or not columns:
        return ColumnClassification()
    prompt = "Columns:\n" + "\n".join(f"- {c}" for c in columns)
    try:
        turn = provider.send(_SYSTEM_PROMPT, [ConversationTurn(role="user", text=prompt)], tools=[])
    except Exception:  # noqa: BLE001 -- any provider/network failure degrades to the deterministic fallback, never raises past KPI discovery
        return ColumnClassification()
    if turn.stop_reason == "error" or not turn.text:
        return ColumnClassification()

    parsed = _parse_json_object(turn.text)
    if not isinstance(parsed, dict):
        return ColumnClassification()

    result = ColumnClassification()
    for column in columns:
        value = parsed.get(column)
        if value == "sum":
            result.aggregations[column] = Aggregation.SUM
        elif value == "mean":
            result.aggregations[column] = Aggregation.MEAN
        elif value == "exclude":
            result.excluded.add(column)
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
