from typing import List

from fastapi import APIRouter, Request, Depends, Body, Query

from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload, get_login_user, get_admin_user
from bisheng.api.v1.schemas import UnifiedResponseModel, LLMServerInfo, resp_200, KnowledgeLLMConfig, \
    AssistantLLMConfig, EvaluationLLMConfig, LLMServerCreateReq, LLMModelInfo

router = APIRouter(prefix='/llm', tags=['LLM'])


@router.get('', response_model=UnifiedResponseModel[List[LLMServerInfo]])
def get_all_llm(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[List[LLMServerInfo]]:
    ret = LLMService.get_all_llm(request, login_user)
    return resp_200(data=ret)


@router.post('', response_model=UnifiedResponseModel[LLMServerInfo])
def add_llm_server(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        server: LLMServerCreateReq = Body(..., description="服务提供方所有数据"),
) -> UnifiedResponseModel[LLMServerInfo]:
    ret = LLMService.add_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.delete('', response_model=UnifiedResponseModel)
def delete_llm_server(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        server_id: int = Body(..., embed=True, description="服务提供方唯一ID"),
) -> UnifiedResponseModel:
    LLMService.delete_llm_server(request, login_user, server_id)
    return resp_200()


@router.put('', response_model=UnifiedResponseModel[LLMServerInfo])
def update_llm_server(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        server: LLMServerCreateReq = Body(..., description="服务提供方所有数据"),
) -> UnifiedResponseModel[LLMServerInfo]:
    ret = LLMService.update_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.get('/info', response_model=UnifiedResponseModel[LLMServerInfo])
def get_one_llm(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        server_id: int = Query(..., description="服务提供方唯一ID"),
) -> UnifiedResponseModel[LLMServerInfo]:
    ret = LLMService.get_one_llm(request, login_user, server_id)
    return resp_200(data=ret)


@router.post('/online', response_model=UnifiedResponseModel[LLMModelInfo])
def update_model_online(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        model_id: int = Body(..., embed=True, description="模型的唯一ID"),
        online: bool = Body(..., embed=True, description="是否上线"),
) -> UnifiedResponseModel[LLMModelInfo]:
    ret = LLMService.update_model_online(request, login_user, model_id, online)
    return resp_200(data=ret)


@router.get('/knowledge', response_model=UnifiedResponseModel[KnowledgeLLMConfig])
def get_knowledge_llm(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[KnowledgeLLMConfig]:
    ret = LLMService.get_knowledge_llm()
    return resp_200(data=ret)


@router.post('/knowledge', response_model=UnifiedResponseModel[KnowledgeLLMConfig])
def update_knowledge_llm(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        data: KnowledgeLLMConfig = Body(..., description="知识库默认模型配置"),
) -> UnifiedResponseModel[KnowledgeLLMConfig]:
    """ 更新知识库相关的默认模型配置 """
    ret = LLMService.update_knowledge_llm(request, login_user, data)
    return resp_200(data=ret)


@router.get('/assistant', response_model=UnifiedResponseModel[AssistantLLMConfig])
def get_assistant_llm(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[AssistantLLMConfig]:
    """ 获取助手相关的模型配置 """
    ret = LLMService.get_assistant_llm()
    return resp_200(data=ret)


@router.post('/assistant', response_model=UnifiedResponseModel[AssistantLLMConfig])
def update_assistant_llm(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        data: AssistantLLMConfig = Body(..., description="助手默认模型配置"),
) -> UnifiedResponseModel[AssistantLLMConfig]:
    """ 更新助手相关的模型配置 """
    ret = LLMService.update_assistant_llm(request, login_user, data)
    return resp_200(data=ret)


@router.get('/evaluation', response_model=UnifiedResponseModel[EvaluationLLMConfig])
def get_evaluation_llm(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[EvaluationLLMConfig]:
    """ 获取评价相关的模型配置 """
    ret = LLMService.get_evaluation_llm()
    return resp_200(data=ret)


@router.post('/evaluation', response_model=UnifiedResponseModel[EvaluationLLMConfig])
def update_evaluation_llm(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        data: EvaluationLLMConfig = Body(..., description="评价默认模型配置"),
) -> UnifiedResponseModel[EvaluationLLMConfig]:
    """ 更新评价相关的模型配置 """
    ret = LLMService.update_evaluation_llm(request, login_user, data)
    return resp_200(data=ret)


@router.get('/assistant/llm_list', response_model=UnifiedResponseModel[List[LLMServerInfo]])
async def get_assistant_llm_list(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
) -> UnifiedResponseModel[List[LLMServerInfo]]:
    """ 获取助手可选的模型列表 """
    ret = LLMService.get_assistant_llm_list(request, login_user)
    return resp_200(data=ret)
