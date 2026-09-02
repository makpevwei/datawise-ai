"""Semantic column resolution (app/semantic/resolver.py): natural-language
business concepts -> real dataset columns, tolerating naming-convention
differences, business synonyms, typos, and distinguishing dimensions
(product_name) from identifiers (product_id) and measures (sales_amount).
"""

import pandas as pd
import pytest

from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind, DatasetProfile
from app.semantic.resolver import resolve_column

N = 20


def _sales_profile() -> DatasetProfile:
    df = pd.DataFrame(
        {
            "product_id": list(range(1, N + 1)),
            "product_name": [f"Widget {i % 6}" for i in range(1, N + 1)],
            "sales_amount": [100.0 + i * 3.5 for i in range(1, N + 1)],
            "region": [["North", "South", "East", "West"][i % 4] for i in range(1, N + 1)],
            "order_date": pd.date_range("2024-01-01", periods=N, freq="D"),
        }
    )
    return profile_dataframe(df, "sales", "sales", "sales.csv", None, DatasetKind.UPLOADED)


def _ambiguous_product_profile() -> DatasetProfile:
    df = pd.DataFrame(
        {
            "product_id": list(range(1, N + 1)),
            "product_code": [f"SKU-{i}" for i in range(1, N + 1)],
            "product_name": [f"Widget {i % 6}" for i in range(1, N + 1)],
            "sales": [50.0 + i for i in range(1, N + 1)],
        }
    )
    return profile_dataframe(df, "products", "products", "products.csv", None, DatasetKind.UPLOADED)


def _id_only_profile() -> DatasetProfile:
    df = pd.DataFrame(
        {
            "product_id": list(range(1, N + 1)),
            "revenue": [10.0 * i for i in range(1, N + 1)],
        }
    )
    return profile_dataframe(df, "p2", "p2", "p2.csv", None, DatasetKind.UPLOADED)


def _price_history_profile() -> DatasetProfile:
    df = pd.DataFrame(
        {
            "product_price_history_id": list(range(1, N + 1)),
            "price": [9.99 + i for i in range(1, N + 1)],
        }
    )
    return profile_dataframe(df, "prices", "prices", "prices.csv", None, DatasetKind.UPLOADED)


# -- naming-convention normalization -----------------------------------------


@pytest.mark.parametrize(
    "concept",
    ["product", "product name", "product-name", "ProductName", "productname", "PRODUCT NAME"],
)
def test_resolves_naming_convention_variants_to_product_name(concept):
    result = resolve_column(concept, _sales_profile(), role="dimension")
    assert result.column == "product_name"


def test_resolves_customer_id_variants_via_id_token():
    df = pd.DataFrame({"customer_id": list(range(1, N + 1)), "amount": [1.0] * N})
    profile = profile_dataframe(df, "d", "d", "d.csv", None, DatasetKind.UPLOADED)
    for concept in ["customer id", "customer-id", "CustomerID", "customerid"]:
        result = resolve_column(concept, profile, role="dimension")
        assert result.column == "customer_id"


# -- business synonyms --------------------------------------------------------


def test_sales_resolves_to_sales_amount_measure():
    result = resolve_column("sales", _sales_profile(), role="measure")
    assert result.column == "sales_amount"


def test_revenue_synonym_resolves_to_sales_amount_measure():
    result = resolve_column("revenue", _sales_profile(), role="measure")
    assert result.column == "sales_amount"


def test_revenue_prefers_a_literal_revenue_column_over_a_sales_synonym_match():
    # Found live: a dataset with BOTH a "sales"-named column and an actual
    # "revenue"-named column used to score them identically for the
    # concept "revenue" (both counted as one "matched" token, whether by
    # literal match or by the sales<->revenue synonym bridge) -- the tie
    # then silently broke on column order, picking gross_sales_ngn every
    # time regardless of realized_revenue_ngn being the more precise,
    # literal match for what was actually asked.
    df = pd.DataFrame(
        {
            "gross_sales_ngn": [100.0 + i for i in range(1, N + 1)],
            "realized_revenue_ngn": [90.0 + i for i in range(1, N + 1)],
        }
    )
    profile = profile_dataframe(df, "d", "d", "d.csv", None, DatasetKind.UPLOADED)
    result = resolve_column("revenue", profile, role="measure")
    assert result.column == "realized_revenue_ngn"


def test_return_rate_does_not_resolve_to_an_unrelated_numeric_field():
    df = pd.DataFrame({"late_delivery_risk": [0, 1] * 10, "price": [10.0] * 20})
    profile = profile_dataframe(df, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED)

    result = resolve_column("return rate", profile, role="measure")

    assert result.resolved is False
    assert result.column is None


# -- typo tolerance ------------------------------------------------------------


@pytest.mark.parametrize(
    ("typo", "expected"),
    [
        ("prodcut", "product_name"),
        ("prduct name", "product_name"),
    ],
)
def test_typo_tolerant_dimension_resolution(typo, expected):
    result = resolve_column(typo, _sales_profile(), role="dimension")
    assert result.column == expected


def test_typo_does_not_create_a_false_match_against_an_unrelated_long_column():
    # 'price' must resolve to the real 'price' column, not fuzzy-match
    # into 'product_price_history_id' just because it's a substring.
    result = resolve_column("price", _price_history_profile(), role="measure")
    assert result.column == "price"


# -- dimension vs measure / identifier avoidance ------------------------------


def test_prefers_descriptive_dimension_over_identifier_when_both_share_a_stem():
    result = resolve_column("product", _sales_profile(), role="dimension")
    assert result.column == "product_name"
    assert result.column != "product_id"


def test_explicit_id_wording_resolves_to_the_identifier_column():
    result = resolve_column("product id", _sales_profile(), role="dimension")
    assert result.column == "product_id"


def test_falls_back_to_identifier_when_no_descriptive_column_exists():
    result = resolve_column("product", _id_only_profile(), role="dimension")
    assert result.column == "product_id"


def _agent_and_channel_profile() -> DatasetProfile:
    # Reproduces a real bug found live: a fact table with an identifier
    # column that's the ONLY representation of an entity (no human-readable
    # name column for it, e.g. "sales agent" is only ever an ID in this
    # table) alongside an unrelated categorical column that partially
    # shares a token with the concept.
    df = pd.DataFrame(
        {
            "sales_agent_id": [f"E{i:03d}" for i in range(1, N + 1)],
            "sales_channel": [["Retail Store", "Mobile App", "WhatsApp"][i % 3] for i in range(1, N + 1)],
            "revenue": [100.0 + i * 3.5 for i in range(1, N + 1)],
        }
    )
    return profile_dataframe(df, "agents", "agents", "agents.csv", None, DatasetKind.UPLOADED)


def test_identifier_with_a_full_token_match_beats_an_unrelated_partial_match():
    # "sales agent" fully matches sales_agent_id's tokens (sales + agent);
    # sales_channel only matches "sales". The identifier must win even
    # though it's an identifier and the concept never said "id" -- the
    # bug this guards against: a *worse*, unrelated match winning purely
    # because it isn't an identifier (found live: this resolved to
    # sales_channel, producing "the sales channel that generated the most
    # revenue" as the answer to "which sales agent generated the most
    # revenue").
    result = resolve_column("sales agent", _agent_and_channel_profile(), role="dimension")
    assert result.column == "sales_agent_id"


def test_measure_role_never_resolves_to_an_identifier_column():
    # Even though 'product_id' is numeric under the hood, it must never be
    # offered as a measure.
    result = resolve_column("product", _sales_profile(), role="measure")
    assert result.column is None or result.column != "product_id"


def test_measure_role_never_resolves_to_a_non_numeric_column():
    result = resolve_column("region", _sales_profile(), role="measure")
    assert result.column is None


def test_dimension_role_can_resolve_a_plain_categorical_column():
    result = resolve_column("region", _sales_profile(), role="dimension")
    assert result.column == "region"


# -- ambiguity: prefer the best available business dimension -----------------


def test_prefers_product_name_over_product_code_and_product_id_when_all_three_exist():
    result = resolve_column("product", _ambiguous_product_profile(), role="dimension")
    assert result.column == "product_name"


# -- confidence gating / no fabricated column ---------------------------------


def test_returns_no_column_for_a_concept_with_no_reasonable_match():
    result = resolve_column("zorblaxian quantum flux", _sales_profile(), role="dimension")
    assert result.column is None
    assert result.resolved is False


def test_exact_match_carries_no_interpretation_note():
    result = resolve_column("product_name", _sales_profile(), role="dimension")
    assert result.column == "product_name"
    assert result.note is None


def test_non_trivial_match_carries_a_human_readable_interpretation_note():
    result = resolve_column("product", _sales_profile(), role="dimension")
    assert result.note is not None
    assert "product_name" in result.note


def test_empty_concept_resolves_to_nothing():
    result = resolve_column("", _sales_profile(), role="dimension")
    assert result.column is None


@pytest.mark.parametrize(
    "unsupported_concept",
    [
        "marketing ROI",
        "campaign adspend",
        "stockout rate",
        "excess inventory",
        "delivery partner rating",
        "employee revenue",
        "employee profitability",
        "target attainment",
    ],
)
def test_unsupported_case_study_4_concepts_do_not_resolve_to_unrelated_columns(unsupported_concept):
    df = pd.DataFrame(
        {
            "order_id": [1, 2],
            "price": [10.0, 20.0],
            "late_delivery_risk": [0, 1],
            "department": ["Sales", "HR"],
            "rating": [4, 5],
        }
    )
    profile = profile_dataframe(df, "orders", "orders", "orders.csv", None, DatasetKind.UPLOADED)
    result = resolve_column(unsupported_concept, profile, role="measure")
    assert result.resolved is False
    assert result.column is None

