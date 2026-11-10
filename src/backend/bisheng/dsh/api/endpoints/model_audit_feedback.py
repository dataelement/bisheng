"""Authenticated desktop like and dislike updates, without model admission or billing."""

import json

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.dsh import DshInternalErrorError, DshInvalidRequestError
from bisheng.dsh.api.dependencies import get_settings
from bisheng.dsh.api.endpoints.models import desktop_principal
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.repositories.model_audit_feedback import DshModelAuditFeedbackRepository
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.schemas.model_audit_feedback import AuditMessageFeedbackUpdate
from bisheng.dsh.domain.services.model_audit_feedback import DshModelAuditFeedbackService
from bisheng.dsh.domain.services.model_audit_setting import DshModelAuditSettingService
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
from bisheng.dsh.operations_runtime import repository_scope

router = APIRouter(route_class=DshRoute)
_MAX_BODY_BYTES = 16 * 1024


def feedback_service(settings=Depends(get_settings)):
    async def read():
        def load():
            with repository_scope(DshModelAuditSettingRepository) as repository:
                return repository.read()

        return await run_audit_blocking(load)

    modes = DshModelAuditSettingService(read, timeout_seconds=settings.audit_mode_read_timeout_seconds)
    return DshModelAuditFeedbackService(modes, lambda: repository_scope(DshModelAuditFeedbackRepository))


@router.post("/dsh/audit/message-feedback")
async def apply_message_feedback(
    request: Request, principal=Depends(desktop_principal), service=Depends(feedback_service)
):
    if request.url.query or request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise DshInvalidRequestError()
    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > _MAX_BODY_BYTES:
                raise DshInvalidRequestError()
            raw.extend(chunk)
        command = AuditMessageFeedbackUpdate.model_validate(json.loads(raw))
    except (ValueError, ValidationError, UnicodeError, RecursionError):
        raise DshInvalidRequestError() from None
    try:
        return await service.apply(principal, command)
    except (SQLAlchemyError, RuntimeError, TimeoutError) as error:
        logger.warning("DSH audit message feedback unavailable ({})", type(error).__name__)
        raise DshInternalErrorError() from None
