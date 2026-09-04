"""Open API adaptation onto the shared daily-chat implementation."""

from __future__ import annotations

from fastapi import HTTPException

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal
from bisheng.workstation.domain.schemas.chat import APIChatCompletion
from bisheng.workstation.domain.services.workstation_service import WorkStationService


class OpenDailyChatService:
    @classmethod
    async def prepare_request(
        cls,
        *,
        principal: OpenApiPrincipal,
        request: OpenDailyChatCompletionReq,
        login_user,
    ) -> tuple[APIChatCompletion, SessionSubject]:
        subject = session_subject_from_principal(principal)
        await TempUploadService.assert_owned_references(request.files, subject)
        config = await WorkStationService.get_open_api_daily_config(login_user)
        cls._validate_model_and_tools(request, config)
        return request.to_internal(), subject

    @staticmethod
    def _validate_model_and_tools(request: OpenDailyChatCompletionReq, config: dict[str, list]) -> None:
        model_ids = {str(item.get("id")) for item in config.get("models", [])}
        if request.model not in model_ids:
            raise HTTPException(status_code=400, detail="model is not available to this API subject")

        available = {
            (int(child.get("id", 0) or 0), str(child.get("tool_key") or ""))
            for group in config.get("tools", [])
            for child in group.get("children", [])
            if isinstance(child, dict)
        }
        for tool in request.tools or []:
            requested = (int(tool.id or 0), str(tool.tool_key or ""))
            if requested not in available:
                raise HTTPException(status_code=400, detail="tools contains an unavailable tool")

