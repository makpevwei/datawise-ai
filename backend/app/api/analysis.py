from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.ai.base import LLMProvider
from app.analysis.dashboard_charts import discover_cross_dataset_charts, discover_dashboard_charts
from app.analysis.engine import AnalysisError, compute_correlation, compute_distribution, run_analysis
from app.analysis.insights import generate_insights
from app.analysis.kpi_discovery import discover_kpis
from app.api.deps import get_llm_provider, get_scoped_dataset_store
from app.api.scoped_stores import ScopedDatasetStore
from app.api.sessions import append_message, get_or_create_owned_session
from app.auth.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.semantic.models import AnalysisRequest, AnalysisResult, ChartSpec, Insight, KPISuggestion

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
def kpis(
    dataset_id: str,
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
    llm_provider: LLMProvider | None = Depends(get_llm_provider),
) -> list[KPISuggestion]:
    record = _get_record_or_404(store, dataset_id)
    return discover_kpis(record, llm_provider=llm_provider)


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


@router.get("/dashboard-charts/{dataset_id}", response_model=list[ChartSpec])
def dashboard_charts(
    dataset_id: str,
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
) -> list[ChartSpec]:
    """Return up to 3 default charts for the Management Dashboard.

    Charts are selected deterministically from the dataset's actual columns --
    never invented. Returns an empty list when the dataset lacks the required
    structure (no numeric metrics, no categorical or date dimensions).
    """
    record = _get_record_or_404(store, dataset_id)
    return discover_dashboard_charts(record)


@router.get("/dashboard-charts-multi", response_model=list[ChartSpec])
def dashboard_charts_multi(
    dataset_ids: str,
    store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
) -> list[ChartSpec]:
    """Return up to 4 default charts from the best combination of datasets.

    Accepts a comma-separated list of dataset IDs. Collects charts from each
    dataset individually, PLUS -- when more than one dataset is selected --
    from a safe, automatically-detected join across them (see
    discover_cross_dataset_charts: e.g. a fact table with only a foreign key
    gets a real "Sales by Region" chart once joined to its dimension table,
    which neither table alone could produce). Deduplicates by chart
    fingerprint and returns the strongest charts, trend/comparison preferred
    over KPI scalar cards.
    """
    ids = [d.strip() for d in dataset_ids.split(",") if d.strip()]
    trend_charts: list[ChartSpec] = []
    comparison_charts: list[ChartSpec] = []
    kpi_charts: list[ChartSpec] = []
    seen_fps: set[str] = set()

    def _bucket(charts: list[ChartSpec]) -> None:
        for c in charts:
            fp = f"{c.chart_type.value}:{c.x_column}:{c.y_column}"
            if fp in seen_fps:
                continue
            seen_fps.add(fp)
            if c.chart_type.value in ("line", "time_series"):
                trend_charts.append(c)
            elif c.chart_type.value in ("bar", "ranking", "grouped_bar", "stacked_bar", "donut", "pie"):
                comparison_charts.append(c)
            elif c.chart_type.value == "kpi_card":
                kpi_charts.append(c)

    records = [r for r in (store.get(dataset_id) for dataset_id in ids) if r is not None]
    for record in records:
        _bucket(discover_dashboard_charts(record))
    if len(records) > 1:
        _bucket(discover_cross_dataset_charts(records, store))

    # Prefer meaningful visual charts over KPI cards; fill remaining slots
    result: list[ChartSpec] = []
    for pool in (trend_charts, comparison_charts):
        for c in pool:
            if len(result) >= 4:
                break
            result.append(c)
    if len(result) < 2:
        result.extend(kpi_charts[: 2 - len(result)])
    return result[:4]
