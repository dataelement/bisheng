"""Published workflow WebSocket adapter."""

from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter, Path, WebSocket
from fastapi import status as http_status
from loguru import logger

from bisheng.api.v1.chat import chat_manager
from bisheng.common.chat.types import WorkType
from bisheng.core.logger import trace_id_var
from bisheng.public_endpoints.domain.services.guest_policy import PublicAccessError, public_execution
from bisheng.workflow.domain.services.published_workflow_service import PublishedWorkflowService

router = APIRouter(prefix="/workflow", tags=["PublicAPI", "Workflow"])


@router.websocket("/chat/{workflow_id}")
async def workflow_ws(
    *,
    workflow_id: UUID = Path(..., description="Workflow UniqueID"),
    websocket: WebSocket,
    chat_id: str | None = None,
):
    normalized_id = workflow_id.hex
    try:
        async with public_execution("workflow", normalized_id) as execution:
            await PublishedWorkflowService.validate_websocket_session(
                workflow_id=normalized_id,
                chat_id=chat_id,
                session_subject=execution.session_subject,
            )
            snapshot = execution.snapshot.model_copy(update={"trace_id": str(trace_id_var.get() or uuid.uuid4().hex)})
            await chat_manager.dispatch_client(
                websocket,
                normalized_id,
                chat_id,
                execution.operator,
                WorkType.WORKFLOW,
                websocket,
                session_subject=execution.session_subject,
                execution_snapshot=snapshot.model_dump(mode="json"),
            )
    except PublicAccessError as exc:
        await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION, reason=exc.message)
    except Exception as exc:
        logger.opt(exception=True).error("public workflow websocket failed")
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
