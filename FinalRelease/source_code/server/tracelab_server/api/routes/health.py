from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from tracelab_server.core.config import settings
from tracelab_server.db.session import get_session
from tracelab_server.schemas.common import HealthRead

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthRead)
def health() -> HealthRead:
    return HealthRead(status="ok", service=settings.app_name)


@router.get("/health/ready", response_model=HealthRead)
def readiness(session: Session = Depends(get_session)) -> HealthRead:
    session.exec(text("SELECT 1"))
    return HealthRead(status="ready", service=settings.app_name)
