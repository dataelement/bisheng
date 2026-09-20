"""Isolation-environment runner HTTP app. Must not import bisheng."""

from __future__ import annotations

import json
from collections.abc import Callable

from execute import handle_exec
from files import ZipSlipError, handle_get_files, handle_put_files
from leases import CapacityError, ForbiddenLeaseError, LeaseStore, UnknownLeaseError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

ROUTES = (
    "/health",
    "/v1/sessions",
    "/v1/sessions/{id}",
    "/v1/sessions/{id}/files",
    "/v1/sessions/{id}/exec",
)


def create_app(
    *,
    token: str,
    sessions_root: str,
    max_sessions: int = 1,
    lease_ttl_s: float = 900,
    max_copy_in_bytes: int = 50 * 1024 * 1024,
    enable_uid_isolation: bool = False,
    clock: Callable[[], float] | None = None,
) -> Starlette:
    if not token:
        raise RuntimeError("runner token must not be empty")
    store = LeaseStore(
        sessions_root=sessions_root,
        max_sessions=max_sessions,
        lease_ttl_s=lease_ttl_s,
        enable_uid_isolation=enable_uid_isolation,
        clock=clock,
    )

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    def _bearer(request: Request) -> str:
        header = request.headers.get("authorization") or request.headers.get("x-sandbox-token") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return header.strip()

    def _lease_token(request: Request) -> str:
        return (request.headers.get("x-lease-token") or "").strip()

    async def create_session(request: Request) -> Response:
        if _bearer(request) != token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            lease = store.create()
        except CapacityError:
            return JSONResponse({"error": "capacity exceeded"}, status_code=503)
        return JSONResponse(
            {
                "session_id": lease.session_id,
                "lease_token": lease.lease_token,
                "lease_expires_at": store.expires_at_iso(lease),
            }
        )

    async def delete_session(request: Request) -> Response:
        session_id = request.path_params["id"]
        try:
            store.delete(session_id, _lease_token(request))
        except UnknownLeaseError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except ForbiddenLeaseError:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"ok": True})

    async def put_files(request: Request) -> Response:
        session_id = request.path_params["id"]
        try:
            lease = store.get(session_id, _lease_token(request))
        except UnknownLeaseError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except ForbiddenLeaseError:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.body()
        raw_manifest = request.headers.get("x-file-manifest") or "{}"
        try:
            manifest = json.loads(raw_manifest)
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid manifest"}, status_code=400)
        if not isinstance(manifest, dict):
            return JSONResponse({"error": "invalid manifest"}, status_code=400)
        try:
            result = handle_put_files(lease, body, manifest, max_copy_in_bytes)
        except ZipSlipError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    async def get_files(request: Request) -> Response:
        session_id = request.path_params["id"]
        try:
            lease = store.get(session_id, _lease_token(request))
        except UnknownLeaseError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except ForbiddenLeaseError:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        payload = handle_get_files(lease)
        return Response(payload, media_type="application/gzip")

    async def exec_code(request: Request) -> Response:
        session_id = request.path_params["id"]
        try:
            lease = store.get(session_id, _lease_token(request))
        except UnknownLeaseError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except ForbiddenLeaseError:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        result = handle_exec(store, lease, payload)
        return JSONResponse(result)

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/v1/sessions", create_session, methods=["POST"]),
            Route("/v1/sessions/{id}", delete_session, methods=["DELETE"]),
            Route("/v1/sessions/{id}/files", put_files, methods=["PUT"]),
            Route("/v1/sessions/{id}/files", get_files, methods=["GET"]),
            Route("/v1/sessions/{id}/exec", exec_code, methods=["POST"]),
        ]
    )
    app.state.store = store
    app.state.token = token
    return app
