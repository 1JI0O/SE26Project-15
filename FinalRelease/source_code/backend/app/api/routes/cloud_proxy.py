"""Loopback reverse proxy for the unified TraceLab cloud API.

The desktop WebView (WKWebView/WebView2) enforces TLS validation and offers no
way for an end user to accept the cloud server's self-signed certificate. Rather
than shipping an insecure ``verify=False`` client or a bare-IP HTTPS call the
WebView will reject, the desktop frontend points its cloud client at this
loopback route (``http://127.0.0.1:8765/cloud-api/v1/...``). The local backend
forwards each request upstream over a *pinned* CA bundle and streams the
response back unchanged.

This keeps the frontend behaviour identical: it still sends ``Authorization:
Bearer`` headers and JSON/binary bodies, and still receives the same status
codes, headers and bodies. Only the transport hop changes.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from functools import lru_cache

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.core.config import settings

router = APIRouter(prefix="/cloud-api/v1", tags=["cloud-proxy"])

# Hop-by-hop headers must never be forwarded (RFC 7230 §6.1) plus a few that the
# proxied hop must own itself (host/content-length are recomputed by httpx).
_REQUEST_HOP_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "accept-encoding",
}
_RESPONSE_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}


def _upstream_base() -> str:
    return settings.tracelab_cloud_upstream.rstrip("/")


def _build_ssl_context() -> ssl.SSLContext | bool:
    """Verify context pinned to the bundled cloud CA, or system trust."""

    if not settings.tracelab_cloud_tls_verify:
        return False
    ca_file = settings.tracelab_cloud_ca_file.strip()
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    return True


@lru_cache
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_upstream_base(),
        verify=_build_ssl_context(),
        timeout=settings.tracelab_cloud_proxy_timeout_seconds,
        follow_redirects=False,
    )


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy(path: str, request: Request) -> Response:
    if not _upstream_base():
        return Response(
            content=b'{"detail":"Cloud proxy is not configured"}',
            status_code=503,
            media_type="application/json",
        )

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _REQUEST_HOP_HEADERS
    }
    body = await request.body()

    upstream = _client().build_request(
        request.method,
        f"/api/v1/{path}",
        params=request.query_params,
        headers=forward_headers,
        content=body,
    )
    try:
        response = await _client().send(upstream, stream=True)
    except httpx.ConnectError as error:
        return Response(
            content=f'{{"detail":"Cloud upstream unreachable: {error}"}}'.encode(),
            status_code=502,
            media_type="application/json",
        )
    except httpx.TransportError as error:
        return Response(
            content=f'{{"detail":"Cloud upstream error: {error}"}}'.encode(),
            status_code=502,
            media_type="application/json",
        )

    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in _RESPONSE_HOP_HEADERS
    }

    async def stream_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )
