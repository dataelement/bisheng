from fastapi import APIRouter, Request

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from ..dependencies import LoginUserDep
from ...domain.services.chat_service import stream_chat_completion


router = APIRouter(prefix='/shougang-portal')


class ShougangPortalChatCompletion(APIChatCompletion):
    system_prompt: str = ''


@router.post('/chat/completions')
async def shougang_portal_chat_completions(
        request: Request,
        data: ShougangPortalChatCompletion,
        login_user=LoginUserDep,
):
    return await stream_chat_completion(request, data, login_user)
