"""Key-authenticated adapters for daily workstation chat."""

from fastapi import APIRouter, Depends, Request

from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.open_api.api.dependencies import get_open_api_execution
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.daily_chat_service import OpenDailyChatService
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async
from bisheng.workstation.domain.services.chat_service import stream_chat_completion
from bisheng.workstation.domain.services.workstation_service import WorkStationService

router = APIRouter(prefix="/workstation", tags=["OpenAPI", "WorkStation"])


@router.get("/config", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke")
async def get_daily_config(
    _principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    operator = await get_open_api_operator_async()
    return resp_200(data=await WorkStationService.get_open_api_daily_config(operator))


@router.post("/chat/completions")
@open_api_scope("chat:invoke", session=True)
async def daily_chat_completions(
    request: Request,
    data: OpenDailyChatCompletionReq,
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    operator = await get_open_api_operator_async()
    internal, subject = await OpenDailyChatService.prepare_request(
        principal=principal,
        request=data,
        login_user=operator,
    )
    return await stream_chat_completion(
        request,
        internal,
        operator,
        session_subject=subject,
    )

