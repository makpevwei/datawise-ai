"""app/analysis/sql_query.py -- the DuckDB-backed read-only SQL tool.

Every security claim in that module's docstring is verified here live
against a real DuckDB connection, not assumed: filesystem access, DDL,
multi-statement injection, and a runaway query are each actually attempted
and confirmed blocked, the same standard the rest of this codebase holds
security-relevant code to.
"""

import time

import pandas as pd
import pytest

from app.analysis.sql_query import SqlQueryError, run_sql_query
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind
from app.semantic.store import DatasetRecord
from tests.factories import customers_df, orders_df


def _record(df: pd.DataFrame, dataset_id: str, name: str, sheet_name: str | None = None) -> DatasetRecord:
    profile = profile_dataframe(df, dataset_id, name, f"{name}.csv", sheet_name, DatasetKind.UPLOADED)
    return DatasetRecord(dataframe=df, profile=profile)


def test_simple_select_against_one_dataset_returns_real_rows():
    record = _record(customers_df(), "customers", "customers")
    table = next(iter(run_sql_query([record], "SELECT * FROM customers").table_names))

    result = run_sql_query([record], f"SELECT name, segment FROM {table} WHERE segment = 'Corporate' ORDER BY name")

    assert result.columns == ["name", "segment"]
    assert result.rows == [{"name": "Bob", "segment": "Corporate"}, {"name": "Frank", "segment": "Corporate"}]
    assert result.row_count == 2
    assert result.truncated is False


def test_join_across_two_datasets_matches_independently_computed_ground_truth():
    customers = customers_df()
    orders = orders_df(20)
    records = [_record(customers, "customers", "customers"), _record(orders, "orders", "orders")]

    # Ground truth computed directly with pandas, independently of the SQL
    # tool under test -- the same verification standard used throughout
    # this session's RAG accuracy work.
    merged = orders.merge(customers, on="customer_id")
    expected = merged.groupby("name")["amount"].sum().sort_values(ascending=False)

    result = run_sql_query(
        records,
        "SELECT c.name AS name, SUM(o.amount) AS total "
        "FROM customers c JOIN orders o ON c.customer_id = o.customer_id "
        "GROUP BY c.name ORDER BY total DESC",
    )

    got = {row["name"]: row["total"] for row in result.rows}
    assert got == pytest.approx(expected.to_dict())
    assert set(result.table_names.values()) == {"customers", "orders"}


def test_table_names_and_schema_reflect_the_registered_datasets():
    record = _record(customers_df(), "customers", "customers")
    result = run_sql_query([record], "SELECT 1")
    ((sql_name, display_name),) = result.table_names.items()
    assert display_name == "customers"
    assert result.tables_schema[sql_name] == list(customers_df().columns)


def test_a_workbook_sheet_name_with_spaces_and_punctuation_becomes_a_valid_identifier():
    # A real uploaded workbook's display name looks like
    # "NexaSphere_BI_Case_Study_Dataset.xlsx -- Fact_Sales" -- not a valid
    # unquoted SQL identifier. The sheet name (when present) should be
    # preferred and sanitized into something queryable.
    record = _record(customers_df(), "customers", "Workbook.xlsx -- Dim Customers!", sheet_name="Dim Customers!")
    result = run_sql_query([record], "SELECT 1")
    (sql_name,) = result.table_names.keys()
    assert sql_name.replace("_", "").isalnum()
    # And it's actually usable as a bare identifier in a follow-up query.
    result2 = run_sql_query([record], f"SELECT COUNT(*) AS n FROM {sql_name}")
    assert result2.rows == [{"n": 8}]


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO customers VALUES (99, 'Eve', 'Consumer')",
        "UPDATE customers SET segment = 'x'",
        "DELETE FROM customers",
        "DROP TABLE customers",
        "CREATE TABLE evil (x INT)",
        "ATTACH '/tmp/evil.db' AS evil",
        "PRAGMA database_list",
        "COPY customers TO '/tmp/leak.csv'",
    ],
)
def test_rejects_every_non_select_statement_shape(query):
    record = _record(customers_df(), "customers", "customers")
    with pytest.raises(SqlQueryError):
        run_sql_query([record], query)


def test_rejects_semicolon_separated_multiple_statements():
    record = _record(customers_df(), "customers", "customers")
    with pytest.raises(SqlQueryError):
        run_sql_query([record], "SELECT 1; DROP TABLE customers")


def test_a_semicolon_inside_a_string_literal_does_not_trip_the_multi_statement_check():
    # A legitimate filter value containing a semicolon must not be
    # mistaken for a second statement.
    record = _record(customers_df(), "customers", "customers")
    result = run_sql_query([record], "SELECT 'a;b' AS x")
    assert result.rows == [{"x": "a;b"}]


def test_a_single_trailing_semicolon_is_tolerated():
    record = _record(customers_df(), "customers", "customers")
    result = run_sql_query([record], "SELECT 1 AS x;")
    assert result.rows == [{"x": 1}]


def test_blocks_filesystem_access_even_though_the_statement_is_a_plain_select():
    # The statement-shape check alone would let this through (it IS a
    # SELECT) -- this confirms the real guard, enable_external_access, is
    # actually wired up and actually blocks it, live.
    record = _record(customers_df(), "customers", "customers")
    with pytest.raises(SqlQueryError, match="external|Permission|file system"):
        run_sql_query([record], "SELECT * FROM read_csv_auto('/etc/passwd')")


def test_row_cap_and_truncation_flag():
    record = _record(orders_df(20), "orders", "orders")
    result = run_sql_query([record], "SELECT * FROM orders ORDER BY order_id", max_rows=5)
    assert result.row_count == 5
    assert result.truncated is True


def test_result_under_the_cap_is_not_flagged_truncated():
    record = _record(orders_df(3), "orders", "orders")
    result = run_sql_query([record], "SELECT * FROM orders", max_rows=5)
    assert result.row_count == 3
    assert result.truncated is False


def test_unknown_table_reference_lists_the_real_available_tables_in_the_error():
    record = _record(customers_df(), "customers", "customers")
    with pytest.raises(SqlQueryError, match="customers"):
        run_sql_query([record], "SELECT * FROM nonexistent_table")


def test_no_datasets_raises_a_clear_error():
    with pytest.raises(SqlQueryError):
        run_sql_query([], "SELECT 1")


def test_a_runaway_query_is_cancelled_at_the_timeout_instead_of_hanging():
    # Found flaky live in CI: an earlier version of this test used a plain
    # `SELECT COUNT(*) FROM big a CROSS JOIN big b` over 50k rows (2.5B
    # pairs) -- DuckDB's vectorized, multi-core execution finished that in
    # under half a second on a fast CI runner (~5s on this project's own,
    # much slower, dev machine), so the timeout never actually fired and
    # the test failed with "DID NOT RAISE". A bare COUNT(*) over a cross
    # join is about the cheapest possible per-pair operation there is, and
    # how fast it runs is entirely a function of the CPU it happens to run
    # on -- not a reliable way to build a "this takes a long time" test.
    # `%` (modulo) has no algebraic shortcut across an unconditional cross
    # join (unlike e.g. SUM(a.x*b.x), which DuckDB or a future version of
    # it could rewrite as SUM(a.x)*SUM(b.x)) and is a genuinely
    # per-pair-costly integer operation, so scaling the pair count up
    # substantially (150k x 150k = 22.5B pairs) makes this robust across
    # any plausible hardware with a wide safety margin -- and since the
    # query is cancelled well before completion either way, that larger
    # size costs nothing in actual test runtime.
    big = pd.DataFrame({"x": range(150_000)})
    record = _record(big, "big", "big")
    start = time.monotonic()
    with pytest.raises(SqlQueryError, match="longer than"):
        run_sql_query([record], "SELECT SUM(a.x % (b.x + 1)) FROM big a CROSS JOIN big b", timeout_seconds=1.5)
    # Cancelled promptly, not left to run to completion.
    assert time.monotonic() - start < 20.0
