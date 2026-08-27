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

# These tokens, when appearing as the LAST token of a column name, are
# strong enough identifiers that we classify the column as IDENTIFIER
# regardless of uniqueness ratio. A foreign key like SalesTerritoryKey
# repeats throughout a fact table but is still an identifier, not a
# summable business measure.
_STRONG_SUFFIX_TOKENS = {"key", "id", "uuid", "guid"}

# A suffix pattern for camelCase and underscore forms.
# Matches columns that END with these suffixes (case-insensitive).
# This is a stronger signal than just "contains id/key somewhere".
_STRONG_IDENTIFIER_SUFFIX = re.compile(
    r"(?i)(?:Key|Id|UUID|GUID|Pk|Fk|RowId|RowKey)$"
    r"|(?:_(?:key|id|uuid|guid|pk|fk|rowid|rowkey))$"
)

CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
CURRENCY_CHARS = re.compile(r"[,$€£₦\s]")


def tokenize_column_name(column_name: str) -> list[str]:
    snake = CAMEL_BOUNDARY.sub("_", column_name).lower()
    return [t for t in NON_ALNUM.split(snake) if t]


def looks_like_identifier_name(column_name: str) -> bool:
    return any(t in ID_TOKENS for t in tokenize_column_name(column_name))


def _has_strong_identifier_suffix(column_name: str) -> bool:
    """Return True when the column name ends with a strong identifier suffix.

    This is a higher-confidence signal than a bare token match:
    - SalesTerritoryKey → ends with 'Key' → strong identifier
    - CustomerKey → ends with 'Key' → strong identifier
    - ProductKey → ends with 'Key' → strong identifier
    - OrderID → ends with 'ID' → strong identifier
    - order_id → ends with '_id' → strong identifier
    But NOT:
    - Sales Amount → doesn't end with an identifier suffix
    - Quantity → doesn't end with an identifier suffix
    - Price → doesn't end with an identifier suffix
    """
    return bool(_STRONG_IDENTIFIER_SUFFIX.search(column_name))


_DATE_SAMPLE_SIZE = 200
_DATE_SAMPLE_FLOOR = 0.05  # far below the 0.9 acceptance bar -- only ever skips columns that are essentially never dates


def _sample_looks_date_like(non_null: pd.Series) -> bool:
    """Cheap pre-check on a small sample before paying for a full-column
    pd.to_datetime -- see infer_column_type's comment for why."""
    sample = non_null.head(_DATE_SAMPLE_SIZE)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        sample_coerced = pd.to_datetime(sample, errors="coerce")
    return sample_coerced.notna().mean() >= _DATE_SAMPLE_FLOOR


def infer_column_type(series: pd.Series, column_name: str) -> tuple[ColumnType, list[str]]:
    """Returns (type, quality_flags). Never raises."""
    flags: list[str] = []
    non_null = series.dropna()
    row_count = len(series)

    if len(non_null) == 0:
        return ColumnType.UNKNOWN, flags

    unique_ratio = non_null.nunique() / len(non_null)
    is_id_name = looks_like_identifier_name(column_name)
    # Strong identifier suffix: classify as IDENTIFIER regardless of unique ratio.
    # Foreign keys in fact tables repeat (e.g. SalesTerritoryKey appears thousands
    # of times), but they are still keys, not summable business measures.
    has_strong_suffix = _has_strong_identifier_suffix(column_name)

    if pd.api.types.is_bool_dtype(series):
        return ColumnType.BOOLEAN, flags

    if pd.api.types.is_numeric_dtype(series):
        # Strong identifier suffix → always IDENTIFIER, regardless of uniqueness.
        if has_strong_suffix:
            return ColumnType.IDENTIFIER, flags
        # Weaker ID heuristic: id-like name + high uniqueness.
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
        if has_strong_suffix:
            return ColumnType.IDENTIFIER, flags
        if is_id_name and unique_ratio > 0.95 and len(non_null) > 5:
            return ColumnType.IDENTIFIER, flags
        return ColumnType.NUMERIC, flags

    # A full-column pd.to_datetime on a large, obviously-non-date text column
    # (e.g. "SO43659 - 1") is expensive: pandas can't infer one consistent
    # format, so it falls back to parsing every value one at a time with
    # dateutil -- seconds of wasted work on a 100k+-row column that was
    # never going to classify as DATE anyway. A cheap sample first (same
    # 0.9 acceptance bar the real check uses, but at a near-zero floor so
    # it can only ever skip the full check for columns with essentially no
    # parseable dates -- never flip a genuine date column's classification)
    # avoids that cost for the common case of a random/coded text column.
    if not _sample_looks_date_like(non_null):
        date_success_rate = 0.0
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            date_coerced = pd.to_datetime(non_null, errors="coerce")
        date_success_rate = date_coerced.notna().mean()
    if date_success_rate >= 0.9:
        return ColumnType.DATE, flags

    if has_strong_suffix:
        return ColumnType.IDENTIFIER, flags
    if is_id_name and unique_ratio > 0.9 and len(non_null) > 5:
        return ColumnType.IDENTIFIER, flags

    if unique_ratio > 0.9 and len(non_null) > 20:
        return ColumnType.TEXT, flags

    return ColumnType.CATEGORICAL, flags
