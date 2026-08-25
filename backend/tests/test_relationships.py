import pandas as pd

from app.profiling.service import profile_dataframe
from app.relationships.joins import perform_join
from app.relationships.service import detect_relationships
from app.semantic.models import ConfidenceLevel, DatasetKind, JoinCardinality, JoinRequest
from app.semantic.store import DatasetRecord, DatasetStore
from tests.factories import customers_df, orders_df


def _record(df, dataset_id, name):
    profile = profile_dataframe(df, dataset_id, name, f"{name}.csv", None, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_detects_high_confidence_relationship_on_matching_ids():
    customers = _record(customers_df(), "c1", "customers")
    orders = _record(orders_df(), "o1", "orders")

    suggestions = detect_relationships([customers, orders])
    matches = [s for s in suggestions if s.left_column == "customer_id" or s.right_column == "customer_id"]
    assert matches, "expected a customer_id relationship to be suggested"
    assert matches[0].confidence == ConfidenceLevel.HIGH
    assert matches[0].value_overlap_percentage == 100.0


def test_relationship_reasons_explain_the_match():
    customers = _record(customers_df(), "c1", "customers")
    orders = _record(orders_df(), "o1", "orders")
    suggestions = detect_relationships([customers, orders])
    assert suggestions[0].reasons, "every suggestion must explain why it was made"


def test_no_relationship_suggested_between_unrelated_columns():
    customers = _record(customers_df(), "c1", "customers")
    # A dataset that shares no column names or compatible id-like columns.
    unrelated = customers_df().rename(columns={"customer_id": "widget_serial", "name": "colour", "segment": "size"})
    unrelated_record = _record(unrelated, "u1", "widgets")

    suggestions = detect_relationships([customers, unrelated_record])
    assert suggestions == []


def test_never_auto_joins_only_suggests():
    customers = _record(customers_df(), "c1", "customers")
    orders = _record(orders_df(), "o1", "orders")
    suggestions = detect_relationships([customers, orders])
    # detect_relationships must be read-only: original dataframes untouched.
    assert list(customers.dataframe.columns) == ["customer_id", "name", "segment"]
    assert list(orders.dataframe.columns) == ["order_id", "date", "customer_id", "amount", "region"]
    assert suggestions  # sanity: we did find something to suggest


def test_generic_categorical_overlap_is_not_suggested_as_a_relationship():
    """Regression test for the reported false positive: two datasets that
    both happen to have a low-cardinality 'Region' column with overlapping
    values must NOT be suggested as a relationship. Neither column is
    unique in its own table, so neither behaves like a key -- shared
    vocabulary (regions, segments, countries) proves nothing about how the
    tables actually relate."""
    orders = orders_df(20)  # has a "region" column: North/South/East/West, repeated
    customers = customers_df()
    customers["region"] = ["North", "South", "East", "West", "North", "South", "East", "West"]

    orders_record = _record(orders, "o1", "orders")
    customers_record = _record(customers, "c1", "customers")

    suggestions = detect_relationships([orders_record, customers_record])
    region_matches = [s for s in suggestions if s.left_column == "region" or s.right_column == "region"]
    assert region_matches == [], (
        "a shared low-cardinality categorical column must never be suggested as a key relationship"
    )
    # The genuine customer_id key relationship should still be found.
    id_matches = [s for s in suggestions if s.left_column == "customer_id" or s.right_column == "customer_id"]
    assert id_matches


def test_relationship_suggestion_reports_cardinality():
    customers = _record(customers_df(), "c1", "customers")
    orders = _record(orders_df(), "o1", "orders")
    suggestions = detect_relationships([customers, orders])
    match = next(s for s in suggestions if s.left_column == "customer_id" or s.right_column == "customer_id")
    assert match.cardinality in (JoinCardinality.MANY_TO_ONE, JoinCardinality.ONE_TO_MANY)


def test_identifier_name_synonyms_are_recognized(tmp_path):
    # 'product_number' and 'product_id' should stem to the same business
    # key ('product') even though they don't match verbatim.
    products = pd.DataFrame({"product_id": [1, 2, 3, 4, 5, 6], "product_name": ["A", "B", "C", "D", "E", "F"]})
    orders = pd.DataFrame({"order_id": [1, 2, 3, 4, 5, 6, 7, 8], "product_number": [1, 1, 2, 2, 3, 4, 5, 6]})

    products_record = _record(products, "p1", "products")
    orders_record = _record(orders, "o1", "orders")

    suggestions = detect_relationships([products_record, orders_record])
    matches = [s for s in suggestions if {"product_id", "product_number"} == {s.left_column, s.right_column}]
    assert matches, "product_id and product_number should be recognized as the same business key"
    # products.product_id is unique (one product); orders.product_number repeats (many orders per product).
    assert matches[0].cardinality == JoinCardinality.ONE_TO_MANY


def test_derived_dataset_is_not_suggested_as_related_to_its_own_parents(tmp_path):
    store = DatasetStore(storage_dir=tmp_path)
    customers = customers_df()
    orders = orders_df(10)
    store.put("customers", customers, profile_dataframe(customers, "customers", "customers", "customers.csv", None, DatasetKind.UPLOADED))
    store.put("orders", orders, profile_dataframe(orders, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED))

    request = JoinRequest(
        left_dataset_id="orders", left_column="customer_id",
        right_dataset_id="customers", right_column="customer_id",
    )
    result = perform_join(store, request, created_by_user_id="test-user")

    all_records = store.all_records()
    suggestions = detect_relationships(all_records)
    noise = [
        s for s in suggestions
        if {s.left_dataset_id, s.right_dataset_id} == {result.new_dataset_id, "orders"}
        or {s.left_dataset_id, s.right_dataset_id} == {result.new_dataset_id, "customers"}
    ]
    assert noise == [], "a derived dataset must not be suggested as related to its own direct parent"
