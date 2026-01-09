from fastapi import APIRouter, Request, Depends, Body, Query, BackgroundTasks, UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200, UnifiedResponseModel
from ..domain import LLMService
from ..domain.schemas import KnowledgeLLMConfig, AssistantLLMConfig, EvaluationLLMConfig, LLMServerCreateReq, \
    WorkbenchModelConfig

router = APIRouter(prefix='/llm', tags=['LLM'])


@router.get('')
async def get_all_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = await LLMService.get_all_llm()
    return resp_200(data=ret)


@router.post('')
async def add_llm_server(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                         server: LLMServerCreateReq = Body(..., description="Service Provider All Data")):
    ret = await LLMService.add_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.delete('')
async def delete_llm_server(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                            server_id: int = Body(..., embed=True, description="Service Provider UniqueID")):
    await LLMService.delete_llm_server(request, login_user, server_id)
    return resp_200()


@router.put('')
async def update_llm_server(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                            server: LLMServerCreateReq = Body(..., description="Service Provider All Data")):
    ret = await LLMService.update_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.get('/info')
async def get_one_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                      server_id: int = Query(..., description="Service Provider UniqueID")):
    ret = await LLMService.get_one_llm(server_id)
    return resp_200(data=ret)


@router.post('/online')
async def update_model_online(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                              model_id: int = Body(..., embed=True, description="Model UniqueID"),
                              online: bool = Body(..., embed=True, description="Online or not")):
    ret = await LLMService.update_model_online(model_id, online)
    return resp_200(data=ret)


@router.get('/workbench', summary="Get workbench-related model configurations", response_model=UnifiedResponseModel)
async def get_workbench_llm():
    """ Get Idea-Related Model Configurations """
    ret = await LLMService.get_workbench_llm()
    return resp_200(data=ret)


@router.post('/workbench', summary="Update workbench related model configurations", response_model=UnifiedResponseModel)
async def update_workbench_llm(
        background_tasks: BackgroundTasks,
        login_user: UserPayload = Depends(UserPayload.get_admin_user),
        config_obj: WorkbenchModelConfig = Body(..., description="Model Configuration Object")):
    """ Update Idea-Related Model Configurations """
    ret = await LLMService.update_workbench_llm(login_user.user_id, config_obj, background_tasks)
    return resp_200(data=ret)


@router.post('/workbench/asr')
async def invoke_workbench_asr(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                               file: UploadFile = None):
    """ Call the workbench'sasrModels Convert Voice to Text """
    text = await LLMService.invoke_workbench_asr(login_user, file)
    return resp_200(data=text)


@router.post('/workbench/tts')
async def invoke_workbench_tts(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                               text: str = Body(..., embed=True, description="Text that needs to be synthesized")):
    """ Call the workbench'sttsModels Convert text to speech """
    audio_url = await LLMService.invoke_workbench_tts(login_user, text)
    return resp_200(data=audio_url)


@router.get('/knowledge')
def get_knowledge_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = LLMService.get_knowledge_llm()
    return resp_200(data=ret)


@router.post('/knowledge')
async def update_knowledge_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                               data: KnowledgeLLMConfig = Body(..., description="Knowledge Base Default Model Configuration")):
    """ Update default model configuration for knowledge base """
    ret = await LLMService.update_knowledge_llm(data)
    return resp_200(data=ret)


@router.get('/assistant')
async def get_assistant_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get assistant related model configuration """
    ret = await LLMService.get_assistant_llm()
    return resp_200(data=ret)


@router.post('/assistant')
async def update_assistant_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                               data: AssistantLLMConfig = Body(..., description="Assistant Default Model Configuration")):
    """ Update assistant related model configurations """
    ret = await LLMService.update_assistant_llm(data)
    return resp_200(data=ret)


@router.get('/evaluation')
async def get_evaluation_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get evaluation related model configurations """
    ret = await LLMService.get_evaluation_llm()
    return resp_200(data=ret)


@router.post('/evaluation')
async def update_evaluation_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                                data: EvaluationLLMConfig = Body(..., description="Evaluate default model configuration")):
    """ Update review related model configurations """
    ret = await LLMService.update_evaluation_llm(data)
    return resp_200(data=ret)


@router.get('/workflow')
async def get_workflow_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get workflow-related model configurations """
    ret = await LLMService.get_workflow_llm()
    return resp_200(data=ret)


@router.post('/workflow')
async def update_workflow_llm(request: Request, login_user: UserPayload = Depends(UserPayload.get_admin_user),
                              data: EvaluationLLMConfig = Body(..., description="Workflow default model configuration")):
    """ Update workflow-related model configurations """
    ret = await LLMService.update_workflow_llm(data)
    return resp_200(data=ret)


@router.get('/assistant/llm_list')
async def get_assistant_llm_list(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get a list of optional models for the assistant """
    ret = await LLMService.get_assistant_llm_list(request, login_user)
    return resp_200(data=ret)
