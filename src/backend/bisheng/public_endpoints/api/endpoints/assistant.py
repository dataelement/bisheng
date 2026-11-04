"""Published assistant HTTP and WebSocket adapters."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, WebSocket
from fastapi import status as http_status
from loguru import logger

from bisheng.api.v1.chat import chat_manager
from bisheng.assistant.domain.services.published_assistant_service import PublishedAssistantService
from bisheng.common.chat.types import WorkType
from bisheng.common.errcode.public_endpoints import PublicAccessError
from bisheng.common.schemas.api import resp_200
from bisheng.public_endpoints.api.exception_handlers import deny_public_websocket
from bisheng.public_endpoints.domain.services.guest_policy import public_execution

router = APIRouter(prefix="/assistant", tags=["PublicAPI", "Assistant"])


@router.get("/info/{assistant_id}")
async def get_assistant_info(request: Request, assistant_id: UUID):
    del request
    normalized_id = assistant_id.hex
    async with public_execution("assistant", normalized_id) as execution:
        data = await PublishedAssistantService.get_info(normalized_id, execution.operator)
        # The anonymous channel exposes no way to create a share link, and a
        # super-admin operator would short-circuit the check to True. Reporting
        # that to a visitor is misleading and leaks whether the app is shareable.
        return resp_200(data=data.model_copy(update={"can_share": False}))


@router.websocket("/chat/{assistant_id}")
async def assistant_ws(*, websocket: WebSocket, assistant_id: str, chat_id: str | None = None):
    try:
        normalized_id = UUID(assistant_id).hex
        async with public_execution("assistant", normalized_id) as execution:
            await PublishedAssistantService.validate_websocket_session(
                assistant_id=normalized_id,
                chat_id=chat_id,
                session_subject=execution.session_subject,
            )
            await chat_manager.dispatch_client(
                websocket,
                normalized_id,
                chat_id,
                execution.operator,
                WorkType.GPTS,
                websocket,
                session_subject=execution.session_subject,
            )
    except PublicAccessError as exc:
        await deny_public_websocket(websocket, exc)
    except Exception as exc:
        logger.opt(exception=True).error("public assistant websocket failed")
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
