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


def test_insufficient_data_insight_when_no_metric_or_dimension():
    df = pd.DataFrame({"free_text": [f"note {i}" for i in range(30)]})
    insights = generate_insights(_record(df, "notes"))
    assert insights[0].finding == "Insufficient data to determine this."
    assert insights[0].confidence_label == "INSUFFICIENT_DATA"


def test_every_insight_carries_evidence_and_calculation():
    df = orders_df(20)
    insights = generate_insights(_record(df))
    for insight in insights:
        assert insight.evidence.description
        assert insight.calculation
        assert insight.interpretation
