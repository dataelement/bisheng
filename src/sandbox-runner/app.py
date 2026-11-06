"""Isolation-environment runner HTTP app. Must not import bisheng."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from functools import partial

import anyio
import anyio.from_thread
from execute import handle_exec
from files import (
    MAX_MANIFEST_BYTES,
    ArchiveError,
    CopyInAbortedError,
    ManifestError,
    ZipSlipError,
    handle_get_files,
    handle_put_files,
    read_copy_in_manifest,
)
from leases import (
    CapacityError,
    ForbiddenLeaseError,
    Lease,
    LeaseStore,
    UnknownLeaseError,
)
from logutil import configure, get_logger
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

DEFAULT_MAX_COPY_IN_TOTAL_BYTES = 512 * 1024 * 1024
_NOT_FOUND = {"error": "not found"}
_TOO_LARGE = {"error": "copy-in body too large"}


def copy_in_body_limit(max_copy_in_total_bytes: int) -> int:
    """Largest copy-in body accepted: the frame, the capped file bytes, tar overhead.

    The executor caps the same total before it builds the tar, so a legitimate
    body stays well below this. Tar headers and padding are at most ~1 KiB per
    member; gzip never grows incompressible data by more than a fraction of a
    percent. Allow 1/8 of the cap (at least 64 MiB) for that.
    """
    overhead = max(64 * 1024 * 1024, max_copy_in_total_bytes // 8)
    return 4 + MAX_MANIFEST_BYTES + max_copy_in_total_bytes + overhead


class BodyTooLargeError(Exception):
    pass


class _StreamedBody:
    """Blocking reader over an ASGI request body, for use from a worker thread.

    Each read pulls the next chunk from the event loop, so at most one chunk
    plus the read size is held in memory and nothing is spooled to disk.
    Raises BodyTooLargeError once
    more than ``limit`` bytes have arrived.
    """

    def __init__(self, chunks: AsyncIterator[bytes], limit: int):
        self._chunks = chunks
        self._limit = limit
        self._buf = bytearray()
        self._eof = False
        self.total = 0

    def _pull(self) -> None:
        try:
            chunk = anyio.from_thread.run(self._chunks.__anext__)
        except StopAsyncIteration:
            self._eof = True
            return
        self.total += len(chunk)
        if self.total > self._limit:
            raise BodyTooLargeError()
        self._buf += chunk

    def read(self, size: int = -1) -> bytes:
        while not self._eof and (size is None or size < 0 or len(self._buf) < size):
            self._pull()
        if size is None or size < 0 or size >= len(self._buf):
            out = bytes(self._buf)
            self._buf.clear()
            return out
        out = bytes(self._buf[:size])
        del self._buf[:size]
        return out


def create_app(
    *,
    token: str,
    sessions_root: str,
    max_sessions: int = 1,
    lease_ttl_s: float = 900,
    max_copy_in_bytes: int = 50 * 1024 * 1024,
    max_copy_in_total_bytes: int = DEFAULT_MAX_COPY_IN_TOTAL_BYTES,
    max_copy_in_body_bytes: int | None = None,
    enable_uid_isolation: bool = False,
    clock: Callable[[], float] | None = None,
) -> Starlette:
    if not token:
        raise RuntimeError("runner token must not be empty")
    configure()
    log = get_logger()
    store = LeaseStore(
        sessions_root=sessions_root,
        max_sessions=max_sessions,
        lease_ttl_s=lease_ttl_s,
        enable_uid_isolation=enable_uid_isolation,
        clock=clock,
    )
    log.info(
        "ready sessions_root=%s max_sessions=%s lease_ttl_s=%s isolation=%s copy_in_total_cap=%s",
        sessions_root,
        max_sessions,
        lease_ttl_s,
        enable_uid_isolation,
        max_copy_in_total_bytes,
    )

    # Blocking work runs in worker threads so one exec never stalls the event
    # loop. Separate limiters: execs (and same-session execs queued on the lease
    # lock) cannot use up the threads that create / DELETE need, so DELETE can
    # always reach a running exec and kill it.
    slots = max(max_sessions, 1)
    exec_limiter = anyio.CapacityLimiter(slots * 2 + 4)
    files_limiter = anyio.CapacityLimiter(slots * 2 + 4)
    control_limiter = anyio.CapacityLimiter(8)

    async def _run(limiter: anyio.CapacityLimiter, func: Callable, *args, **kwargs):
        return await anyio.to_thread.run_sync(partial(func, *args, **kwargs), limiter=limiter)

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    def _bearer(request: Request) -> str:
        header = request.headers.get("authorization") or request.headers.get("x-sandbox-token") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return header.strip()

    def _lease_token(request: Request) -> str:
        return (request.headers.get("x-lease-token") or "").strip()

    async def _acquire(request: Request, action: str) -> Lease | Response:
        session_id = request.path_params["id"]
        try:
            return await _run(control_limiter, store.acquire, session_id, _lease_token(request))
        except UnknownLeaseError:
            log.warning("session missing action=%s session_id=%s", action, session_id)
            return JSONResponse(_NOT_FOUND, status_code=404)
        except ForbiddenLeaseError:
            log.warning("lease forbidden action=%s session_id=%s", action, session_id)
            return JSONResponse({"error": "forbidden"}, status_code=403)

    async def create_session(request: Request) -> Response:
        if _bearer(request) != token:
            log.warning("auth failed action=create_session")
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            lease = await _run(control_limiter, store.create)
        except CapacityError:
            log.warning(
                "session rejected reason=capacity slots=%s/%s",
                max_sessions,
                max_sessions,
            )
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
            await _run(
                control_limiter,
                store.delete,
                session_id,
                _lease_token(request),
                reason="client",
            )
        except UnknownLeaseError:
            log.warning("session missing action=delete session_id=%s", session_id)
            return JSONResponse(_NOT_FOUND, status_code=404)
        except ForbiddenLeaseError:
            log.warning("lease forbidden action=delete session_id=%s", session_id)
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse({"ok": True})

    body_limit = max_copy_in_body_bytes or copy_in_body_limit(max_copy_in_total_bytes)

    def _put_locked(lease: Lease, body: _StreamedBody) -> dict:
        manifest = read_copy_in_manifest(body)
        with store.locked(lease):
            if lease.deleted:
                raise UnknownLeaseError()
            return handle_put_files(
                lease,
                body,
                manifest,
                max_copy_in_bytes,
                max_copy_in_total_bytes,
                should_stop=lambda: lease.deleted,
            )

    async def put_files(request: Request) -> Response:
        session_id = request.path_params["id"]
        declared = request.headers.get("content-length") or ""
        if declared.isdigit() and int(declared) > body_limit:
            log.warning(
                "copy-in rejected session_id=%s reason=too_large content_length=%s limit=%s",
                session_id,
                declared,
                body_limit,
            )
            return JSONResponse(_TOO_LARGE, status_code=413)
        acquired = await _acquire(request, "copy-in")
        if isinstance(acquired, Response):
            return acquired
        lease = acquired
        # The tar is extracted while it streams in: no spool file, no full body in memory.
        body = _StreamedBody(request.stream(), body_limit)
        try:
            try:
                result = await _run(files_limiter, _put_locked, lease, body)
            except ManifestError:
                return JSONResponse({"error": "invalid manifest"}, status_code=400)
            except ArchiveError:
                log.warning("copy-in rejected session_id=%s error=invalid archive", session_id)
                return JSONResponse({"error": "invalid archive"}, status_code=400)
            except ZipSlipError as exc:
                log.warning("copy-in rejected session_id=%s error=%s", session_id, exc)
                return JSONResponse({"error": str(exc)}, status_code=400)
            except BodyTooLargeError:
                log.warning(
                    "copy-in rejected session_id=%s reason=too_large streamed=%s limit=%s",
                    session_id,
                    body.total,
                    body_limit,
                )
                return JSONResponse(_TOO_LARGE, status_code=413)
            except (UnknownLeaseError, CopyInAbortedError):
                log.warning("session missing action=copy-in session_id=%s", session_id)
                return JSONResponse(_NOT_FOUND, status_code=404)
        finally:
            store.release(lease)
        body_bytes = body.total
        log.info(
            "copy-in session_id=%s bytes=%s written=%s skipped=%s",
            session_id,
            body_bytes,
            len(result.get("written") or []),
            len(result.get("skipped") or []),
        )
        return JSONResponse(result)

    def _get_locked(lease: Lease) -> bytes:
        with store.locked(lease):
            if lease.deleted:
                raise UnknownLeaseError()
            return handle_get_files(lease)

    async def get_files(request: Request) -> Response:
        session_id = request.path_params["id"]
        acquired = await _acquire(request, "copy-out")
        if isinstance(acquired, Response):
            return acquired
        lease = acquired
        try:
            payload = await _run(files_limiter, _get_locked, lease)
        except UnknownLeaseError:
            log.warning("session missing action=copy-out session_id=%s", session_id)
            return JSONResponse(_NOT_FOUND, status_code=404)
        finally:
            store.release(lease)
        log.info("copy-out session_id=%s bytes=%s", session_id, len(payload))
        return Response(payload, media_type="application/gzip")

    async def exec_code(request: Request) -> Response:
        session_id = request.path_params["id"]
        acquired = await _acquire(request, "exec")
        if isinstance(acquired, Response):
            return acquired
        lease = acquired
        try:
            try:
                payload = await request.json()
            except Exception:
                log.warning("exec rejected session_id=%s error=invalid json", session_id)
                return JSONResponse({"error": "invalid json"}, status_code=400)
            try:
                result = await _run(exec_limiter, handle_exec, store, lease, payload)
            except UnknownLeaseError:
                log.warning("session missing action=exec session_id=%s", session_id)
                return JSONResponse(_NOT_FOUND, status_code=404)
        finally:
            store.release(lease)
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
