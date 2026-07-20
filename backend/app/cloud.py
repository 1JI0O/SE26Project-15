from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    auth,
    blobs,
    cloud_domain,
    cloud_projects,
    health,
    sync,
    workspaces_cloud,
)
from app.core.config import settings
from app.db.session import init_db
from app.storage.blob_store import blob_store


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.validate_cloud_runtime()
    if settings.cloud_run_migrations_on_start:
        init_db()
    blob_store.root.mkdir(parents=True, exist_ok=True)
    blob_store.quarantine.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="TraceLab Cloud API",
    version="0.2.0",
    description="Authenticated, workspace-scoped TraceLab cloud and sync API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(
        {
            settings.cloud_public_origin.rstrip("/"),
            *settings.cors_origins,
        }
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Range"],
    expose_headers=["Content-Range", "X-Debug-Email-Token"],
)
for cloud_router in (
    health.router,
    auth.router,
    workspaces_cloud.router,
    cloud_projects.router,
    cloud_domain.router,
    sync.router,
    blobs.router,
    admin.router,
):
    app.include_router(cloud_router, prefix="/api/v1")
