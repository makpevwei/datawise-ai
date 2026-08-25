"""Phase 4 continuation section 25: the Dimension selector was too
restrictive because DatasetProfile never exposed TEXT-typed columns (e.g.
near-unique product names) at all -- not even mislabeled, just dropped.
Confirms the new text_columns bucket exists and is populated correctly,
alongside identifier_columns, which the frontend now also includes.
"""

import pandas as pd

from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind


def test_near_unique_text_column_is_classified_as_text_and_exposed():
    df = pd.DataFrame(
        {
            "product_id": range(1, 61),
            "product_name": [f"Widget Model {i}-Deluxe Edition" for i in range(1, 61)],
            "product_category_name": (["Electronics", "Footwear", "Home", "Sports"] * 15),
        }
    )
    profile = profile_dataframe(
        df=df, dataset_id="ds1", name="products.csv", source_file="products.csv",
        sheet_name=None, kind=DatasetKind.UPLOADED,
    )

    assert "product_name" in profile.text_columns
    assert "product_id" in profile.identifier_columns
    assert "product_category_name" in profile.categorical_columns
    # A column classified as text must not also appear as categorical/numeric.
    assert "product_name" not in profile.categorical_columns
    assert "product_name" not in profile.numeric_columns


def test_text_columns_defaults_to_empty_list_when_none_present():
    df = pd.DataFrame({"amount": [1.0, 2.0, 3.0], "region": ["North", "South", "East"]})
    profile = profile_dataframe(
        df=df, dataset_id="ds2", name="orders.csv", source_file="orders.csv",
        sheet_name=None, kind=DatasetKind.UPLOADED,
    )
    assert profile.text_columns == []


def test_dataset_profile_round_trips_text_columns_through_json():
    df = pd.DataFrame({"description": [f"Item description number {i} with extra detail text" for i in range(30)]})
    profile = profile_dataframe(
        df=df, dataset_id="ds3", name="items.csv", source_file="items.csv",
        sheet_name=None, kind=DatasetKind.UPLOADED,
    )
    payload = profile.model_dump_json()
    from app.semantic.models import DatasetProfile

    restored = DatasetProfile.model_validate_json(payload)
    assert restored.text_columns == profile.text_columns
    assert "description" in restored.text_columns
