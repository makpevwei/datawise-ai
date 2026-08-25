import pytest

from app.parsing.errors import ParsingError
from app.parsing.service import parse_csv_bytes, parse_xlsx_bytes
from tests.factories import customers_df, orders_df, to_csv_bytes, to_xlsx_bytes


def test_parses_comma_delimited_csv():
    table = parse_csv_bytes(to_csv_bytes(customers_df(), sep=","), "customers.csv")
    assert list(table.dataframe.columns) == ["customer_id", "name", "segment"]
    assert len(table.dataframe) == 8


def test_parses_semicolon_delimited_csv():
    table = parse_csv_bytes(to_csv_bytes(customers_df(), sep=";"), "customers.csv")
    assert list(table.dataframe.columns) == ["customer_id", "name", "segment"]
    assert len(table.dataframe) == 8


def test_detects_duplicate_column_headers():
    content = b"id,id,amount\n1,2,3\n"
    table = parse_csv_bytes(content, "dupes.csv")
    assert "id" in table.duplicate_columns


def test_rejects_empty_csv():
    with pytest.raises(ParsingError, match="empty"):
        parse_csv_bytes(b"", "empty.csv")


def test_rejects_malformed_csv_gracefully():
    # A row with more fields than the header is unrecoverable -- must raise
    # a clean ParsingError rather than letting pandas.errors.ParserError escape.
    with pytest.raises(ParsingError, match="malformed"):
        parse_csv_bytes(b"a,b,c\n1,2,3\n4,5,6,7\n", "ragged.csv")


def test_flags_header_only_csv_as_warning_not_error():
    table = parse_csv_bytes(b"a,b,c\n", "headers_only.csv")
    assert len(table.dataframe) == 0
    assert any("no data rows" in w for w in table.warnings)


def test_parses_multi_sheet_xlsx():
    content = to_xlsx_bytes({"Customers": customers_df(), "Orders": orders_df()})
    tables, warnings = parse_xlsx_bytes(content, "book.xlsx")
    assert {t.sheet_name for t in tables} == {"Customers", "Orders"}
    assert warnings == []


def test_skips_empty_worksheet_with_warning():
    import pandas as pd

    content = to_xlsx_bytes({"Data": customers_df(), "Empty": pd.DataFrame()})
    tables, warnings = parse_xlsx_bytes(content, "book.xlsx")
    assert {t.sheet_name for t in tables} == {"Data"}
    assert any("Empty" in w for w in warnings)


def test_rejects_non_xlsx_content():
    with pytest.raises(ParsingError, match="not a valid"):
        parse_xlsx_bytes(b"not a real workbook", "fake.xlsx")


def test_rejects_empty_xlsx_bytes():
    with pytest.raises(ParsingError, match="empty"):
        parse_xlsx_bytes(b"", "empty.xlsx")
