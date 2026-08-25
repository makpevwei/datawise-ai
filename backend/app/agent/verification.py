"""Verification engine: cross-checks claimed evidence labels against what
tool calls actually returned this session.

The LLM proposes a label (VERIFIED_FROM_DATA / CALCULATED / ...) for each
claim it makes; this module never trusts that label blindly. A numeric
claim's label can only be *confirmed* or *downgraded* to AI_INTERPRETATION
here -- it is never upgraded. This is the concrete mechanism behind "never
convert AI interpretation into a verified fact."
"""

import re

from app.agent.schemas import EvidenceLabel, ToolInvocation

# Negative lookbehind excludes digits glued to a preceding letter (e.g. the
# "2" in "Q2" or "H1") -- those are period labels, not numeric claims.
_NUMBER_RE = re.compile(r"(?<![A-Za-z])-?\d[\d,]*\.?\d*%?")

NUMERIC_LABELS = (EvidenceLabel.VERIFIED_FROM_DATA, EvidenceLabel.CALCULATED, EvidenceLabel.DERIVED)


def extract_numbers(text: str) -> list[float]:
    numbers: list[float] = []
    for match in _NUMBER_RE.findall(text):
        cleaned = match.replace(",", "").rstrip("%")
        if not cleaned or cleaned in ("-", "."):
            continue
        try:
            numbers.append(float(cleaned))
        except ValueError:
            continue
    return numbers


def _numbers_from_tool_outputs(tool_invocations: list[ToolInvocation]) -> set[float]:
    pool: set[float] = set()
    for inv in tool_invocations:
        if not inv.succeeded:
            continue
        pool.update(round(n, 2) for n in extract_numbers(inv.output_summary))
    return pool


def _approx_in(value: float, pool: set[float]) -> bool:
    # Compared on magnitude, not sign: natural language expresses a decline
    # as "fell 14.2%" (a positive number) while calculated evidence often
    # carries a signed delta ("-14.2"). This check only confirms a matching
    # number exists in evidence -- it does not verify stated direction.
    tolerance = max(0.5, abs(value) * 0.02)
    return any(abs(abs(value) - abs(candidate)) <= tolerance for candidate in pool)


def verify_finding_label(
    text: str, claimed_label: EvidenceLabel, tool_invocations: list[ToolInvocation]
) -> tuple[EvidenceLabel, str | None]:
    """Returns (final_label, downgrade_note). Only ever downgrades."""
    if claimed_label not in NUMERIC_LABELS:
        return claimed_label, None

    claim_numbers = [round(n, 2) for n in extract_numbers(text)]
    if not claim_numbers:
        # No numeric assertion to mechanically check; a non-numeric factual
        # claim about the data is left as the LLM labelled it.
        return claimed_label, None

    evidence_numbers = _numbers_from_tool_outputs(tool_invocations)
    if all(_approx_in(n, evidence_numbers) for n in claim_numbers):
        return claimed_label, None

    return (
        EvidenceLabel.AI_INTERPRETATION,
        f"Downgraded from {claimed_label.value}: at least one number in this claim does not "
        "match any tool result from this session.",
    )


def verify_document_grounding(
    text: str, citation_excerpts: list[str]
) -> tuple[bool, str | None]:
    """Checks a DOCUMENT_EVIDENCE claim actually overlaps a cited excerpt.

    Cheap lexical-overlap check (shared significant words), not full NLI --
    enough to catch a citation that was fabricated or misattributed.
    """
    if not citation_excerpts:
        return False, "No citation was attached to this document-grounded claim."

    claim_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text)}
    if not claim_words:
        return True, None

    for excerpt in citation_excerpts:
        excerpt_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", excerpt)}
        overlap = claim_words & excerpt_words
        if len(overlap) >= min(3, len(claim_words)):
            return True, None

    return False, "The cited excerpt does not share enough wording with the claim to confirm grounding."


def verify_claim_comparison(
    data_finding_text: str | None, tool_invocations: list[ToolInvocation]
) -> tuple[bool, str | None]:
    """For a cross-data/document ClaimComparison: confirms the data_finding
    side actually traces back to a real tool result before trusting a
    SUPPORTED_BY_DATA / CONTRADICTED_BY_DATA verdict.
    """
    if not data_finding_text:
        return False, "No data finding was cited for this comparison."
    numbers = [round(n, 2) for n in extract_numbers(data_finding_text)]
    if not numbers:
        return True, None
    evidence_numbers = _numbers_from_tool_outputs(tool_invocations)
    if all(_approx_in(n, evidence_numbers) for n in numbers):
        return True, None
    return False, "The cited data finding's numbers do not match any tool result from this session."
