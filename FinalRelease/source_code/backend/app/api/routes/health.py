from fastapi import APIRouter

from app.core.config import settings
from app.schemas.common import HealthRead

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthRead)
def health() -> HealthRead:
    return HealthRead(status="ok", service=settings.app_name)
