from fastapi import APIRouter

from app.api.routes import artifacts, health, projects, traces

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(artifacts.router)
api_router.include_router(traces.router)

