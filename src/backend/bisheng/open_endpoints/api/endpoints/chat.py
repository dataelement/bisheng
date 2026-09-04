"""Source-aware Open API session reads."""

from fastapi import APIRouter, Depends, Query

from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.open_api.api.dependencies import get_open_api_execution
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal

router = APIRouter(prefix="/chat", tags=["OpenAPI", "Chat"])


@router.get("/list", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke", session=True)
def list_daily_sessions(
    page: int = Query(default=1, ge=1, le=1000),
    limit: int = Query(default=10, ge=1, le=100),
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    subject = session_subject_from_principal(principal)
    return resp_200(data=ChatSessionService.get_subject_session_list(subject, page, limit))


@router.get("/info", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke", session=True)
async def get_daily_session_info(
    chat_id: str = Query(...),
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    subject = session_subject_from_principal(principal)
    return resp_200(data=await ChatSessionService.get_session_info(chat_id, subject))
