"""Bind a desktop to the signed-in account and relay phone RPC across workers."""

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from urllib.parse import quote
from uuid import uuid4

from loguru import logger
from redis.exceptions import RedisError
from starlette.websockets import WebSocketDisconnect

from bisheng.dsh.domain.schemas.mobile import DESKTOP_ID_PATTERN, parse_bind, parse_rpc, parse_unbind
from bisheng.dsh.infrastructure.mobile_access import MobileAccessStore

_EMPTY_SECRET_HASH = hashlib.sha256(b"").hexdigest()
_FAILURE_LIMIT = 8


class MobileResult:
    def __init__(self, status: int, body: dict | str, *, raw: bool = False, media_type: str | None = None):
        self.status = status
        self.body = body
        self.raw = raw
        self.media_type = media_type


class MobileAccessRuntime:
    def __init__(self):
        self.attachments = 0
        self.streams = 0
        self.pending: dict[str, dict[str, float]] = {}
        self.stream_requests: set[str] = set()
        self.lock = asyncio.Lock()


class MobileStream:
    """One relayed desktop stream.

    ``close`` deletes the response key, tells the desktop to stop its follow,
    and frees the per-process stream slot. The body generator does not do it:
    a phone that leaves mid-stream cancels the generator, and an unshielded
    cleanup inside it would be cancelled with it, leaving the desktop follow
    open for the whole stream deadline. The caller runs ``close`` under
    ``asyncio.shield`` instead.
    """

    def __init__(self, status: int, media_type: str, body: AsyncIterator[str], close):
        self.status = status
        self.media_type = media_type
        self.body = body
        self.close = close


class MobileAccessService:
    def __init__(
        self,
        store: MobileAccessStore,
        runtime: MobileAccessRuntime | None = None,
        *,
        rpc_timeout: float = 35,
        blpop_timeout: float = 5,
        online_ttl: int = 60,
        max_attach: int = 32,
        max_pending: int = 128,
        stream_timeout: float = 3600,
        keepalive_interval: float = 15,
        max_streams: int = 64,
    ):
        self.store = store
        self.runtime = runtime or MobileAccessRuntime()
        self.rpc_timeout = rpc_timeout
        self.blpop_timeout = blpop_timeout
        self.online_ttl = online_ttl
        self.max_attach = max_attach
        self.max_pending = max_pending
        self.stream_timeout = stream_timeout
        self.keepalive_interval = keepalive_interval
        self.max_streams = max_streams

    async def bind(self, user, body: dict) -> MobileResult:
        parsed = parse_bind(body)
        if parsed is None:
            return _invalid()
        desktop_id, secret, display_name = parsed
        tenant_id, user_id = _decimal(user.tenant_id), _decimal(user.user_id)
        try:
            status, previous, previous_tenant, previous_user = await self.store.bind(
                desktop_id, tenant_id, user_id, display_name, _secret_hash(secret)
            )
            if status == 0:
                return MobileResult(409, {"error": "desktop_conflict"})
            if previous_tenant and (previous_tenant != tenant_id or previous_user != user_id):
                await self.store.remove_index(previous_tenant, previous_user, desktop_id)
            await self.store.add_index(tenant_id, user_id, desktop_id)
            if previous:
                await self.store.push_request(desktop_id, previous, {"kind": "disconnect"})
        except RedisError:
            logger.exception("mobile bind failed desktop={}", desktop_id)
            return _unavailable()
        return MobileResult(200, {"ok": True})

    async def unbind(self, user, body: dict) -> MobileResult:
        desktop_id = parse_unbind(body)
        if desktop_id is None:
            return _invalid()
        try:
            status, previous = await self.store.unbind(desktop_id, _decimal(user.tenant_id), _decimal(user.user_id))
            if status == 0:
                return MobileResult(404, {"error": "not_found"})
            await self.store.remove_index(_decimal(user.tenant_id), _decimal(user.user_id), desktop_id)
            if previous:
                await self.store.push_request(desktop_id, previous, {"kind": "disconnect"})
        except RedisError:
            logger.exception("mobile unbind failed desktop={}", desktop_id)
            return _unavailable()
        return MobileResult(200, {"ok": True})

    async def list_desktops(self, user) -> MobileResult:
        tenant_id, user_id = _decimal(user.tenant_id), _decimal(user.user_id)
        try:
            desktops = []
            for desktop_id in await self.store.desktop_ids(tenant_id, user_id):
                record = await self.store.read(desktop_id)
                if record is None:
                    await self.store.remove_index(tenant_id, user_id, desktop_id)
                    continue
                if record.tenant_id != tenant_id or record.user_id != user_id:
                    await self.store.remove_index(tenant_id, user_id, desktop_id)
                    continue
                desktops.append(
                    {
                        "desktopId": desktop_id,
                        "displayName": record.display_name,
                        "online": bool(await self.store.current_connection(desktop_id)),
                    }
                )
        except RedisError:
            logger.exception("mobile desktop list failed")
            return _unavailable()
        return MobileResult(200, {"desktops": desktops})

    async def rpc(self, user, desktop_id: str, body: dict) -> MobileResult:
        parsed = parse_rpc(body)
        if parsed is None or DESKTOP_ID_PATTERN.fullmatch(desktop_id or "") is None:
            return _invalid()
        method, payload = parsed
        tenant_id, user_id = _decimal(user.tenant_id), _decimal(user.user_id)
        try:
            record = await self.store.read(desktop_id)
            if record is None or record.tenant_id != tenant_id or record.user_id != user_id:
                return MobileResult(404, {"error": "not_found"})
            connection_id = await self.store.current_connection(desktop_id)
            if not connection_id:
                return MobileResult(503, {"error": "offline"})
            request_id = str(uuid4())
            deadline = time.time() + self.rpc_timeout
            await self.store.push_request(
                desktop_id,
                connection_id,
                {
                    "kind": "rpc",
                    "id": request_id,
                    "deadline": deadline,
                    "body": json.dumps({"method": method, "payload": payload}, separators=(",", ":")),
                    "userId": user_id,
                    "tenantId": tenant_id,
                },
            )
            while time.time() < deadline:
                remaining = deadline - time.time()
                message = await self.store.pop_response(desktop_id, request_id, min(self.blpop_timeout, remaining))
                if message:
                    return _relayed(message)
                if await self.store.current_connection(desktop_id) != connection_id:
                    break
        except RedisError:
            logger.exception("mobile rpc failed desktop={}", desktop_id)
            return _unavailable()
        return MobileResult(503, {"error": "offline"})

    async def open_session_stream(self, user, desktop_id: str, session_id: str | None, view: str | None):
        checked = _session_id(session_id)
        if (
            checked is None
            or (view is not None and view != "transcript")
            or DESKTOP_ID_PATTERN.fullmatch(desktop_id or "") is None
        ):
            return _invalid()
        tenant_id, user_id = _decimal(user.tenant_id), _decimal(user.user_id)
        try:
            record = await self.store.read(desktop_id)
            if record is None or record.tenant_id != tenant_id or record.user_id != user_id:
                return MobileResult(404, {"error": "not_found"})
            connection_id = await self.store.current_connection(desktop_id)
            if not connection_id:
                return MobileResult(503, {"error": "offline"})
            if not await self._acquire_stream():
                return MobileResult(503, {"error": "busy"})
        except RedisError:
            logger.exception("mobile stream open failed desktop={}", desktop_id)
            return _unavailable()
        request_id = str(uuid4())
        path = f"/api/v1/session/stream?sessionId={quote(checked, safe='')}"
        if view == "transcript":
            path += "&view=transcript"
        finished = False
        handed_off = False

        async def close() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            await self._finish_stream(desktop_id, connection_id, request_id)

        try:
            await self.store.open_stream(desktop_id, request_id, max(1, int(self.stream_timeout) + 11))
            await self.store.push_request(
                desktop_id,
                connection_id,
                {
                    "kind": "stream",
                    "id": request_id,
                    "deadline": time.time() + self.stream_timeout,
                    "method": "GET",
                    "path": path,
                    "userId": user_id,
                    "tenantId": tenant_id,
                },
            )
            first = await self._first_stream_frame(desktop_id, request_id, connection_id)
            if first is None:
                return MobileResult(503, {"error": "offline"})
            if first.get("type") == "response":
                return _relayed(first)
            if first.get("type") == "response-error":
                return MobileResult(503, {"error": "busy"})
            status = first.get("status")
            if type(status) is not int or not 100 <= status <= 599:
                status = 200
            media_type = first.get("contentType") if isinstance(first.get("contentType"), str) else "text/event-stream"
            stream = MobileStream(
                status,
                media_type,
                self._follow_stream(desktop_id, connection_id, request_id),
                close,
            )
            handed_off = True
            return stream
        except RedisError:
            logger.exception("mobile stream dispatch failed desktop={}", desktop_id)
            return _unavailable()
        finally:
            # Before the StreamingResponse owns cleanup, cancellation and all
            # failed-open paths must release the slot and stop the desktop follow.
            if not handed_off:
                await asyncio.shield(close())

    async def _first_stream_frame(self, desktop_id: str, request_id: str, connection_id: str) -> dict | None:
        deadline = time.time() + 10
        while time.time() < deadline:
            remaining = deadline - time.time()
            message = await self.store.pop_response(
                desktop_id, request_id, min(self.blpop_timeout, remaining), stream=True
            )
            if message:
                return message
            if await self.store.current_connection(desktop_id) != connection_id:
                return None
        return None

    async def _follow_stream(self, desktop_id: str, connection_id: str, request_id: str) -> AsyncIterator[str]:
        yield ": keep-alive\n\n"
        deadline = time.time() + self.stream_timeout
        # A desktop chunk boundary is not an SSE event boundary: one event can
        # arrive in two chunks. Writing a comment between them would make the
        # phone read it as part of that event's data and drop the increment.
        at_boundary = True
        while time.time() < deadline:
            remaining = deadline - time.time()
            try:
                message = await self.store.pop_response(
                    desktop_id, request_id, min(self.keepalive_interval, remaining), stream=True
                )
            except RedisError:
                # A cluster failover outlives the client's own retries. End the
                # stream with a readable event so the phone reconnects with
                # backoff instead of waiting on a stream that never resumes.
                logger.exception("mobile stream read failed desktop={}", desktop_id)
                yield 'event: error\ndata: {"error":"unavailable"}\n\n'
                return
            if message is None:
                if await self.store.current_connection(desktop_id) != connection_id:
                    yield 'event: error\ndata: {"error":"offline"}\n\n'
                    return
                if at_boundary:
                    yield ": keep-alive\n\n"
                continue
            frame_type = message.get("type")
            if frame_type == "response-error":
                prefix = "" if at_boundary else "\n\n"
                yield prefix + 'event: error\ndata: {"error":"busy"}\n\n'
                return
            if frame_type == "response-chunk" and isinstance(message.get("data"), str):
                data = message["data"]
                if data:
                    at_boundary = data.endswith("\n\n")
                    yield data
                continue
            if frame_type in {"response-end", "response"}:
                return

    async def _finish_stream(self, desktop_id: str, connection_id: str, request_id: str) -> None:
        try:
            try:
                await self.store.close_stream(desktop_id, request_id)
            except RedisError:
                logger.warning("mobile stream response cleanup failed desktop={}", desktop_id)
            try:
                await self.store.push_request(desktop_id, connection_id, {"kind": "cancel", "id": request_id})
            except RedisError:
                logger.warning("mobile stream cancel failed desktop={}", desktop_id)
        finally:
            await self._release_stream()

    async def _acquire_stream(self) -> bool:
        async with self.runtime.lock:
            if self.runtime.streams >= self.max_streams:
                return False
            self.runtime.streams += 1
            return True

    async def _release_stream(self) -> None:
        async with self.runtime.lock:
            self.runtime.streams = max(0, self.runtime.streams - 1)

    async def attach(self, socket, client_ip: str) -> None:
        await socket.accept()
        acquired = False
        desktop_id = ""
        connection_id = ""
        try:
            frame = await self._first_frame(socket)
            if frame is None:
                await self._reject(socket)
                return
            desktop_id = frame.get("desktopId")
            secret = frame.get("attachSecret")
            if not isinstance(desktop_id, str) or not isinstance(secret, str):
                await self._reject(socket)
                return
            if await self._limited(client_ip, desktop_id) or not await self._authorized(desktop_id, secret, client_ip):
                await self._reject(socket)
                return
            async with self.runtime.lock:
                if self.runtime.attachments >= self.max_attach:
                    over_capacity = True
                else:
                    self.runtime.attachments += 1
                    acquired = True
                    over_capacity = False
            if over_capacity:
                await self._reject(socket)
                return
            connection_id = uuid4().hex
            record = await self.store.read(desktop_id)
            previous = (
                None
                if record is None
                else await self.store.activate(desktop_id, _secret_hash(secret), connection_id, self.online_ttl)
            )
            if previous is None:
                await self._reject(socket)
                return
            if previous:
                await self.store.push_request(desktop_id, previous, {"kind": "disconnect"})
            self.runtime.pending[connection_id] = {}
            await self._relay(socket, desktop_id, connection_id)
        except RedisError:
            logger.exception("mobile attach failed desktop={}", desktop_id)
            await self._reject(socket)
        finally:
            if connection_id:
                self.runtime.stream_requests.difference_update(self.runtime.pending.pop(connection_id, {}))
                try:
                    await self.store.clear_if_current(desktop_id, connection_id)
                except RedisError:
                    logger.warning("mobile online cleanup failed desktop={}", desktop_id)
            if acquired:
                async with self.runtime.lock:
                    self.runtime.attachments -= 1
            try:
                await socket.close()
            except Exception:
                logger.info("mobile attach close finished desktop={}", desktop_id)

    async def _relay(self, socket, desktop_id: str, connection_id: str) -> None:
        receive_task = asyncio.create_task(self._receive(socket, desktop_id, connection_id))
        dispatch_task = asyncio.create_task(self._dispatch(socket, desktop_id, connection_id))
        done, pending_tasks = await asyncio.wait({receive_task, dispatch_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending_tasks:
            task.cancel()
        outcomes = await asyncio.gather(*done, *pending_tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.opt(exception=outcome).error("mobile attach relay ended desktop={}", desktop_id)

    async def _receive(self, socket, desktop_id: str, connection_id: str) -> None:
        try:
            while True:
                frame = await socket.receive_json()
                if not isinstance(frame, dict):
                    continue
                frame_type = frame.get("type")
                if frame_type == "ping":
                    if not await self.store.refresh(desktop_id, connection_id, self.online_ttl):
                        return
                elif frame_type == "response":
                    await self._accept_response(socket, desktop_id, connection_id, frame)
                elif frame_type in {"response-start", "response-chunk", "response-end"}:
                    await self._accept_stream_frame(desktop_id, connection_id, frame)
        except (WebSocketDisconnect, RuntimeError, TypeError, ValueError):
            logger.info("mobile attach receive ended desktop={}", desktop_id)

    async def _dispatch(self, socket, desktop_id: str, connection_id: str) -> None:
        try:
            while True:
                pending = self.runtime.pending.setdefault(connection_id, {})
                now = time.time()
                for request_id, deadline in list(pending.items()):
                    if deadline <= now:
                        pending.pop(request_id, None)
                        self.runtime.stream_requests.discard(request_id)
                # Wake even on an idle connection so unanswered RPCs cannot accumulate.
                message = await self.store.pop_request(desktop_id, connection_id, min(self.blpop_timeout, 1))
                if message is None:
                    if await self.store.current_connection(desktop_id) != connection_id:
                        return
                    continue
                kind = message.get("kind")
                if kind == "disconnect":
                    return
                if kind == "cancel":
                    request_id = message.get("id")
                    if isinstance(request_id, str):
                        pending.pop(request_id, None)
                        self.runtime.stream_requests.discard(request_id)
                        await socket.send_json({"type": "cancel", "id": request_id})
                    continue
                if kind not in {"rpc", "stream"}:
                    continue
                deadline = message.get("deadline")
                request_id = message.get("id")
                if not isinstance(deadline, (int, float)) or deadline <= time.time() or not isinstance(request_id, str):
                    logger.info("drop expired mobile rpc desktop={}", desktop_id)
                    continue
                if await self.store.current_connection(desktop_id) != connection_id:
                    logger.info("drop stale mobile rpc desktop={}", desktop_id)
                    continue
                # The blocking pop may have outlived another pending request.
                now = time.time()
                for pending_id, pending_deadline in list(pending.items()):
                    if pending_deadline <= now:
                        pending.pop(pending_id, None)
                        self.runtime.stream_requests.discard(pending_id)
                if len(pending) >= self.max_pending:
                    # "response" marks this as the whole reply. Without it the
                    # stream opener would take a busy frame for a first chunk
                    # and hand the phone a 503 body that never ends.
                    await self.store.push_response(
                        desktop_id,
                        request_id,
                        {
                            "type": "response",
                            "status": 503,
                            "body": '{"error":"busy"}',
                            "contentType": "application/json",
                        },
                    )
                    continue
                pending[request_id] = deadline
                request = {
                    "type": "request",
                    "id": request_id,
                    "headers": {
                        "x-dsh-user-id": message.get("userId") if isinstance(message.get("userId"), str) else "",
                        "x-dsh-tenant-id": message.get("tenantId") if isinstance(message.get("tenantId"), str) else "",
                    },
                }
                if kind == "stream":
                    self.runtime.stream_requests.add(request_id)
                    request["method"] = message.get("method") if isinstance(message.get("method"), str) else "GET"
                    request["path"] = message.get("path") if isinstance(message.get("path"), str) else ""
                    # No body key at all: the desktop passes any string it gets
                    # to fetch, and fetch rejects a GET carrying a body, even "".
                else:
                    request["method"] = "POST"
                    request["path"] = "/api/v1/rpc"
                    request["body"] = message.get("body") if isinstance(message.get("body"), str) else ""
                await socket.send_json(request)
        except (WebSocketDisconnect, RuntimeError):
            logger.info("mobile attach dispatch ended desktop={}", desktop_id)

    async def _accept_response(self, socket, desktop_id: str, connection_id: str, frame: dict) -> None:
        del socket
        request_id = frame.get("id")
        pending = self.runtime.pending.get(connection_id, {})
        deadline = pending.pop(request_id, None) if isinstance(request_id, str) else None
        streaming = request_id in self.runtime.stream_requests if isinstance(request_id, str) else False
        if deadline is not None:
            self.runtime.stream_requests.discard(request_id)
        if deadline is None or deadline <= time.time():
            logger.info("ignore mobile response desktop={}", desktop_id)
            return
        status = frame.get("status")
        if type(status) is not int or not 100 <= status <= 599:
            status = 502
        headers = frame.get("headers") if isinstance(frame.get("headers"), dict) else {}
        content_type = headers.get("content-type") or headers.get("Content-Type") or "application/json"
        if not isinstance(content_type, str):
            content_type = "application/json"
        body = frame.get("body") if isinstance(frame.get("body"), str) else ""
        message = {"type": "response", "status": status, "body": body, "contentType": content_type}
        if streaming:
            await self._queue_stream_frame(desktop_id, connection_id, request_id, message)
        else:
            await self.store.push_response(desktop_id, request_id, message)

    async def _accept_stream_frame(self, desktop_id: str, connection_id: str, frame: dict) -> None:
        request_id = frame.get("id")
        pending = self.runtime.pending.get(connection_id, {})
        if not isinstance(request_id, str):
            return
        deadline = pending.get(request_id)
        if deadline is None or deadline <= time.time():
            logger.info("ignore mobile stream frame desktop={}", desktop_id)
            return
        frame_type = frame.get("type")
        message: dict = {"type": frame_type}
        if frame_type == "response-start":
            status = frame.get("status")
            message["status"] = status if type(status) is int else 200
            headers = frame.get("headers") if isinstance(frame.get("headers"), dict) else {}
            content_type = headers.get("content-type") or headers.get("Content-Type") or "text/event-stream"
            message["contentType"] = content_type if isinstance(content_type, str) else "text/event-stream"
        elif frame_type == "response-chunk":
            message["data"] = frame.get("data") if isinstance(frame.get("data"), str) else ""
        elif frame_type == "response-end":
            pending.pop(request_id, None)
            self.runtime.stream_requests.discard(request_id)
        else:
            return
        await self._queue_stream_frame(desktop_id, connection_id, request_id, message)

    async def _queue_stream_frame(self, desktop_id: str, connection_id: str, request_id: str, message: dict) -> None:
        queued = await self.store.push_stream_response(desktop_id, request_id, message)
        if queued <= 0:
            self.runtime.pending.get(connection_id, {}).pop(request_id, None)
            self.runtime.stream_requests.discard(request_id)
        if queued < 0:
            logger.warning("mobile stream response capacity exceeded desktop={} request={}", desktop_id, request_id)
            await self.store.push_request(desktop_id, connection_id, {"kind": "cancel", "id": request_id})

    async def _first_frame(self, socket) -> dict | None:
        try:
            frame = await asyncio.wait_for(socket.receive_json(), timeout=10)
        except (TimeoutError, WebSocketDisconnect, RuntimeError, TypeError, ValueError):
            return None
        return frame if isinstance(frame, dict) and frame.get("type") == "attach" else None

    async def _limited(self, client_ip: str, desktop_id: str) -> bool:
        try:
            return await self.store.failure_count(client_ip, desktop_id) >= _FAILURE_LIMIT
        except RedisError:
            logger.exception("mobile attach rate check failed desktop={}", desktop_id)
            return True

    async def _authorized(self, desktop_id: str, secret: str, client_ip: str) -> bool:
        try:
            if DESKTOP_ID_PATTERN.fullmatch(desktop_id) is None or DESKTOP_ID_PATTERN.fullmatch(secret) is None:
                record = None
                presented = _EMPTY_SECRET_HASH
            else:
                record = await self.store.read(desktop_id)
                presented = _secret_hash(secret)
        except RedisError:
            logger.exception("mobile attach registration read failed desktop={}", desktop_id)
            return False
        expected = record.secret_hash if record is not None else _EMPTY_SECRET_HASH
        if record is None or not hmac.compare_digest(presented, expected):
            try:
                await self.store.record_failure(client_ip, desktop_id)
            except RedisError:
                logger.warning("mobile attach failure count unavailable desktop={}", desktop_id)
            return False
        return True

    async def _reject(self, socket) -> None:
        try:
            await socket.send_json({"type": "rejected"})
        except Exception:
            logger.info("mobile attach rejection could not be sent")
        try:
            await socket.close()
        except Exception:
            logger.info("mobile attach rejection close finished")


def _relayed(message: dict) -> MobileResult:
    status = message.get("status")
    body = message.get("body")
    media_type = message.get("contentType")
    if type(status) is not int or not isinstance(body, str):
        return MobileResult(502, {"error": "invalid_desktop_response"})
    return MobileResult(status, body, raw=True, media_type=media_type if isinstance(media_type, str) else None)


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _decimal(value) -> str:
    if type(value) is not int:
        return ""
    return str(value)


def _session_id(value) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return None
    if any(char in value for char in "\r\n\t ?#&/\\"):
        return None
    return value


def _invalid() -> MobileResult:
    return MobileResult(400, {"error": "invalid_request"})


def _unavailable() -> MobileResult:
    return MobileResult(503, {"error": "unavailable"})
