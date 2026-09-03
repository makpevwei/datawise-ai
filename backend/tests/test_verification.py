from app.agent.schemas import EvidenceLabel, ToolInvocation
from app.agent.verification import (
    extract_numbers,
    verify_claim_comparison,
    verify_document_grounding,
    verify_finding_label,
)


def _invocation(output_summary: str, succeeded: bool = True) -> ToolInvocation:
    return ToolInvocation(id="t1", tool_name="calculate_metric", input={}, output_summary=output_summary, succeeded=succeeded, duration_ms=1)


def _search_invocation(output_summary: str, succeeded: bool = True) -> ToolInvocation:
    return ToolInvocation(id="t1", tool_name="search_documents", input={}, output_summary=output_summary, succeeded=succeeded, duration_ms=1)


def test_extract_numbers_handles_percentages_and_commas():
    assert extract_numbers("Revenue fell 14.2% to $1,234.56") == [14.2, 1234.56]


def test_confirms_matching_calculated_claim():
    label, note = verify_finding_label(
        "Revenue fell 14.2%.", EvidenceLabel.CALCULATED, [_invocation('{"percentage_change": -14.2}')]
    )
    assert label == EvidenceLabel.CALCULATED
    assert note is None


def test_downgrades_unsupported_calculated_claim():
    label, note = verify_finding_label(
        "Revenue fell 90%.", EvidenceLabel.CALCULATED, [_invocation('{"percentage_change": -14.2}')]
    )
    assert label == EvidenceLabel.AI_INTERPRETATION
    assert note is not None


def test_never_upgrades_ai_interpretation():
    # A claimed AI_INTERPRETATION label is left alone even if a matching
    # number exists -- the verifier only ever downgrades.
    label, note = verify_finding_label(
        "This suggests demand weakened by roughly 14.2%.",
        EvidenceLabel.AI_INTERPRETATION,
        [_invocation('{"percentage_change": -14.2}')],
    )
    assert label == EvidenceLabel.AI_INTERPRETATION
    assert note is None


def test_non_numeric_claim_is_not_downgraded():
    label, note = verify_finding_label(
        "The West region uses a different shipping provider.",
        EvidenceLabel.CALCULATED,
        [],
    )
    assert label == EvidenceLabel.CALCULATED
    assert note is None


def test_failed_tool_calls_are_not_counted_as_evidence():
    label, _note = verify_finding_label(
        "Revenue fell 14.2%.", EvidenceLabel.CALCULATED, [_invocation('{"percentage_change": -14.2}', succeeded=False)]
    )
    assert label == EvidenceLabel.AI_INTERPRETATION


def test_document_search_output_is_not_treated_as_numeric_evidence():
    # Found live: a fabricated number ("GPT-4 scored 88.0% on the MMLU
    # benchmark") got labelled VERIFIED_FROM_DATA and survived
    # verification because a real search_documents call that turn
    # happened to retrieve a genuinely unrelated passage containing some
    # other number within the 2% tolerance. search_documents' output is
    # raw retrieved text, not a deterministic computed result -- unlike
    # calculate_metric's, it must never count as numeric evidence for an
    # unrelated claim, no matter how numerically close.
    label, note = verify_finding_label(
        "GPT-4 scored 88.0% on the MMLU benchmark.",
        EvidenceLabel.VERIFIED_FROM_DATA,
        [_search_invocation('{"results": [{"chunk": {"text": "an unrelated passage that happens to mention 88 somewhere"}}]}')],
    )
    assert label == EvidenceLabel.AI_INTERPRETATION
    assert note is not None


def test_document_grounding_confirmed_with_overlapping_excerpt():
    grounded, note = verify_document_grounding(
        "Management attributes the decline to a supply disruption.",
        ["Management attributes the revenue decline to an ongoing supply disruption in the region."],
    )
    assert grounded is True
    assert note is None


def test_document_grounding_rejected_with_no_citation():
    grounded, note = verify_document_grounding("Management attributes the decline to a supply disruption.", [])
    assert grounded is False
    assert "No citation" in note


def test_document_grounding_rejected_with_unrelated_excerpt():
    grounded, _note = verify_document_grounding(
        "Management attributes the decline to a supply disruption.",
        ["Employee headcount grew across all departments this year."],
    )
    assert grounded is False


def test_claim_comparison_confirmed_when_numbers_match():
    ok, _note = verify_claim_comparison("Revenue fell 14.2% in Q2.", [_invocation('{"percentage_change": -14.2}')])
    assert ok is True


def test_claim_comparison_rejected_when_numbers_do_not_match():
    ok, note = verify_claim_comparison("Revenue fell 60% in Q2.", [_invocation('{"percentage_change": -14.2}')])
    assert ok is False
    assert note is not None


def test_claim_comparison_rejected_with_no_data_finding():
    ok, _note = verify_claim_comparison(None, [])
    assert ok is False
