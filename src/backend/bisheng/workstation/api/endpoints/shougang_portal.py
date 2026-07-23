from fastapi import APIRouter, Depends, Request

from bisheng.api.v1.schema.chat_schema import APIChatCompletion

from ...domain.services.chat_service import stream_chat_completion
from ..dependencies import (
    LoginUserDep,
    get_department_file_view_access_service,
)

router = APIRouter(prefix="/shougang-portal")


class ShougangPortalChatCompletion(APIChatCompletion):
    system_prompt: str = ""


@router.post("/chat/completions")
async def shougang_portal_chat_completions(
    request: Request,
    data: ShougangPortalChatCompletion,
    login_user=LoginUserDep,
    department_file_view_access_service=Depends(get_department_file_view_access_service),
):
    return await stream_chat_completion(
        request,
        data,
        login_user,
        portal_context=True,
        department_file_view_access_service=(department_file_view_access_service),
    )
