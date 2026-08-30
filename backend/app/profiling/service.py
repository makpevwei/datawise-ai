"""Data Profiling Layer -- computes column- and dataset-level profiles.

Every statistic here is computed directly from the DataFrame; nothing is
inferred or guessed beyond the documented type-inference heuristics.
"""

from datetime import UTC, datetime

import pandas as pd

from app.profiling.type_inference import CURRENCY_CHARS, infer_column_type
from app.semantic.models import (
    ColumnProfile,
    ColumnType,
    DatasetKind,
    DatasetProfile,
    DatasetQualitySummary,
    TopValue,
)

HIGH_MISSING_THRESHOLD = 50.0
HIGH_CARDINALITY_RATIO = 0.9
HIGH_CARDINALITY_MIN_ROWS = 20


def _numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    cleaned = series.dropna().astype(str).str.replace(CURRENCY_CHARS, "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _date_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce")


def _profile_column(series: pd.Series, name: str) -> ColumnProfile:
    row_count = len(series)
    non_null_count = int(series.notna().sum())
    missing_count = row_count - non_null_count
    missing_percentage = (missing_count / row_count * 100) if row_count else 0.0
    unique_count = int(series.nunique(dropna=True))

    inferred_type, flags = infer_column_type(series, name)

    if missing_percentage > HIGH_MISSING_THRESHOLD:
        flags.append("high_missing")

    profile = ColumnProfile(
        name=name,
        inferred_type=inferred_type,
        row_count=row_count,
        non_null_count=non_null_count,
        missing_count=missing_count,
        missing_percentage=round(missing_percentage, 2),
        unique_count=unique_count,
        is_likely_identifier=inferred_type == ColumnType.IDENTIFIER,
        quality_flags=flags,
    )

    if inferred_type == ColumnType.NUMERIC:
        numeric = _numeric_series(series).dropna()
        if len(numeric) > 0:
            profile.min = float(numeric.min())
            profile.max = float(numeric.max())
            profile.mean = round(float(numeric.mean()), 4)
            profile.median = float(numeric.median())
            profile.std = round(float(numeric.std()), 4) if len(numeric) > 1 else 0.0

    elif inferred_type == ColumnType.CATEGORICAL:
        profile.cardinality = unique_count
        if unique_count / max(non_null_count, 1) > HIGH_CARDINALITY_RATIO and row_count > HIGH_CARDINALITY_MIN_ROWS:
            flags.append("high_cardinality")
        value_counts = series.dropna().astype(str).value_counts().head(5)
        profile.top_values = [
            TopValue(
                value=str(v),
                count=int(c),
                percentage=round(float(c) / max(non_null_count, 1) * 100, 2),
            )
            for v, c in value_counts.items()
        ]

    elif inferred_type == ColumnType.DATE:
        dates = _date_series(series).dropna()
        if len(dates) > 0:
            profile.min_date = dates.min().isoformat()
            profile.max_date = dates.max().isoformat()
            profile.date_coverage_days = int((dates.max() - dates.min()).days)

    return profile


def profile_dataframe(
    df: pd.DataFrame,
    dataset_id: str,
    name: str,
    source_file: str,
    sheet_name: str | None,
    kind: DatasetKind,
    duplicate_column_names: list[str] | None = None,
) -> DatasetProfile:
    columns = [_profile_column(df[col], str(col)) for col in df.columns]

    duplicate_row_count = int(df.duplicated().sum())
    row_count = len(df)
    duplicate_row_percentage = round(duplicate_row_count / row_count * 100, 2) if row_count else 0.0

    columns_mostly_missing = [c.name for c in columns if "high_missing" in c.quality_flags]
    possible_id_columns = [c.name for c in columns if c.inferred_type == ColumnType.IDENTIFIER]
    possible_date_columns = [c.name for c in columns if c.inferred_type == ColumnType.DATE]
    numeric_stored_as_text_columns = [c.name for c in columns if "numeric_stored_as_text" in c.quality_flags]
    high_cardinality_columns = [c.name for c in columns if "high_cardinality" in c.quality_flags]

    score = 100.0
    score -= min(duplicate_row_percentage, 30)
    score -= 15 * len(columns_mostly_missing)
    score -= 5 * len(numeric_stored_as_text_columns)
    score -= 5 * len(duplicate_column_names or [])
    if score >= 85:
        rating = "good"
    elif score >= 60:
        rating = "fair"
    else:
        rating = "poor"

    notes: list[str] = []
    if duplicate_row_count:
        notes.append(f"{duplicate_row_count} duplicate rows ({duplicate_row_percentage}% of rows).")
    if columns_mostly_missing:
        notes.append(
            f"{len(columns_mostly_missing)} column(s) are more than {HIGH_MISSING_THRESHOLD:.0f}% missing: "
            + ", ".join(columns_mostly_missing)
        )
    if numeric_stored_as_text_columns:
        notes.append(
            "Numeric values stored as text in: " + ", ".join(numeric_stored_as_text_columns)
        )
    if duplicate_column_names:
        notes.append("Duplicate column names were auto-renamed: " + ", ".join(duplicate_column_names))
    if high_cardinality_columns:
        notes.append(
            "Unusually high cardinality for a categorical column: " + ", ".join(high_cardinality_columns)
        )

    quality = DatasetQualitySummary(
        duplicate_row_count=duplicate_row_count,
        duplicate_row_percentage=duplicate_row_percentage,
        columns_mostly_missing=columns_mostly_missing,
        possible_id_columns=possible_id_columns,
        possible_date_columns=possible_date_columns,
        numeric_stored_as_text_columns=numeric_stored_as_text_columns,
        high_cardinality_columns=high_cardinality_columns,
        duplicate_column_names=duplicate_column_names or [],
        overall_rating=rating,
        notes=notes,
    )

    return DatasetProfile(
        id=dataset_id,
        name=name,
        source_file=source_file,
        sheet_name=sheet_name,
        kind=kind,
        row_count=row_count,
        column_count=len(columns),
        columns=columns,
        numeric_columns=[c.name for c in columns if c.inferred_type == ColumnType.NUMERIC],
        categorical_columns=[c.name for c in columns if c.inferred_type == ColumnType.CATEGORICAL],
        date_columns=possible_date_columns,
        identifier_columns=possible_id_columns,
        text_columns=[c.name for c in columns if c.inferred_type == ColumnType.TEXT],
        quality=quality,
        created_at=datetime.now(UTC),
    )
