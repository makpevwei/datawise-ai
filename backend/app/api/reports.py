"""Report history: generated PDFs, persisted on disk so reopening a report
serves the existing file rather than re-rendering it (Phase 4 continuation
section 18). Reuses the existing Phase 3 PDF renderer (app/agent/export.py)
unchanged -- this endpoint only adds "save it and remember it belongs to
this user," not a second export pipeline.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import ConfigDict, BaseModel, EmailStr
from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from app.agent.export import render_answer_pdf
from app.agent.schemas import AgentAnswer
from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import Message, Report, User
from app.db.session import get_db
from app.notifications.email import EmailNotConfiguredError, EmailSendError, send_report_email

router = APIRouter(prefix="/reports", tags=["reports"])

# reports_dir ("../data/reports") is relative to backend/, which puts the
# actual files under the DataWise-AI project root, one level above backend/
# -- so storage_reference must be computed relative to THAT root, not to
# backend/ (which the PDF directory falls outside of).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ReportCreate(BaseModel):
    message_id: str
    title: str


class ReportOut(BaseModel):
    id: str
    title: str
    dataset_reference: str | None
    session_id: str | None
    email_status: str
    email_recipient: str | None
    email_sent_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmailReportRequest(BaseModel):
    recipient: EmailStr


def _reports_dir(user_id: str) -> Path:
    settings = get_settings()
    base = (Path(__file__).resolve().parents[2] / settings.reports_dir).resolve()
    user_dir = base / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ReportCreate, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)
) -> ReportOut:
    message = db.get(Message, payload.message_id)
    if message is None or message.session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")
    if message.kind != "agent_answer":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only an agent answer can be exported to PDF.")

    try:
        answer = AgentAnswer.model_validate(message.message_metadata)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This message has no exportable answer.") from exc

    pdf_bytes = render_answer_pdf(answer)

    report = Report(user_id=user.id, session_id=message.session_id, title=payload.title.strip() or "Report", storage_reference="")
    db.add(report)
    db.flush()

    pdf_path = _reports_dir(user.id) / f"{report.id}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    report.storage_reference = str(pdf_path.relative_to(_PROJECT_ROOT))
    db.commit()
    db.refresh(report)
    return ReportOut.model_validate(report)


@router.get("", response_model=list[ReportOut])
def list_reports(db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[ReportOut]:
    reports = db.query(Report).filter(Report.user_id == user.id).order_by(desc(Report.created_at)).all()
    return [ReportOut.model_validate(r) for r in reports]


def _get_owned_report(db: DBSession, report_id: str, user: User) -> Report:
    report = db.get(Report, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report


@router.get("/{report_id}")
def get_report(report_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    report = _get_owned_report(db, report_id, user)
    pdf_path = _PROJECT_ROOT / report.storage_reference
    if not pdf_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file is missing.")
    return Response(
        content=pdf_path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={report.id}.pdf"},
    )


@router.post("/{report_id}/email", response_model=ReportOut)
def email_report(
    report_id: str,
    payload: EmailReportRequest,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    report = _get_owned_report(db, report_id, user)
    pdf_path = _PROJECT_ROOT / report.storage_reference
    if not pdf_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file is missing.")

    settings = get_settings()
    try:
        send_report_email(
            settings=settings,
            to_email=payload.recipient,
            subject=f"DataWise AI report: {report.title}",
            body_text=f'Your DataWise AI report "{report.title}" is attached.',
            attachment_bytes=pdf_path.read_bytes(),
            attachment_filename=f"{report.title or 'datawise-report'}.pdf",
        )
    except EmailNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except EmailSendError as exc:
        report.email_status = "failed"
        report.email_recipient = payload.recipient
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    report.email_status = "sent"
    report.email_recipient = payload.recipient
    report.email_sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(report)
    return ReportOut.model_validate(report)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: str, db: DBSession = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    report = _get_owned_report(db, report_id, user)
    pdf_path = _PROJECT_ROOT / report.storage_reference
    pdf_path.unlink(missing_ok=True)
    db.delete(report)
    db.commit()
