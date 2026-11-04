"""Receive bounded signed safety facts independently of model admission."""

from asyncio import CancelledError

from fastapi import APIRouter, Request
from loguru import logger
from starlette.requests import ClientDisconnect

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import (
    DshContentSafetyInvalidEventError,
    DshContentSafetyTooLargeError,
    DshContentSafetyUnavailableError,
)
from bisheng.dsh import content_safety_runtime
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.schemas.content_safety import MAX_EVENT_BYTES, ContentSafetyReceipt

router = APIRouter(route_class=DshRoute)


@router.post("/internal/dsh/content-safety-events", response_model=ContentSafetyReceipt)
async def receive_content_safety_event(request: Request) -> ContentSafetyReceipt:
    # Scope comes only from the signed envelope; query hints cannot override it.
    if request.query_params:
        raise DshContentSafetyInvalidEventError()
    try:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_EVENT_BYTES:
                raise DshContentSafetyTooLargeError()
            body.extend(chunk)
        verified = content_safety_runtime.verify_source(bytes(body), request.headers, request.method, request.url.path)
        service = content_safety_runtime.get_content_safety_service()
        return await service.ingest(verified.raw_event, verified.verified_source)
    except (CancelledError, ClientDisconnect):
        # Disconnect/cancellation stops observation and can never imply an ACK.
        raise
    except BaseErrorCode:
        raise
    except Exception as error:
        # Dependency exceptions may embed SQL, signed facts or credentials.
        logger.warning("DSH content-safety receiver unavailable ({})", type(error).__name__)
        raise DshContentSafetyUnavailableError() from None
