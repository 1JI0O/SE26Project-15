from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tracelab_server.admin import web as admin_web
from tracelab_server.api.routes import (
    admin,
    auth,
    blobs,
    cloud_domain,
    cloud_projects,
    health,
    sync,
    workspaces_cloud,
)
from tracelab_server.core.config import settings
from tracelab_server.storage.blob_store import blob_store


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.validate_runtime()
    blob_store.root.mkdir(parents=True, exist_ok=True)
    blob_store.quarantine.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Standalone account and local-first synchronization service for TraceLab.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Range"],
    expose_headers=["Content-Range", "X-Debug-Email-Token"],
)
for server_router in (
    health.router,
    auth.router,
    workspaces_cloud.router,
    cloud_projects.router,
    cloud_domain.router,
    sync.router,
    blobs.router,
    admin.router,
):
    app.include_router(server_router, prefix="/api/v1")

app.include_router(admin_web.router)
app.mount(
    "/admin-console/static",
    StaticFiles(directory=str(Path(admin_web.__file__).with_name("static"))),
    name="admin-static",
)
