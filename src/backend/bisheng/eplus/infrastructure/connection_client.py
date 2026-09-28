"""Production WebSocket client for the customer-verified E+ protocol."""

from __future__ import annotations

import asyncio
import inspect
import json
import secrets
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from loguru import logger
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from bisheng.eplus.infrastructure.protocol import (
    EPlusProtocolError,
    build_ping_frame,
    build_subscribe_frame,
    sanitize_for_log,
)

FrameHandler = Callable[[dict[str, Any]], None | Awaitable[None]]
EventSink = Callable[[str, dict[str, Any]], None]


class EPlusSubscriptionError(RuntimeError):
    """E+ rejected the robot subscription."""


class EPlusConnectionExitReason(StrEnum):
    DISCONNECTED = "disconnected"
    TAKEN_OVER = "taken_over"


@dataclass(frozen=True, slots=True)
class EPlusConnectionConfig:
    url: str
    bot_id: str
    secret: str
    ca_pem: bytes | None = None
    heartbeat_interval_seconds: float = 30.0
    ack_timeout_seconds: float = 5.0
    connect_timeout_seconds: float = 10.0
    close_timeout_seconds: float = 5.0
    max_frame_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise ValueError("E+ URL must be an absolute ws:// or wss:// URL")
        if not self.bot_id or not self.secret:
            raise ValueError("E+ bot_id and secret are required")
        if (
            self.heartbeat_interval_seconds <= 0
            or self.ack_timeout_seconds <= 0
            or self.connect_timeout_seconds <= 0
            or self.close_timeout_seconds <= 0
            or self.max_frame_bytes <= 0
        ):
            raise ValueError("E+ connection timeouts and frame limit must be positive")


@dataclass(slots=True)
class _RequestGate:
    lock: asyncio.Lock
    users: int = 0


class EPlusConnectionClient:
    """Own one subscribed E+ WebSocket and correlate protocol ACK frames."""

    def __init__(
        self,
        config: EPlusConnectionConfig,
        *,
        on_message: FrameHandler | None = None,
        on_event: FrameHandler | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.config = config
        self._on_message = on_message
        self._on_event = on_event
        self._event_sink = event_sink
        self._websocket: ClientConnection | None = None
        self._pending_acks: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._request_gates: dict[str, _RequestGate] = {}
        self._message_tasks: set[asyncio.Task[None]] = set()
        self._authenticated = asyncio.Event()
        self._taken_over = False
        self._ssl_context = self._build_ssl_context()

    async def wait_authenticated(self) -> None:
        await self._authenticated.wait()

    async def run_connection_once(self) -> EPlusConnectionExitReason:
        """Connect, authenticate, serve callbacks, and return one exit reason."""

        parsed = urlsplit(self.config.url)
        self._taken_over = False
        self._authenticated.clear()
        self._emit(
            "connection.opening",
            url=self.config.url,
            bot_id=self.config.bot_id,
            tls=parsed.scheme == "wss",
        )
        connect_kwargs: dict[str, Any] = {
            "ping_interval": None,
            "open_timeout": self.config.connect_timeout_seconds,
            "close_timeout": self.config.close_timeout_seconds,
            "max_size": self.config.max_frame_bytes,
        }
        if parsed.scheme == "wss":
            connect_kwargs["ssl"] = self._ssl_context

        receiver_task: asyncio.Task[None] | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            async with connect(self.config.url, **connect_kwargs) as websocket:
                self._websocket = websocket
                self._emit("connection.opened")
                receiver_task = asyncio.create_task(self._receive_loop(websocket))

                req_id = _new_req_id("aibot_subscribe")
                ack = await self.send_with_ack(build_subscribe_frame(self.config.bot_id, self.config.secret, req_id))
                if _ack_error(ack):
                    raise EPlusSubscriptionError(
                        f"E+ subscription rejected with errcode={ack.get('errcode')}"
                    )
                self._authenticated.set()
                self._emit("subscription.authenticated", req_id=req_id, bot_id=self.config.bot_id)

                heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                try:
                    await receiver_task
                except ConnectionClosed:
                    self._emit(
                        "connection.closed",
                        code=websocket.close_code,
                        reason=websocket.close_reason,
                    )
        finally:
            await _cancel_task(heartbeat_task)
            await _cancel_task(receiver_task)
            await self._finish_message_tasks()
            self._fail_pending_acks(ConnectionError("E+ connection closed before ACK"))
            self._authenticated.clear()
            self._request_gates.clear()
            self._websocket = None

        reason = EPlusConnectionExitReason.TAKEN_OVER if self._taken_over else EPlusConnectionExitReason.DISCONNECTED
        self._emit("connection.ended", reason=reason.value)
        return reason

    async def close(self) -> None:
        websocket = self._websocket
        if websocket is not None:
            await websocket.close(code=1000, reason="E+ worker stopping")

    async def send_with_ack(self, frame: dict[str, Any]) -> dict[str, Any]:
        websocket = self._websocket
        if websocket is None:
            raise ConnectionError("E+ WebSocket is not connected")
        req_id = _frame_req_id(frame)
        gate = self._request_gates.setdefault(req_id, _RequestGate(asyncio.Lock()))
        gate.users += 1
        try:
            async with gate.lock:
                if req_id in self._pending_acks:
                    raise EPlusProtocolError(f"an ACK is already pending for req_id={req_id}")
                future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
                self._pending_acks[req_id] = future
                try:
                    self._emit("frame.outbound", cmd=frame.get("cmd"), req_id=req_id)
                    await websocket.send(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))
                    return await asyncio.wait_for(future, timeout=self.config.ack_timeout_seconds)
                finally:
                    self._pending_acks.pop(req_id, None)
        finally:
            gate.users -= 1
            if gate.users == 0 and self._request_gates.get(req_id) is gate:
                self._request_gates.pop(req_id, None)

    async def _receive_loop(self, websocket: ClientConnection) -> None:
        async for raw_frame in websocket:
            frame = _decode_frame(raw_frame)
            self._emit(
                "frame.inbound",
                cmd=frame.get("cmd"),
                req_id=_optional_req_id(frame),
                errcode=frame.get("errcode"),
            )
            cmd = frame.get("cmd")
            if not cmd:
                self._resolve_ack(frame)
            elif cmd == "aibot_msg_callback":
                self._spawn_message_task(frame)
            elif cmd == "aibot_event_callback":
                await self._handle_event(frame)
            else:
                self._emit("frame.unsupported", cmd=cmd)

    async def _handle_event(self, frame: dict[str, Any]) -> None:
        if self._on_event is not None:
            await _invoke_handler(self._on_event, frame)
        body = frame.get("body")
        event = body.get("event") if isinstance(body, Mapping) else None
        event_type = event.get("eventtype") if isinstance(event, Mapping) else None
        self._emit("event.received", event_type=event_type)
        if event_type == "disconnected_event":
            self._taken_over = True
            self._emit("connection.taken_over")
            websocket = self._websocket
            if websocket is not None:
                await websocket.close(code=1000, reason="replaced by another E+ connection")

    def _spawn_message_task(self, frame: dict[str, Any]) -> None:
        if self._on_message is None:
            return
        task = asyncio.create_task(_invoke_handler(self._on_message, frame))
        self._message_tasks.add(task)
        task.add_done_callback(self._message_task_done)

    def _message_task_done(self, task: asyncio.Task[None]) -> None:
        self._message_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._emit("message.handler_failed", error_type=type(exception).__name__)

    async def _finish_message_tasks(self) -> None:
        if not self._message_tasks:
            return
        tasks = tuple(self._message_tasks)
        done, pending = await asyncio.wait(tasks, timeout=0.2)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                self._emit("message.handler_failed", error_type=type(task.exception()).__name__)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._message_tasks.clear()

    async def _heartbeat_loop(self) -> None:
        failures = 0
        while True:
            await asyncio.sleep(self.config.heartbeat_interval_seconds)
            req_id = _new_req_id("ping")
            try:
                ack = await self.send_with_ack(build_ping_frame(req_id))
                if _ack_error(ack):
                    raise ConnectionError(f"E+ heartbeat rejected with errcode={ack.get('errcode')}")
                failures = 0
                self._emit("heartbeat.ok", req_id=req_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                self._emit("heartbeat.failed", failures=failures, error_type=type(exc).__name__)
                if failures >= 2:
                    websocket = self._websocket
                    if websocket is not None:
                        await websocket.close(code=1011, reason="heartbeat ACK failed twice")
                    return

    def _resolve_ack(self, frame: dict[str, Any]) -> None:
        req_id = _optional_req_id(frame)
        if req_id is None:
            self._emit("ack.missing_req_id")
            return
        future = self._pending_acks.get(req_id)
        if future is None or future.done():
            self._emit("ack.unmatched", req_id=req_id)
            return
        future.set_result(frame)

    def _fail_pending_acks(self, exception: Exception) -> None:
        for future in self._pending_acks.values():
            if not future.done():
                future.set_exception(exception)
        self._pending_acks.clear()

    def _build_ssl_context(self) -> ssl.SSLContext:
        if self.config.ca_pem is None:
            return ssl.create_default_context()
        try:
            ca_text = self.config.ca_pem.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("E+ CA must be ASCII PEM") from exc
        return ssl.create_default_context(cadata=ca_text)

    def _emit(self, event: str, **fields: Any) -> None:
        safe_fields = sanitize_for_log(fields, secrets=(self.config.secret,))
        if self._event_sink is not None:
            self._event_sink(event, safe_fields)
        logger.bind(eplus_event=event, **safe_fields).info("E+ connection event")


def _decode_frame(raw_frame: str | bytes) -> dict[str, Any]:
    if isinstance(raw_frame, bytes):
        try:
            raw_frame = raw_frame.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EPlusProtocolError("E+ frame is not valid UTF-8") from exc
    try:
        frame = json.loads(raw_frame)
    except json.JSONDecodeError as exc:
        raise EPlusProtocolError("E+ frame is not valid JSON") from exc
    if not isinstance(frame, dict):
        raise EPlusProtocolError("E+ frame must be a JSON object")
    return frame


def _frame_req_id(frame: Mapping[str, Any]) -> str:
    req_id = _optional_req_id(frame)
    if req_id is None:
        raise EPlusProtocolError("outbound frame requires headers.req_id")
    return req_id


def _optional_req_id(frame: Mapping[str, Any]) -> str | None:
    headers = frame.get("headers")
    req_id = headers.get("req_id") if isinstance(headers, Mapping) else None
    return req_id if isinstance(req_id, str) and req_id else None


def _ack_error(ack: Mapping[str, Any]) -> bool:
    try:
        return int(ack.get("errcode", -1)) != 0
    except (TypeError, ValueError):
        return True


async def _invoke_handler(handler: FrameHandler, frame: dict[str, Any]) -> None:
    result = handler(frame)
    if inspect.isawaitable(result):
        await result


async def _cancel_task(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _new_req_id(command: str) -> str:
    return f"{command}_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
