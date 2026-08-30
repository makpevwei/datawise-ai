"""Dataset registry: the runtime "database" substitute for this POC.

Holds parsed DataFrames and their profiles in memory for fast access, and
persists each dataset to disk (parquet + JSON metadata) under the configured
upload directory so datasets survive a server restart. No relational DB is
required for the current scope.
"""

import threading
import uuid
from dataclasses import dataclass
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
    """Every dataset from every user lives in one shared on-disk directory
    (per-user isolation is layered on top by ScopedDatasetStore -- see
    app/api/scoped_stores.py). Construction used to eagerly parse every
    stored dataset's full parquet file into memory up front, which made
    every restart's cost grow with the *total* data ever uploaded by
    *anyone*, not just what the current request needs -- on a long-lived,
    memory-constrained process this compounds with every crash-restart
    into an increasingly likely OOM. Metadata (small JSON) is still indexed
    eagerly so listing/lookup-by-id is cheap; each dataset's actual
    DataFrame is parsed from its parquet file only the first time something
    asks for it, then cached in memory for the life of the process.
    """

    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, DatasetProfile] = {}
        self._records: dict[str, DatasetRecord] = {}
        self._lock = threading.Lock()
        self._index_from_disk()

    def _index_from_disk(self) -> None:
        for meta_path in sorted(self._storage_dir.glob("*.json")):
            dataset_id = meta_path.stem
            if not (self._storage_dir / f"{dataset_id}.parquet").exists():
                continue
            try:
                profile = DatasetProfile.model_validate_json(meta_path.read_text())
            except Exception:  # noqa: BLE001 -- a corrupt cached file must not block startup
                continue
            self._profiles[dataset_id] = profile

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def put(self, dataset_id: str, df: pd.DataFrame, profile: DatasetProfile) -> None:
        df = _sanitize_for_parquet(df)
        with self._lock:
            self._profiles[dataset_id] = profile
            self._records[dataset_id] = DatasetRecord(dataframe=df, profile=profile)
            df.to_parquet(self._storage_dir / f"{dataset_id}.parquet", index=False)
            (self._storage_dir / f"{dataset_id}.json").write_text(profile.model_dump_json())

    def get(self, dataset_id: str) -> DatasetRecord | None:
        cached = self._records.get(dataset_id)
        if cached is not None:
            return cached
        profile = self._profiles.get(dataset_id)
        if profile is None:
            return None
        try:
            df = pd.read_parquet(self._storage_dir / f"{dataset_id}.parquet")
        except Exception:  # noqa: BLE001 -- a corrupt cached file must not surface as a crash
            return None
        record = DatasetRecord(dataframe=df, profile=profile)
        with self._lock:
            self._records[dataset_id] = record
        return record

    def delete(self, dataset_id: str) -> bool:
        with self._lock:
            existed = self._profiles.pop(dataset_id, None) is not None
            self._records.pop(dataset_id, None)
            (self._storage_dir / f"{dataset_id}.parquet").unlink(missing_ok=True)
            (self._storage_dir / f"{dataset_id}.json").unlink(missing_ok=True)
            return existed

    def list_summaries(self) -> list[DatasetSummary]:
        return [
            DatasetSummary(
                id=p.id,
                name=p.name,
                source_file=p.source_file,
                sheet_name=p.sheet_name,
                kind=p.kind,
                row_count=p.row_count,
                column_count=p.column_count,
                quality_rating=p.quality.overall_rating,
                created_at=p.created_at,
            )
            for p in sorted(self._profiles.values(), key=lambda p: p.created_at)
        ]

    def all_records(self) -> list[DatasetRecord]:
        records = (self.get(dataset_id) for dataset_id in self._profiles)
        return [r for r in records if r is not None]
