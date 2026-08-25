from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from app.agent.export import render_answer_pdf
from app.agent.graph import run_agentic_graph
from app.agent.memory import ConversationMemory
from app.agent.schemas import AgentAnswer, AskRequest
from app.ai.base import LLMProvider
from app.api.deps import (
    get_conversation_memory,
    get_llm_provider,
    get_scoped_dataset_store,
    get_scoped_document_store,
)
from app.api.scoped_stores import ScopedDatasetStore, ScopedDocumentStore
from app.api.sessions import append_message, get_or_create_owned_session
from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/status")
def agent_status(llm: LLMProvider | None = Depends(get_llm_provider)) -> dict:
    # Goes through the same dependency /ask uses (rather than calling
    # is_llm_configured() directly) so status always reflects what /ask
    # would actually do, and so tests can override it consistently.
    return {"configured": llm is not None}


@router.post("/ask", response_model=AgentAnswer)
def ask(
    request: AskRequest,
    dataset_store: ScopedDatasetStore = Depends(get_scoped_dataset_store),
    document_store: ScopedDocumentStore = Depends(get_scoped_document_store),
    memory: ConversationMemory = Depends(get_conversation_memory),
    llm: LLMProvider | None = Depends(get_llm_provider),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentAnswer:
    settings = get_settings()

    # The persisted AnalysisSession id IS the agent's session_id -- one
    # thread serves both conversational memory (in-process, ephemeral) and
    # history (Postgres, durable). A brand-new question with no session_id
    # gets a fresh session titled from the question itself.
    session = get_or_create_owned_session(db, request.session_id, user, default_title=request.question)

    # dataset_ids/document_ids let the caller (e.g. Ask DataWise's dataset
    # picker) scope which of the user's own resources the agent even sees.
    # narrowed() only ever intersects with what this store is already
    # scoped to, so an id the user doesn't own can't leak in here.
    if request.dataset_ids:
        dataset_store = dataset_store.narrowed(set(request.dataset_ids))
    if request.document_ids:
        document_store = document_store.narrowed(set(request.document_ids))

    answer = run_agentic_graph(
        question=request.question,
        session_id=session.id,
        llm=llm,
        dataset_store=dataset_store,
        document_store=document_store,
        memory=memory,
        max_iterations=settings.agent_max_tool_iterations,
        currency=user.currency,
        decimal_places=user.decimal_places,
    )

    append_message(db, session, role="user", kind="agent_answer", content=request.question, metadata={})
    assistant_message = append_message(
        db, session, role="assistant", kind="agent_answer",
        content=answer.executive_summary or answer.error or "",
        metadata=answer.model_dump(mode="json"),
    )
    answer.message_id = assistant_message.id

    return answer


@router.post("/export/pdf")
def export_pdf(answer: AgentAnswer) -> Response:
    pdf_bytes = render_answer_pdf(answer)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=datawise-analysis.pdf"},
    )
