import json
from typing import List

from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.schemas import (AssistantCreateReq, AssistantInfo, AssistantUpdateReq,
                                    UnifiedResponseModel)
from bisheng.database.models.assistant import Assistant
from fastapi import APIRouter, Body, Depends
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/assistant', tags=['Assistant'])


@router.get('', response_model=UnifiedResponseModel[List[AssistantInfo]])
def get_assistant():
    pass


@router.post('', response_model=UnifiedResponseModel[AssistantInfo])
def create_assistant(*,
                     req: AssistantCreateReq,
                     Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())

    assistant = Assistant(**req.dict(),
                          user_id=current_user.get('user_id'))
    return AssistantService.create_assistant(assistant)


@router.put('', response_model=UnifiedResponseModel[AssistantInfo])
def update_assistant(*,
                     req: AssistantUpdateReq,
                     Authorize: AuthJWT = Depends()):
    # get login user
    Authorize.jwt_required()
    return AssistantService.update_assistant(req)


# 自动优化prompt和工具选择
@router.post('/auto', response_model=UnifiedResponseModel[AssistantInfo])
def auto_update_assistant(*,
                          assistant_id: int = Body(description='助手唯一ID'),
                          prompt: str = Body(description='用户填写的提示词'),
                          Authorize: AuthJWT = Depends()):
    return AssistantService.auto_update(assistant_id, prompt)


# 更新助手的提示词
@router.post('/prompt', response_model=UnifiedResponseModel)
def update_prompt(*,
                  assistant_id: int = Body(description='助手唯一ID'),
                  prompt: str = Body(description='用户使用的prompt'),
                  Authorize: AuthJWT = Depends()):
    return AssistantService.update_prompt(assistant_id, prompt)


@router.post('/skill', response_model=UnifiedResponseModel)
def update_skill_list(*,
                      assistant_id: int = Body(description='助手唯一ID'),
                      skill_list: List[int] = Body(description='用户选择的技能列表'),
                      Authorize: AuthJWT = Depends()):
    return AssistantService.update_skill_list(assistant_id, skill_list)


@router.post('/tool', response_model=UnifiedResponseModel)
def update_tool_list(*,
                     assistant_id: int = Body(description='助手唯一ID'),
                     tool_list: List[int] = Body(description='用户选择的工具列表'),
                     Authorize: AuthJWT = Depends()):
    return AssistantService.update_tool_list(assistant_id, tool_list)
