import pandas as pd

from app.analysis.insights import generate_insights
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetRecord
from tests.factories import orders_df


def _record(df, name="orders"):
    profile = profile_dataframe(df, name, name, f"{name}.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_top_performer_insight_matches_manual_calculation():
    df = orders_df(20)
    insights = generate_insights(_record(df))
    top = next(i for i in insights if i.category == "top_performer")

    grouped = df.groupby("region")["amount"].sum()
    expected_top_region = grouped.idxmax()
    expected_share = round(grouped.max() / grouped.sum() * 100, 2)

    assert expected_top_region in top.finding
    assert str(expected_share) in top.finding
    assert top.confidence_label == "CALCULATED"


def test_concentration_risk_flagged_when_one_group_dominates():
    df = pd.DataFrame(
        {
            "region": ["North"] * 18 + ["South"] * 2,
            "amount": [100] * 18 + [10] * 2,
        }
    )
    insights = generate_insights(_record(df, "skewed"))
    assert any(i.category == "concentration_risk" for i in insights)


def test_duplicate_row_insight_only_fires_above_threshold():
    df = orders_df(20)
    duped = pd.concat([df] + [df.iloc[[0]]] * 3, ignore_index=True)  # >5% duplicates
    insights = generate_insights(_record(duped, "duped"))
    assert any(i.category == "data_quality" and "duplicate" in i.finding.lower() for i in insights)


def test_no_concentration_insight_when_evenly_distributed():
    df = pd.DataFrame({"region": ["A", "B", "C", "D"] * 5, "amount": [10, 10, 10, 10] * 5})
    insights = generate_insights(_record(df, "even"))
    assert not any(i.category == "concentration_risk" for i in insights)


def test_no_findings_when_no_metric_or_dimension():
    """When a dataset has no usable metric or dimension, generate_insights returns
    an empty list rather than a fake 'Insufficient data' finding card.
    Data-quality / coverage notices are surfaced separately in the UI.
    """
    df = pd.DataFrame({"free_text": [f"note {i}" for i in range(30)]})
    insights = generate_insights(_record(df, "notes"))
    # Must be empty -- no fake finding, no INSUFFICIENT_DATA card
    assert insights == []


def test_no_insufficient_data_finding_in_output():
    """INSUFFICIENT_DATA must never appear as an executive finding card."""
    df = orders_df(20)
    insights = generate_insights(_record(df))
    for insight in insights:
        assert insight.confidence_label != "INSUFFICIENT_DATA", \
            f"Unexpected INSUFFICIENT_DATA finding: {insight.finding!r}"


def test_freshness_warning_fires_for_an_old_dataset():
    # orders_df's dates are all in 2024 -- unconditionally far past the
    # 30-day threshold regardless of when this test runs.
    df = orders_df(20)
    insights = generate_insights(_record(df))
    freshness = [i for i in insights if i.category == "data_quality" and "days old" in i.finding]
    assert len(freshness) == 1
    assert "2024" in freshness[0].finding
    assert freshness[0].confidence_label == "VERIFIED_FROM_DATA"


def test_no_freshness_warning_for_a_dataset_with_no_date_column():
    df = pd.DataFrame({"region": ["North", "South"], "amount": [100, 200]})
    insights = generate_insights(_record(df, "no_dates"))
    assert not any("days old" in i.finding for i in insights)


def test_no_freshness_warning_when_the_newest_record_is_recent():
    import datetime

    recent = pd.Timestamp.now().normalize() - pd.Timedelta(days=2)
    df = pd.DataFrame(
        {
            "date": [(recent - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(20)],
            "region": ["North", "South"] * 10,
            "amount": [100.0 + i for i in range(20)],
        }
    )
    insights = generate_insights(_record(df, "fresh"))
    assert not any("days old" in i.finding for i in insights)


def test_every_insight_carries_evidence_and_calculation():
    df = orders_df(20)
    insights = generate_insights(_record(df))
    for insight in insights:
        assert insight.evidence.description
        assert insight.calculation
        assert insight.interpretation
