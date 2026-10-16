"""Authenticated workbench audio sessions; frontend states remain start/pause."""

import asyncio
import json
import time
import uuid
from urllib.parse import urlsplit

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.server import NoAsrModelConfigError
from bisheng.core.ai.asr.realtime import RealtimeASRClient
from bisheng.llm.domain.services.llm import LLMService

SESSION_LIMIT_SECONDS = 600
MAX_FRAME_BYTES = 32000


def _browser_host(headers) -> str:
    """Host the browser used, not the upstream the dev proxy rewrote it to."""
    forwarded = headers.get("x-forwarded-host")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return headers.get("host") or ""


async def run_realtime_asr(websocket: WebSocket, login_user):
    origin = websocket.headers.get("origin")
    if origin and urlsplit(origin).netloc != _browser_host(websocket.headers):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session_id = uuid.uuid4().hex
    try:
        start = await asyncio.wait_for(websocket.receive_json(), 10)
        if start.get("type") != "start":
            raise ValueError("ASR session requires a start event")
        config = await LLMService.get_workbench_llm()
        if not config.asr_model or not config.asr_model.id:
            raise NoAsrModelConfigError()
        if str(start.get("model_id")) != str(config.asr_model.id):
            raise ValueError("ASR configuration changed; refresh before starting")
        asr = await LLMService.get_bisheng_asr(
            model_id=int(config.asr_model.id),
            app_id=ApplicationTypeEnum.ASR.value,
            app_name=ApplicationTypeEnum.ASR.value,
            app_type=ApplicationTypeEnum.ASR,
            user_id=login_user.user_id,
        )
        if not isinstance(asr.asr, RealtimeASRClient):
            raise ValueError("The configured model uses file recognition")

        async def ready():
            await websocket.send_json({"type": "ready", "session_id": session_id, "sample_rate": 16000})

        async def forward(event):
            await websocket.send_json({**event, "session_id": session_id})

        async def audio():
            started = time.monotonic()
            total_bytes = 0
            while True:
                remaining = SESSION_LIMIT_SECONDS - (time.monotonic() - started)
                if remaining <= 0 or total_bytes >= SESSION_LIMIT_SECONDS * 32000:
                    await websocket.send_json({"type": "limit_reached", "session_id": session_id})
                    return
                try:
                    message = await asyncio.wait_for(websocket.receive(), min(remaining, 30))
                except TimeoutError:
                    if remaining <= 30:
                        await websocket.send_json({"type": "limit_reached", "session_id": session_id})
                        return
                    raise ValueError("Audio input timed out") from None
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect()
                pcm = message.get("bytes")
                if pcm is not None:
                    if len(pcm) > MAX_FRAME_BYTES or len(pcm) % 2:
                        raise ValueError("Invalid PCM audio frame")
                    total_bytes += len(pcm)
                    if total_bytes > (time.monotonic() - started + 5) * 32000:
                        raise ValueError("Audio input exceeds realtime rate")
                    yield pcm
                elif message.get("text"):
                    event = json.loads(message["text"])
                    if event.get("type") == "stop":
                        return
                    raise ValueError("Invalid ASR control event")

        await asr.astream(audio(), ready, forward)
        await websocket.send_json({"type": "completed", "session_id": session_id})
    except WebSocketDisconnect:
        logger.info("ASR client disconnected session={} user={}", session_id, login_user.user_id)
    except Exception as exc:
        logger.exception("ASR session failed session={} user={}", session_id, login_user.user_id)
        try:
            await websocket.send_json({"type": "error", "code": exc.code if isinstance(exc, BaseErrorCode) else 0})
        except (WebSocketDisconnect, RuntimeError, OSError):
            # The browser may already have left; cleanup still runs below.
            logger.debug("ASR error recipient disconnected session={}", session_id)
    finally:
        try:
            await websocket.close()
        except (WebSocketDisconnect, RuntimeError, OSError):
            # Closing an already disconnected browser is best-effort cleanup.
            logger.debug("ASR socket already closed session={}", session_id)
