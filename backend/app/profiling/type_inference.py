"""Column type inference heuristics.

Rules are deliberately explicit and documented so the reasoning behind a
classification can be surfaced to the user rather than being a black box.
"""

import re
import warnings

import pandas as pd

from app.semantic.models import ColumnType

# Public so app/relationships/service.py can reuse the exact same
# tokenization when stemming column names for join-key matching.
ID_TOKENS = {"id", "code", "key", "uuid", "no", "num", "number", "sku"}
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
CURRENCY_CHARS = re.compile(r"[,$€£₦\s]")


def tokenize_column_name(column_name: str) -> list[str]:
    snake = CAMEL_BOUNDARY.sub("_", column_name).lower()
    return [t for t in NON_ALNUM.split(snake) if t]


def looks_like_identifier_name(column_name: str) -> bool:
    return any(t in ID_TOKENS for t in tokenize_column_name(column_name))


def infer_column_type(series: pd.Series, column_name: str) -> tuple[ColumnType, list[str]]:
    """Returns (type, quality_flags). Never raises."""
    flags: list[str] = []
    non_null = series.dropna()
    row_count = len(series)

    if len(non_null) == 0:
        return ColumnType.UNKNOWN, flags

    unique_ratio = non_null.nunique() / len(non_null)
    is_id_name = looks_like_identifier_name(column_name)

    if pd.api.types.is_bool_dtype(series):
        return ColumnType.BOOLEAN, flags

    if pd.api.types.is_numeric_dtype(series):
        if is_id_name and unique_ratio > 0.95 and len(non_null) > 5:
            return ColumnType.IDENTIFIER, flags
        return ColumnType.NUMERIC, flags

    if pd.api.types.is_datetime64_any_dtype(series):
        return ColumnType.DATE, flags

    # Object/string column: try numeric coercion first (handles "1,234.50" etc.)
    cleaned = non_null.astype(str).str.replace(CURRENCY_CHARS, "", regex=True)
    numeric_coerced = pd.to_numeric(cleaned, errors="coerce")
    numeric_success_rate = numeric_coerced.notna().mean()
    if numeric_success_rate >= 0.9:
        flags.append("numeric_stored_as_text")
        if is_id_name and unique_ratio > 0.95 and len(non_null) > 5:
            return ColumnType.IDENTIFIER, flags
        return ColumnType.NUMERIC, flags

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        date_coerced = pd.to_datetime(non_null, errors="coerce")
    date_success_rate = date_coerced.notna().mean()
    if date_success_rate >= 0.9:
        return ColumnType.DATE, flags

    if is_id_name and unique_ratio > 0.9 and len(non_null) > 5:
        return ColumnType.IDENTIFIER, flags

    if unique_ratio > 0.9 and len(non_null) > 20:
        return ColumnType.TEXT, flags

    return ColumnType.CATEGORICAL, flags
