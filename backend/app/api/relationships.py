from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_scoped_dataset_store
from app.api.scoped_stores import ScopedDatasetStore
from app.auth.dependencies import get_current_user
from app.db.models import Dataset, User
from app.db.session import get_db
from app.relationships.joins import JoinError, JoinSafetyError, join_content_hash, perform_join, preview_join
from app.relationships.service import detect_relationships
from app.semantic.models import DatasetSummary, JoinPreviewResult, JoinRequest, JoinResult, RelationshipSuggestion

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("", response_model=list[RelationshipSuggestion])
def list_relationships(
    dataset_ids: str | None = Query(default=None, description="Comma-separated dataset ids; omit for all."),
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RelationshipSuggestion]:
    # Only discover relationships between a dataset's *active* version --
    # otherwise every superseded upload would keep generating its own set
    # of suggestions forever, drowning out the few that actually matter.
    active_ids = {
        row.storage_reference
        for row in db.query(Dataset.storage_reference).filter(Dataset.user_id == user.id, Dataset.is_active.is_(True))
    }
    records = [r for r in store.all_records() if r.profile.id in active_ids]
    if dataset_ids:
        wanted = set(dataset_ids.split(","))
        records = [r for r in records if r.profile.id in wanted]
    return detect_relationships(records)


@router.post("/join/preview", response_model=JoinPreviewResult)
def preview_join_datasets(
    request: JoinRequest,
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
) -> JoinPreviewResult:
    """Dry-run stats for a proposed join -- no dataset is created. Lets the
    user see rows/matches/warnings before committing via /join."""
    try:
        return preview_join(store, request)
    except JoinSafetyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JoinError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/join", response_model=JoinResult)
def join_datasets(
    request: JoinRequest,
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JoinResult:
    # Duplicate-join prevention: the same source datasets (dataset id already
    # encodes version -- each new version is a distinct row) + same keys +
    # same join type => reuse the existing derived dataset instead of
    # minting a new one.
    content_hash = join_content_hash(request)
    existing = (
        db.query(Dataset)
        .filter(Dataset.user_id == user.id, Dataset.content_hash == content_hash, Dataset.is_active.is_(True))
        .first()
    )
    if existing is not None:
        existing_record = store.get(existing.storage_reference)
        if existing_record is not None:
            try:
                preview = preview_join(store, request)
            except JoinError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            existing_profile = existing_record.profile
            return JoinResult(
                new_dataset_id=existing_profile.id,
                new_dataset=DatasetSummary(
                    id=existing_profile.id,
                    name=existing_profile.name,
                    source_file=existing_profile.source_file,
                    sheet_name=existing_profile.sheet_name,
                    kind=existing_profile.kind,
                    row_count=existing_profile.row_count,
                    column_count=existing_profile.column_count,
                    quality_rating=existing_profile.quality.overall_rating,
                    created_at=existing_profile.created_at,
                ),
                reused_existing=True,
                left_dataset_id=request.left_dataset_id,
                left_column=request.left_column,
                right_dataset_id=request.right_dataset_id,
                right_column=request.right_column,
                join_type=request.join_type,
                rows_before_left=preview.rows_before_left,
                rows_before_right=preview.rows_before_right,
                rows_after=preview.rows_after,
                matched_both=preview.matched_both,
                unmatched_left=preview.unmatched_left,
                unmatched_right=preview.unmatched_right,
                duplicate_key_warning=preview.duplicate_key_warning,
                cardinality=preview.cardinality,
                key_overlap_percentage=preview.key_overlap_percentage,
                estimated_fan_out_rows=preview.estimated_fan_out_rows,
                notes=["An identical joined dataset already exists in your workspace -- reusing it."] + preview.notes,
            )

    try:
        result = perform_join(store, request, created_by_user_id=user.id)
    except JoinSafetyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JoinError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # perform_join wrote the joined dataset straight into the (scoped)
    # store -- give it an ownership row too, or it would be invisible to
    # this same user on their next request.
    joined = result.new_dataset
    db.add(
        Dataset(
            id=joined.id,
            user_id=user.id,
            original_filename=joined.source_file,
            display_name=joined.name,
            file_type="joined",
            file_size=0,
            row_count=joined.row_count,
            column_count=joined.column_count,
            processing_status="ready",
            content_hash=content_hash,
            storage_reference=joined.id,
        )
    )
    db.commit()
    return result
