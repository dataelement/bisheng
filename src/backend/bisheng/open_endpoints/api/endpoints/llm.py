from fastapi import APIRouter, Body, Request, UploadFile

from bisheng.common.schemas.api import resp_200
from bisheng.llm.domain import LLMService
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_endpoints.domain.utils import get_open_api_operator

router = APIRouter(prefix='/llm', tags=['OpenAPI', 'llm'])


@router.post('/workbench/asr')
@open_api_scope("assistant:invoke", modes=("S",))
async def invoke_workbench_asr(request: Request, file: UploadFile = None):
    """ Call the workbench'sasrModels Convert Voice to Text """
    login_user = get_open_api_operator()
    text = await LLMService.invoke_workbench_asr(login_user, file)
    return resp_200(data=text)


@router.post('/workbench/tts')
@open_api_scope("assistant:invoke", modes=("S",))
async def invoke_workbench_tts(request: Request, text: str = Body(..., embed=True, description="Text that needs to be synthesized")):
    """ Call the workbench'sttsModels Convert text to speech """
    login_user = get_open_api_operator()
    audio_url = await LLMService.invoke_workbench_tts(login_user, text)
    return resp_200(data=audio_url)
