"""Upload orchestration: validate -> parse -> profile -> store.

One malformed file must never take down the rest of a multi-file upload --
every failure is captured as an UploadError for that file/sheet and the
remaining files continue to be processed.
"""

from app.parsing.errors import ParsingError
from app.parsing.service import parse_csv_bytes, parse_xlsx_bytes
from app.profiling.service import profile_dataframe
from app.semantic.models import DatasetKind, DatasetSummary, UploadError, UploadResult, UploadWarning
from app.semantic.store import DatasetStore
from app.upload.validation import UploadValidationError, validate_upload


def ingest_files(
    files: list[tuple[str, bytes]],
    store: DatasetStore,
    max_size_mb: int,
    kind: DatasetKind = DatasetKind.UPLOADED,
) -> UploadResult:
    summaries: list[DatasetSummary] = []
    warnings: list[UploadWarning] = []
    errors: list[UploadError] = []

    for filename, content in files:
        try:
            validated = validate_upload(filename, content, max_size_mb)
        except UploadValidationError as exc:
            errors.append(UploadError(file=filename, message=str(exc)))
            continue

        try:
            if validated.extension == ".csv":
                tables = [parse_csv_bytes(validated.content, filename)]
                skipped_sheet_warnings: list[str] = []
            else:
                tables, skipped_sheet_warnings = parse_xlsx_bytes(validated.content, filename)
        except ParsingError as exc:
            errors.append(UploadError(file=filename, message=str(exc)))
            continue

        for message in skipped_sheet_warnings:
            warnings.append(UploadWarning(file=filename, message=message))

        for table in tables:
            for message in table.warnings:
                warnings.append(UploadWarning(file=filename, sheet=table.sheet_name, message=message))

            dataset_id = store.new_id()
            display_name = filename if table.sheet_name is None else f"{filename} — {table.sheet_name}"

            profile = profile_dataframe(
                df=table.dataframe,
                dataset_id=dataset_id,
                name=display_name,
                source_file=filename,
                sheet_name=table.sheet_name,
                kind=kind,
                duplicate_column_names=table.duplicate_columns,
            )
            store.put(dataset_id, table.dataframe, profile)

            summaries.append(
                DatasetSummary(
                    id=profile.id,
                    name=profile.name,
                    source_file=profile.source_file,
                    sheet_name=profile.sheet_name,
                    kind=profile.kind,
                    row_count=profile.row_count,
                    column_count=profile.column_count,
                    quality_rating=profile.quality.overall_rating,
                    created_at=profile.created_at,
                )
            )

    return UploadResult(datasets=summaries, warnings=warnings, errors=errors)
