from fastapi import APIRouter, Request, UploadFile, Body

from bisheng.common.schemas.api import resp_200
from bisheng.llm.domain import LLMService
from bisheng.open_endpoints.domain.utils import get_default_operator

router = APIRouter(prefix='/llm', tags=['OpenAPI', 'llm'])


@router.post('/workbench/asr')
async def invoke_workbench_asr(request: Request, file: UploadFile = None):
    """ Call the workbench'sasrModels Convert Voice to Text """
    login_user = get_default_operator()
    text = await LLMService.invoke_workbench_asr(login_user, file)
    return resp_200(data=text)


@router.post('/workbench/tts')
async def invoke_workbench_tts(request: Request, text: str = Body(..., embed=True, description="Text that needs to be synthesized")):
    """ Call the workbench'sttsModels Convert text to speech """
    login_user = get_default_operator()
    audio_url = await LLMService.invoke_workbench_tts(login_user, text)
    return resp_200(data=audio_url)
