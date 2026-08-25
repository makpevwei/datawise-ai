from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.analysis.engine import AnalysisError, compute_correlation, compute_distribution, run_analysis
from app.analysis.insights import generate_insights
from app.analysis.kpi_discovery import discover_kpis
from app.api.deps import get_scoped_dataset_store
from app.api.scoped_stores import ScopedDatasetStore
from app.api.sessions import append_message, get_or_create_owned_session
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.semantic.models import AnalysisRequest, AnalysisResult, Insight, KPISuggestion

router = APIRouter(prefix="/analysis", tags=["analysis"])


class CorrelationRequest(BaseModel):
    dataset_id: str
    column_a: str
    column_b: str


class AnalysisRunRequest(AnalysisRequest):
    # Optional: attach this run to an Analysis Workspace history thread so
    # it can be restored later (section 30). Omitting it preserves the
    # original stateless contract exactly.
    session_id: str | None = None


def _get_record_or_404(store: ScopedDatasetStore, dataset_id: str):
    record = store.get(dataset_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    return record


@router.post("/run", response_model=AnalysisResult)
def run(
    request: AnalysisRunRequest,
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisResult:
    base_request = AnalysisRequest(**request.model_dump(exclude={"session_id"}))
    try:
        result = run_analysis(base_request, store)
    except AnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.session_id is not None:
        session = get_or_create_owned_session(db, request.session_id, user, default_title="Analysis Workspace")
        summary = result.calculation_description or "Analysis run"
        append_message(
            db, session, role="assistant", kind="analysis_run", content=summary,
            metadata={"request": base_request.model_dump(mode="json"), "result": result.model_dump(mode="json")},
        )

    return result


@router.get("/kpis/{dataset_id}", response_model=list[KPISuggestion])
def kpis(dataset_id: str, store: ScopedDatasetStore = Depends(get_scoped_dataset_store)) -> list[KPISuggestion]:
    record = _get_record_or_404(store, dataset_id)
    return discover_kpis(record)


@router.get("/insights/{dataset_id}", response_model=list[Insight])
def insights(dataset_id: str, store: ScopedDatasetStore = Depends(get_scoped_dataset_store)) -> list[Insight]:
    record = _get_record_or_404(store, dataset_id)
    return generate_insights(record)


@router.post("/correlation")
def correlation(request: CorrelationRequest, store: ScopedDatasetStore = Depends(get_scoped_dataset_store)) -> dict:
    record = _get_record_or_404(store, request.dataset_id)
    for col in (request.column_a, request.column_b):
        if col not in record.dataframe.columns:
            raise HTTPException(status_code=400, detail=f"Column '{col}' not found.")
    return compute_correlation(record.dataframe, request.column_a, request.column_b)


@router.get("/distribution/{dataset_id}")
def distribution(dataset_id: str, column: str, store: ScopedDatasetStore = Depends(get_scoped_dataset_store)) -> dict:
    record = _get_record_or_404(store, dataset_id)
    if column not in record.dataframe.columns:
        raise HTTPException(status_code=400, detail=f"Column '{column}' not found.")
    return compute_distribution(record.dataframe, column)
