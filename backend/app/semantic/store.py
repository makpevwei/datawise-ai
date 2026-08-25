"""Dataset registry: the runtime "database" substitute for this POC.

Holds parsed DataFrames and their profiles in memory for fast access, and
persists each dataset to disk (parquet + JSON metadata) under the configured
upload directory so datasets survive a server restart. No relational DB is
required for the current scope.
"""

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.semantic.models import DatasetProfile, DatasetSummary


def _sanitize_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce mixed-type object columns to plain strings.

    Real-world spreadsheets routinely mix types within a single "text"
    column (e.g. an Invoice column of mostly integers with a few
    "C123456" cancellation codes) -- valid for pandas, but pyarrow's
    schema inference rejects it outright. Only object-dtype columns are
    touched; already-typed numeric/date columns are left alone, and our
    own type inference re-coerces stringified numerics when needed.
    """
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: v if pd.isna(v) else str(v))
    return df


@dataclass
class DatasetRecord:
    dataframe: pd.DataFrame
    profile: DatasetProfile


class DatasetStore:
    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, DatasetRecord] = {}
        self._lock = threading.Lock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        for meta_path in sorted(self._storage_dir.glob("*.json")):
            dataset_id = meta_path.stem
            parquet_path = self._storage_dir / f"{dataset_id}.parquet"
            if not parquet_path.exists():
                continue
            try:
                profile = DatasetProfile.model_validate_json(meta_path.read_text())
                df = pd.read_parquet(parquet_path)
            except Exception:  # noqa: BLE001 -- a corrupt cached file must not block startup
                continue
            self._records[dataset_id] = DatasetRecord(dataframe=df, profile=profile)

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def put(self, dataset_id: str, df: pd.DataFrame, profile: DatasetProfile) -> None:
        df = _sanitize_for_parquet(df)
        with self._lock:
            self._records[dataset_id] = DatasetRecord(dataframe=df, profile=profile)
            df.to_parquet(self._storage_dir / f"{dataset_id}.parquet", index=False)
            (self._storage_dir / f"{dataset_id}.json").write_text(profile.model_dump_json())

    def get(self, dataset_id: str) -> DatasetRecord | None:
        return self._records.get(dataset_id)

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            existed = self._records.pop(dataset_id, None) is not None
            (self._storage_dir / f"{dataset_id}.parquet").unlink(missing_ok=True)
            (self._storage_dir / f"{dataset_id}.json").unlink(missing_ok=True)
            return existed

    def list_summaries(self) -> list[DatasetSummary]:
        return [
            DatasetSummary(
                id=r.profile.id,
                name=r.profile.name,
                source_file=r.profile.source_file,
                sheet_name=r.profile.sheet_name,
                kind=r.profile.kind,
                row_count=r.profile.row_count,
                column_count=r.profile.column_count,
                quality_rating=r.profile.quality.overall_rating,
                created_at=r.profile.created_at,
            )
            for r in sorted(self._records.values(), key=lambda r: r.profile.created_at)
        ]

    def all_records(self) -> list[DatasetRecord]:
        return list(self._records.values())
