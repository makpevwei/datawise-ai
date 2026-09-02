import pandas as pd
import pytest

from app.profiling.service import profile_dataframe
from app.relationships.joins import JoinError, JoinSafetyError, perform_join, preview_join
from app.semantic.models import DatasetKind, JoinCardinality, JoinRequest, JoinType
from app.semantic.store import DatasetRecord, DatasetStore
from tests.factories import customers_df, orders_df


@pytest.fixture
def store(tmp_path):
    s = DatasetStore(storage_dir=tmp_path)
    customers = customers_df()
    orders = orders_df(10)
    s.put(
        "customers",
        customers,
        profile_dataframe(customers, "customers", "customers", "customers.csv", None, DatasetKind.UPLOADED),
    )
    s.put(
        "orders",
        orders,
        profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED),
    )
    return s


def test_inner_join_matches_all_rows(store):
    request = JoinRequest(
        left_dataset_id="orders", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
        join_type=JoinType.INNER,
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    assert result.rows_after == 10  # every order's customer_id exists in customers
    assert result.unmatched_left == 0
    assert result.unmatched_right == 3  # 3 customers (6, 7, 8) placed no orders
    assert result.new_dataset.kind == DatasetKind.JOINED


def test_left_join_reports_unmatched_right_side(store):
    orders = orders_df(10)
    orders.loc[0, "customer_id"] = 999  # no matching customer
    store.put(
        "orders2", orders,
        profile_dataframe(orders, "orders2", "orders2", "orders2.csv", None, DatasetKind.UPLOADED),
    )
    request = JoinRequest(
        left_dataset_id="orders2", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
        join_type=JoinType.LEFT,
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    assert result.rows_after == 10
    assert result.unmatched_left == 1


def test_many_to_many_join_is_refused_by_default(store):
    # Phase 4 join safety: a many-to-many join must never be performed
    # silently -- it's refused with a row-multiplication estimate unless
    # the caller explicitly opts in.
    left = pd.DataFrame({"key": [1, 1, 2], "v": ["a", "b", "c"]})
    right = pd.DataFrame({"key": [1, 1, 2], "w": ["x", "y", "z"]})
    store.put("left", left, profile_dataframe(left, "left", "left", "left.csv", None, DatasetKind.UPLOADED))
    store.put("right", right, profile_dataframe(right, "right", "right", "right.csv", None, DatasetKind.UPLOADED))

    request = JoinRequest(left_dataset_id="left", left_column="key", right_dataset_id="right", right_column="key")
    with pytest.raises(JoinSafetyError, match="many-to-many"):
        perform_join(store, request, created_by_user_id="test-user")


def test_many_to_many_join_proceeds_with_explicit_allow_fan_out(store):
    left = pd.DataFrame({"key": [1, 1, 2], "v": ["a", "b", "c"]})
    right = pd.DataFrame({"key": [1, 1, 2], "w": ["x", "y", "z"]})
    store.put("left", left, profile_dataframe(left, "left", "left", "left.csv", None, DatasetKind.UPLOADED))
    store.put("right", right, profile_dataframe(right, "right", "right", "right.csv", None, DatasetKind.UPLOADED))

    request = JoinRequest(
        left_dataset_id="left", left_column="key", right_dataset_id="right", right_column="key", allow_fan_out=True
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    assert result.duplicate_key_warning is True
    assert result.cardinality == JoinCardinality.MANY_TO_MANY
    assert result.estimated_fan_out_rows == 5  # 1x1 (2 rows) + 1x1 (2 rows) + 2x2 (1 row)
    assert result.rows_after == 5


def test_one_to_many_cardinality_is_classified_and_not_blocked(store):
    # orders.customer_id repeats (many orders per customer); customers.customer_id is unique.
    request = JoinRequest(
        left_dataset_id="orders", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    assert result.cardinality == JoinCardinality.MANY_TO_ONE
    assert result.duplicate_key_warning is False
    assert any("many-to-one" in note.lower() for note in result.notes)


def test_matched_both_reflects_the_real_match_count_not_a_naive_row_sum(store):
    # Regression test: matched_both must be the actual number of rows that
    # matched on both sides, not (rows_before_left + rows_before_right -
    # unmatched_left - unmatched_right) -- that naive formula overcounts
    # for a one-to-many join (10 orders vs 8 customers, all orders matched
    # would wrongly suggest 18, not the real 10).
    request = JoinRequest(
        left_dataset_id="orders", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    assert result.matched_both == result.rows_after == 10
    assert result.matched_both != result.rows_before_left + result.rows_before_right


def test_key_overlap_percentage_is_reported(store):
    request = JoinRequest(
        left_dataset_id="orders", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    assert 0.0 < result.key_overlap_percentage <= 100.0


def test_join_raises_for_missing_dataset(store):
    request = JoinRequest(
        left_dataset_id="does-not-exist", left_column="x", right_dataset_id="customers", right_column="customer_id"
    )
    with pytest.raises(JoinError, match="not found"):
        perform_join(store, request, created_by_user_id="test-user")


def test_join_raises_for_missing_column(store):
    request = JoinRequest(
        left_dataset_id="orders", left_column="not_a_column",
        right_dataset_id="customers", right_column="customer_id",
    )
    with pytest.raises(JoinError, match="not found"):
        perform_join(store, request, created_by_user_id="test-user")


def test_full_outer_join_keeps_unmatched_rows_on_both_sides(store):
    orders = orders_df(10)
    orders.loc[0, "customer_id"] = 999  # unmatched on the left
    store.put(
        "orders3", orders,
        profile_dataframe(orders, "orders3", "orders3", "orders3.csv", None, DatasetKind.UPLOADED),
    )
    request = JoinRequest(
        left_dataset_id="orders3", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
        join_type=JoinType.FULL,
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    # 10 orders (1 unmatched) + 3 customers with no orders (6, 7, 8) never dropped.
    assert result.unmatched_left == 1
    assert result.unmatched_right == 3
    assert result.rows_after == 10 + 3


def test_preview_join_computes_stats_without_persisting_anything(store):
    request = JoinRequest(
        left_dataset_id="orders", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
    )
    preview = preview_join(store, request)
    assert preview.rows_after == 10
    assert preview.cardinality == JoinCardinality.MANY_TO_ONE
    # Nothing should have been written to the store by a preview.
    assert store.get("orders") is not None
    assert len(store.all_records()) == 2  # only the two original fixtures -- no new dataset created


def test_join_uses_dataset_name_suffixes_for_colliding_columns(store):
    # Both tables have a 'name'-shaped collision after adding one to orders.
    orders = orders_df(10)
    orders["notes"] = ["n"] * 10
    customers = customers_df()
    customers["notes"] = ["n"] * 8
    store.put("orders4", orders, profile_dataframe(orders, "orders4", "orders", "orders.csv", None, DatasetKind.UPLOADED))
    store.put("customers2", customers, profile_dataframe(customers, "customers2", "customers", "customers.csv", None, DatasetKind.UPLOADED))

    request = JoinRequest(
        left_dataset_id="orders4", left_column="customer_id",
        right_dataset_id="customers2", right_column="customer_id",
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    record = store.get(result.new_dataset_id)
    columns = list(record.dataframe.columns)
    # No column should have been silently dropped/overwritten, and pandas'
    # generic _x/_y suffixes should have been replaced with dataset-name-based
    # ones (a trailing short hash guards against two dataset names that
    # share a long common prefix truncating down to the same suffix --
    # see _column_suffix's own docstring -- so this checks a prefix match,
    # not an exact name).
    assert any(c.startswith("notes_orders_") for c in columns)
    assert any(c.startswith("notes_customers_") for c in columns)
    assert "notes_x" not in columns and "notes_y" not in columns


def test_join_disambiguates_colliding_columns_even_with_a_long_shared_name_prefix(store):
    # Reproduces a real bug found against a multi-sheet workbook upload:
    # two sheets from the same file share the long "{filename} — " prefix
    # in their dataset name (e.g. "NexaSphere_BI_Case_Study_Dataset.xlsx —
    # Fact_Sales" / "... — Dim_Products"), which used to get truncated down
    # to the *same* 30-character suffix -- pandas doesn't error on that, it
    # silently produces a dataframe with a genuinely duplicate column name,
    # which then blew up downstream the moment anything did df[col]
    # expecting a single Series (profile_dataframe's non_null_count, e.g.).
    long_shared_prefix = "A_Very_Long_Workbook_Filename_That_Exceeds_Thirty_Characters.xlsx"
    left_name = f"{long_shared_prefix} — Fact_Sales"
    right_name = f"{long_shared_prefix} — Dim_Products"

    left_df = orders_df(10)
    left_df["shared_metric"] = list(range(10))  # collides with the right side
    right_df = customers_df()
    right_df["shared_metric"] = list(range(len(right_df)))

    store.put("left", left_df, profile_dataframe(left_df, "left", "Fact_Sales", "wb.xlsx", "Fact_Sales", DatasetKind.UPLOADED))
    store.put("right", right_df, profile_dataframe(right_df, "right", "Dim_Products", "wb.xlsx", "Dim_Products", DatasetKind.UPLOADED))
    # profile_dataframe's `name` argument is what _column_suffix actually
    # keys off -- overwrite it directly to reproduce the exact long,
    # shared-prefix names a real multi-sheet upload produces.
    store.get("left").profile.name = left_name
    store.get("right").profile.name = right_name

    request = JoinRequest(
        left_dataset_id="left", left_column="customer_id",
        right_dataset_id="right", right_column="customer_id",
    )
    result = perform_join(store, request, created_by_user_id="test-user")
    record = store.get(result.new_dataset_id)
    columns = list(record.dataframe.columns)
    # The real assertion: no duplicate column names at all -- this is what
    # previously crashed profile_dataframe downstream.
    assert len(columns) == len(set(columns))
    assert any("shared_metric" in c and "fact_sales" in c for c in columns)
    assert any("shared_metric" in c and "dim_products" in c for c in columns)
