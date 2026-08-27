"""Tests for the deterministic default-dashboard chart selection.

discover_dashboard_charts() is what makes the Management Dashboard feel like
an automated analyst: given nothing but an uploaded dataset, it should surface
a trend chart, a comparison chart, and a composition chart on its own -- no
user interaction required (spec: "Required Chart 1 -- trend", "Required Chart
2 -- comparison", "Optional Chart 3 -- composition").
"""

import pandas as pd
import pytest

from app.analysis.dashboard_charts import discover_cross_dataset_charts, discover_dashboard_charts
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetRecord, DatasetStore
from tests.factories import customers_df, orders_df


def _record(df: pd.DataFrame, name: str = "orders") -> DatasetRecord:
    profile = profile_dataframe(df, name, name, f"{name}.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(profile=profile, dataframe=df)


@pytest.fixture
def two_dimension_df() -> pd.DataFrame:
    """A dataset shaped like a real orders export: a date + metric for trend,
    plus TWO distinct low/medium-cardinality dimensions (region, shipping_mode)
    so both a comparison chart and a genuinely different composition chart are
    possible -- the exact shape that exposed the "only 2 charts ever" bug."""
    regions = ["North", "South", "East", "West"]
    modes = ["Standard", "Express", "Same Day"]
    n = 60
    return pd.DataFrame(
        {
            "order_id": list(range(1, n + 1)),
            "date": [f"2024-{(i % 6) + 1:02d}-15" for i in range(1, n + 1)],
            "amount": [100.0 + i * 10 for i in range(1, n + 1)],
            "region": [regions[i % 4] for i in range(1, n + 1)],
            "shipping_mode": [modes[i % 3] for i in range(1, n + 1)],
        }
    )


def test_produces_trend_comparison_and_composition_together(two_dimension_df):
    # Regression test for the exact bug found via live QA: the composition
    # (3rd) chart only ever ran when discover_dashboard_charts had found
    # FEWER than 2 charts so far, so a dataset where both trend and
    # comparison succeed (the common, healthy case) never got its 3rd chart
    # even though a genuinely different second dimension was available.
    charts = discover_dashboard_charts(_record(two_dimension_df))

    assert len(charts) == 3
    types = [c.chart_type.value for c in charts]
    assert types[0] in ("line", "time_series")  # trend always first
    assert "donut" in types or "pie" in types  # composition chart present


def test_composition_chart_uses_a_different_dimension_than_the_comparison_chart(two_dimension_df):
    charts = discover_dashboard_charts(_record(two_dimension_df))
    comparison = next(c for c in charts if c.chart_type.value in ("bar", "ranking", "grouped_bar", "stacked_bar"))
    composition = next(c for c in charts if c.chart_type.value in ("donut", "pie"))
    assert comparison.x_column != composition.x_column


def test_single_dimension_dataset_produces_two_charts_not_a_redundant_third():
    # orders_df's factory has exactly one real dimension (region) -- with no
    # second distinct dimension available, there is nothing honest to plot
    # for a 3rd chart, so it must not fabricate one by reusing "region" twice.
    charts = discover_dashboard_charts(_record(orders_df(20)))
    assert len(charts) == 2
    dims_used = {c.x_column for c in charts if c.chart_type.value not in ("line", "time_series")}
    assert len(dims_used) <= 1


def test_no_identifier_ever_becomes_a_chart_dimension_or_measure(two_dimension_df):
    charts = discover_dashboard_charts(_record(two_dimension_df))
    identifier_like = {"order_id"}
    for c in charts:
        assert c.x_column not in identifier_like
        assert c.y_column not in identifier_like
        for row in c.data or []:
            assert "order_id" not in row


def test_every_chart_carries_source_lineage(two_dimension_df):
    charts = discover_dashboard_charts(_record(two_dimension_df, name="orders_export"))
    for c in charts:
        assert c.dataset_name == "orders_export"
        assert c.title  # never a blank/generic title


def test_numeric_only_dataset_falls_back_to_kpi_cards():
    df = pd.DataFrame({"transaction_id": range(1, 30), "amount": [50.0 + i for i in range(29)]})
    charts = discover_dashboard_charts(_record(df, name="transactions"))
    assert all(c.chart_type.value == "kpi_card" for c in charts)
    assert len(charts) >= 1


def test_dataset_with_no_eligible_metric_produces_no_charts():
    df = pd.DataFrame({"id": range(1, 10), "category": ["A", "B"] * 4 + ["A"]})
    charts = discover_dashboard_charts(_record(df, name="categories_only"))
    assert charts == []


class TestDiscoverCrossDatasetCharts:
    """orders_df (amount, only "region" as its own dimension) and
    customers_df (segment -- a genuinely useful dimension NOT present in
    orders) are a real many-to-one pair via customer_id -- the exact
    fact-table/dimension-table shape a star schema has, e.g. AdventureWorks'
    Sales_data (a SalesTerritoryKey with no native Region column) joined to
    its Sales Territory_data dimension table."""

    @pytest.fixture
    def store(self, tmp_path) -> DatasetStore:
        s = DatasetStore(storage_dir=tmp_path)
        orders, customers = orders_df(20), customers_df()
        s.put("orders", orders, profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
        s.put(
            "customers", customers,
            profile_dataframe(customers, "customers", "customers", "customers.csv", None, DatasetKind.UPLOADED),
        )
        return s

    def test_joins_related_datasets_and_surfaces_a_chart_neither_table_could_produce_alone(self, store):
        records = [store.get("orders"), store.get("customers")]
        charts = discover_cross_dataset_charts(records, store)

        assert len(charts) > 0
        # A real join happened (not just re-discovering orders/customers'
        # own charts): the derived dataset combines both tables' columns,
        # so a chart's dimension can legitimately come from either side --
        # e.g. "amount by segment" (segment only exists in customers) or a
        # richer "amount by region" now backed by the joined row set.
        joined = [r for r in store.all_records() if r.profile.kind.value == "joined"]
        assert len(joined) == 1
        assert set(orders_df(20).columns) < set(joined[0].dataframe.columns)
        assert set(customers_df().columns) < set(joined[0].dataframe.columns)

    def test_calling_it_twice_reuses_the_same_derived_dataset_instead_of_duplicating_it(self, store):
        records = [store.get("orders"), store.get("customers")]
        discover_cross_dataset_charts(records, store)
        derived_after_first_call = [s for s in store.list_summaries() if s.kind.value == "joined"]

        discover_cross_dataset_charts(records, store)
        derived_after_second_call = [s for s in store.list_summaries() if s.kind.value == "joined"]

        assert len(derived_after_first_call) == 1
        assert len(derived_after_second_call) == 1  # not 2 -- perform_join's own dedup kicked in

    def test_unrelated_datasets_produce_no_forced_join(self, tmp_path):
        # Two tables with no plausible shared key -- must not be joined just
        # because they happen to both be selected together.
        unrelated_a = pd.DataFrame({"category": ["A", "B", "C", "D", "E", "F"], "count": [1, 2, 3, 4, 5, 6]})
        unrelated_b = pd.DataFrame({"label": ["X", "Y", "Z", "W", "V", "U"], "score": [10, 20, 30, 40, 50, 60]})
        store = DatasetStore(storage_dir=tmp_path)
        store.put("a", unrelated_a, profile_dataframe(unrelated_a, "a", "a", "a.csv", None, DatasetKind.UPLOADED))
        store.put("b", unrelated_b, profile_dataframe(unrelated_b, "b", "b", "b.csv", None, DatasetKind.UPLOADED))

        charts = discover_cross_dataset_charts([store.get("a"), store.get("b")], store)

        assert charts == []
        assert [s for s in store.list_summaries() if s.kind.value == "joined"] == []

    def test_a_single_dataset_never_attempts_a_join(self, tmp_path):
        store = DatasetStore(storage_dir=tmp_path)
        df = orders_df(20)
        store.put("orders", df, profile_dataframe(df, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))
        assert discover_cross_dataset_charts([store.get("orders")], store) == []
