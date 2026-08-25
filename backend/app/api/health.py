from fastapi import APIRouter

from app.db.session import check_db_connection, connection_error_message

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "datawise-ai-backend"}


@router.get("/health/db")
def health_check_db() -> dict[str, str]:
    if check_db_connection():
        return {"status": "ok", "database": "connected"}
    return {"status": "unavailable", "database": "unreachable", "detail": connection_error_message()}
