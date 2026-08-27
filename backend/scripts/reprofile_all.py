"""Re-profile all stored datasets using the corrected type inference engine.

Run: python scripts/reprofile_all.py
"""
import sys
import json
sys.path.insert(0, '.')
import pandas as pd
from pathlib import Path
from app.config import get_settings
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind

settings = get_settings()
upload_dir = Path(settings.upload_dir)

reprofiled = 0
errors = 0

for json_path in sorted(upload_dir.glob("*.json")):
    dataset_id = json_path.stem
    parquet_path = upload_dir / f"{dataset_id}.parquet"
    if not parquet_path.exists():
        continue

    try:
        old_data = json.loads(json_path.read_text())
        df = pd.read_parquet(parquet_path)

        kind_str = old_data.get("kind", "uploaded")
        kind = DatasetKind(kind_str)
        new_profile = profile_dataframe(
            df=df,
            dataset_id=dataset_id,
            name=old_data["name"],
            source_file=old_data["source_file"],
            sheet_name=old_data.get("sheet_name"),
            kind=kind,
        )

        # Preserve created_at from original
        if old_data.get("created_at"):
            from datetime import datetime, timezone
            ca = old_data["created_at"]
            if isinstance(ca, str):
                new_profile.created_at = datetime.fromisoformat(ca.replace("Z", "+00:00"))

        json_path.write_text(new_profile.model_dump_json())

        old_id = set(old_data.get("identifier_columns", []))
        new_id = set(new_profile.identifier_columns)
        promoted = new_id - old_id
        demoted = old_id - new_id

        if promoted or demoted:
            print(f"  [{new_profile.name}] newly identifier={sorted(promoted)} demoted={sorted(demoted)}")

        reprofiled += 1
    except Exception as e:
        print(f"  ERROR {dataset_id}: {e}")
        errors += 1

print(f"\nRe-profiled: {reprofiled} datasets, errors: {errors}")
