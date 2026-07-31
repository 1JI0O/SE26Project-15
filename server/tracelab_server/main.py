from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import TimeoutError as PoolTimeout

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
@app.exception_handler(PoolTimeout)
async def _pool_timeout_handler(_request: Request, _exc: PoolTimeout) -> JSONResponse:
    """Answer 503 when every pooled connection is checked out.

    Under load the pool saturates before PostgreSQL does, because the ASGI threadpool is
    wider than the pool. Without this the timeout escapes as an unhandled ASGI exception
    and the client sees an opaque 500 with no signal that retrying would work.
    """

    return JSONResponse(
        status_code=503,
        content={"detail": "The server is at capacity. Retry shortly."},
        headers={"Retry-After": "5"},
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
