from fastapi import APIRouter

from app.api.routes import health, papers, projects, repositories, traces, workspace

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(papers.router)
api_router.include_router(repositories.router)
api_router.include_router(traces.router)
api_router.include_router(traces.workspace_router)
api_router.include_router(workspace.router)
