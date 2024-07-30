from typing import List

from fastapi import APIRouter, Request, Depends, Body, Query

from bisheng.api.services.llm import LLMService
from bisheng.api.services.user_service import UserPayload, get_login_user, get_admin_user
from bisheng.api.v1.schemas import UnifiedResponseModel, LLMServerInfo, resp_200

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
        server: LLMServerInfo = Body(..., description="服务提供方所有数据"),
) -> UnifiedResponseModel[LLMServerInfo]:
    ret = LLMService.add_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.put('', response_model=UnifiedResponseModel[LLMServerInfo])
def update_llm_server(
        request: Request,
        login_user: UserPayload = Depends(get_admin_user),
        server: LLMServerInfo = Body(..., description="服务提供方所有数据"),
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
