from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes import cloud_proxy
from app.core.config import settings
from app.db.session import init_db
from app.services.agent.analysis_jobs import recover_analysis_jobs
from app.services.agent.conversations import recover_agent_runs
from app.services.agent.service import register_analysis_enqueuer
from app.services.analysis_jobs import recover_repository_analysis, run_repository_analysis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    register_analysis_enqueuer(run_repository_analysis)
    recover_repository_analysis()
    recover_agent_runs()
    recover_analysis_jobs()
    yield


# Paper-code bidirectional trace workbench - FastAPI backend
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Paper-code bidirectional trace workbench API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(cloud_proxy.router)
