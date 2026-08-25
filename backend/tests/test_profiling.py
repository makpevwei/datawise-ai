import pandas as pd

from app.profiling.service import profile_dataframe
from app.profiling.type_inference import infer_column_type
from app.semantic.models import ColumnType, DatasetKind
from tests.factories import customers_df, orders_df


def test_infers_numeric_type():
    col_type, flags = infer_column_type(pd.Series([1, 2, 3, 4, 5]), "amount")
    assert col_type == ColumnType.NUMERIC
    assert flags == []


def test_infers_identifier_type_for_unique_id_named_column():
    col_type, _ = infer_column_type(pd.Series(range(100)), "customer_id")
    assert col_type == ColumnType.IDENTIFIER


def test_low_uniqueness_id_named_column_stays_numeric():
    # A foreign key repeats many times -- it must not be misclassified as an
    # identifier just because of its name.
    col_type, _ = infer_column_type(pd.Series([1, 1, 1, 2, 2, 3] * 20), "product_id")
    assert col_type == ColumnType.NUMERIC


def test_infers_categorical_type():
    col_type, _ = infer_column_type(pd.Series(["North", "South", "North", "East"] * 10), "region")
    assert col_type == ColumnType.CATEGORICAL


def test_infers_date_type():
    dates = pd.Series([f"2024-0{(i % 9) + 1}-01" for i in range(20)])
    col_type, _ = infer_column_type(dates, "order_date")
    assert col_type == ColumnType.DATE


def test_detects_numeric_stored_as_text():
    values = pd.Series([f"{i}.50" for i in range(20)])
    col_type, flags = infer_column_type(values, "price")
    assert col_type == ColumnType.NUMERIC
    assert "numeric_stored_as_text" in flags


def test_dataset_profile_computes_missing_and_duplicate_stats():
    df = orders_df(10)
    df.loc[0, "amount"] = None
    df.loc[1, "amount"] = None
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)  # duplicate a non-null row

    profile = profile_dataframe(df, "id1", "orders", "orders.csv", None, DatasetKind.UPLOADED)

    amount_col = next(c for c in profile.columns if c.name == "amount")
    assert amount_col.missing_count == 2
    assert profile.quality.duplicate_row_count == 1
    assert "amount" not in profile.quality.numeric_stored_as_text_columns


def test_dataset_profile_identifies_column_categories():
    df = customers_df()
    profile = profile_dataframe(df, "id2", "customers", "customers.csv", None, DatasetKind.UPLOADED)
    assert "customer_id" in profile.identifier_columns
    assert "segment" in profile.categorical_columns


def test_quality_rating_degrades_with_many_duplicate_rows():
    df = pd.concat([customers_df()] * 5, ignore_index=True)
    profile = profile_dataframe(df, "id3", "dupes", "dupes.csv", None, DatasetKind.UPLOADED)
    assert profile.quality.overall_rating in ("fair", "poor")
