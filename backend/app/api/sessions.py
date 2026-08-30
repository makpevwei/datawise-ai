"""Analysis session history: Ask DataWise conversations and Analysis
Workspace runs, persisted so a user can navigate away and come back (Phase
4 continuation sections 14-17, 30, 49). Reused by app/api/agent.py and
app/api/analysis.py to append messages -- not a second chatbot, just the
durability layer under the existing agent/analysis engines.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import get_current_user
from app.db.models import AnalysisSession, Message, User
from app.db.session import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


class MessageOut(BaseModel):
    id: str
    role: str
    kind: str
    content: str
    metadata: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_model(cls, m: Message) -> "MessageOut":
        return cls(
            id=m.id, role=m.role, kind=m.kind, content=m.content,
            metadata=m.message_metadata or {}, created_at=m.created_at,
        )


class SessionOut(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class SessionDetailOut(SessionOut):
    messages: list[MessageOut]


class SessionCreate(BaseModel):
    title: str


def _get_owned_session(db: DBSession, session_id: str, user: User) -> AnalysisSession:
    session = db.get(AnalysisSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


def get_or_create_owned_session(
    db: DBSession, session_id: str | None, user: User, default_title: str
) -> AnalysisSession:
    """Used by app/api/agent.py and app/api/analysis.py to attach a turn to
    a session without duplicating ownership-check/creation logic. Raises
    404 if session_id is given but doesn't belong to this user."""
    if session_id:
        return _get_owned_session(db, session_id, user)
    session = AnalysisSession(user_id=user.id, title=default_title[:200] or "New Analysis")
    db.add(session)
    db.flush()
    return session


def append_message(
    db: DBSession, session: AnalysisSession, *, role: str, kind: str, content: str, metadata: dict
) -> Message:
    from datetime import datetime

    message = Message(session_id=session.id, role=role, kind=kind, content=content, message_metadata=metadata)
    db.add(message)
    session.last_activity_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    return message


@router.get("", response_model=list[SessionOut])
def list_sessions(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[SessionOut]:
    sessions = (
        db.query(AnalysisSession)
        .filter(AnalysisSession.user_id == user.id)
        .order_by(desc(AnalysisSession.last_activity_at))
        .all()
    )
    return [
        SessionOut(
            id=s.id, title=s.title, status=s.status, created_at=s.created_at,
            updated_at=s.updated_at, last_activity_at=s.last_activity_at,
            message_count=len(s.messages),
        )
        for s in sessions
    ]


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
) -> SessionOut:
    session = AnalysisSession(user_id=user.id, title=payload.title.strip() or "New Analysis")
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionOut(
        id=session.id, title=session.title, status=session.status, created_at=session.created_at,
        updated_at=session.updated_at, last_activity_at=session.last_activity_at, message_count=0,
    )


@router.get("/{session_id}", response_model=SessionDetailOut)
def get_session(
    session_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
) -> SessionDetailOut:
    session = _get_owned_session(db, session_id, user)
    return SessionDetailOut(
        id=session.id, title=session.title, status=session.status, created_at=session.created_at,
        updated_at=session.updated_at, last_activity_at=session.last_activity_at,
        message_count=len(session.messages),
        messages=[MessageOut.from_model(m) for m in session.messages],
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    session = _get_owned_session(db, session_id, user)
    db.delete(session)
    db.commit()
