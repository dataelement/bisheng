"""只观察 ASGI 消息及取消信号，不主动消费请求或改变响应。"""

import asyncio
from time import monotonic

from loguru import logger
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class HttpRequestDiagnosticsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = monotonic()
        response_started = False
        response_completed = False
        disconnect_received = False
        method, path = scope.get("method"), scope.get("path")

        async def observed_receive() -> Message:
            nonlocal disconnect_received
            message = await receive()
            if message["type"] == "http.disconnect" and not disconnect_received:
                disconnect_received = True
                # BaseHTTPMiddleware 也可能生成此消息，不能据此断言客户端主动断开。
                logger.info(
                    "event=http_disconnect_received method={} path={} response_started={} response_completed={} elapsed_ms={:.1f}",
                    method,
                    path,
                    response_started,
                    response_completed,
                    (monotonic() - started_at) * 1000,
                )
            return message

        async def observed_send(message: Message) -> None:
            nonlocal response_started, response_completed
            await send(message)
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.pathsend" or (
                message["type"] == "http.response.body" and not message.get("more_body", False)
            ):
                response_completed = True

        try:
            await self.app(scope, observed_receive, observed_send)
        except asyncio.CancelledError:
            logger.warning(
                "event=http_request_cancelled method={} path={} disconnect_received={} response_started={} response_completed={} elapsed_ms={:.1f}",
                method,
                path,
                disconnect_received,
                response_started,
                response_completed,
                (monotonic() - started_at) * 1000,
            )
            raise
        else:
            if not response_started:
                logger.error(
                    "event=http_no_response method={} path={} disconnect_received={} elapsed_ms={:.1f}",
                    method,
                    path,
                    disconnect_received,
                    (monotonic() - started_at) * 1000,
                )
