import hashlib
import json
from typing import List, Optional, Any, Dict
from uuid import UUID

import yaml
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.openapi import OpenApiSchema
from bisheng.api.services.user_service import UserPayload, get_login_user, get_admin_user
from bisheng.api.utils import get_url_content
from bisheng.api.v1.schemas import (AssistantCreateReq, AssistantInfo, AssistantUpdateReq,
                                    StreamData, UnifiedResponseModel, resp_200, resp_500, DeleteToolTypeReq,
                                    TestToolReq)
from bisheng.chat.manager import ChatManager
from bisheng.chat.types import WorkType
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.gpts_tools import GptsToolsTypeRead, GptsTools
from bisheng.utils.logger import logger
from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketException, Request
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/assistant', tags=['Assistant'])
chat_manager = ChatManager()


@router.get('', response_model=UnifiedResponseModel[List[AssistantInfo]])
def get_assistant(*,
                  name: str = Query(default=None, description='助手名称，模糊匹配, 包含描述的模糊匹配'),
                  tag_id: int = Query(default=None, description='标签ID'),
                  page: Optional[int] = Query(default=1, gt=0, description='页码'),
                  limit: Optional[int] = Query(default=10, gt=0, description='每页条数'),
                  status: Optional[int] = Query(default=None, description='是否上线状态'),
                  login_user: UserPayload = Depends(get_login_user)):
    return AssistantService.get_assistant(login_user, name, status, tag_id, page, limit)


# 获取某个助手的详细信息
@router.get('/info/{assistant_id}', response_model=UnifiedResponseModel[AssistantInfo])
def get_assistant_info(*, assistant_id: UUID, login_user: UserPayload = Depends(get_login_user)):
    """获取助手信息"""
    return AssistantService.get_assistant_info(assistant_id, login_user)


@router.post('/delete', response_model=UnifiedResponseModel)
def delete_assistant(*,
                     request: Request,
                     assistant_id: UUID,
                     login_user: UserPayload = Depends(get_login_user)):
    """删除助手"""
    return AssistantService.delete_assistant(request, login_user, assistant_id)


@router.post('', response_model=UnifiedResponseModel[AssistantInfo])
async def create_assistant(*,
                           request: Request,
                           req: AssistantCreateReq,
                           login_user: UserPayload = Depends(get_login_user)):
    # get login user
    assistant = Assistant(**req.dict(), user_id=login_user.user_id)
    try:
        return await AssistantService.create_assistant(request, login_user, assistant)
    except Exception as e:
        logger.exception('create_assistant error')
        return resp_500(message=f"创建助手出错：{str(e)}")


@router.put('', response_model=UnifiedResponseModel[AssistantInfo])
async def update_assistant(*,
                           request: Request,
                           req: AssistantUpdateReq,
                           login_user: UserPayload = Depends(get_login_user)):
    # get login user
    return await AssistantService.update_assistant(request, login_user, req)


@router.post('/status', response_model=UnifiedResponseModel)
async def update_status(*,
                        request: Request,
                        assistant_id: UUID = Body(description='助手唯一ID', alias='id'),
                        status: int = Body(description='是否上线，1:上线，0:下线'),
                        login_user: UserPayload = Depends(get_login_user)):
    return await AssistantService.update_status(request, login_user, assistant_id, status)


# 自动优化prompt和工具选择
@router.get('/auto', response_class=StreamingResponse)
async def auto_update_assistant(*,
                                assistant_id: UUID = Query(description='助手唯一ID'),
                                prompt: str = Query(description='用户填写的提示词')):
    async def event_stream():
        try:
            async for message in AssistantService.auto_update_stream(assistant_id, prompt):
                yield message
            yield str(StreamData(event='message', data={'type': 'end', 'data': ''}))
        except Exception as e:
            logger.exception('assistant auto update error')
            yield str(StreamData(event='message', data={'type': 'end', 'message': str(e)}))

    try:
        return StreamingResponse(event_stream(), media_type='text/event-stream')
    except Exception as exc:
        logger.error(exc)
        raise HTTPException(status_code=500, detail=str(exc))


# 更新助手的提示词
@router.post('/prompt', response_model=UnifiedResponseModel)
async def update_prompt(*,
                        assistant_id: UUID = Body(description='助手唯一ID', alias='id'),
                        prompt: str = Body(description='用户使用的prompt'),
                        login_user: UserPayload = Depends(get_login_user)):
    return AssistantService.update_prompt(assistant_id, prompt, login_user)


@router.post('/flow', response_model=UnifiedResponseModel)
async def update_flow_list(*,
                           assistant_id: UUID = Body(description='助手唯一ID', alias='id'),
                           flow_list: List[str] = Body(description='用户选择的技能列表'),
                           login_user: UserPayload = Depends(get_login_user)):
    return AssistantService.update_flow_list(assistant_id, flow_list, login_user)


@router.post('/tool', response_model=UnifiedResponseModel)
async def update_tool_list(*,
                           assistant_id: UUID = Body(description='助手唯一ID', alias='id'),
                           tool_list: List[int] = Body(description='用户选择的工具列表'),
                           login_user: UserPayload = Depends(get_login_user)):
    """ 更新助手选择的工具列表 """
    return AssistantService.update_tool_list(assistant_id, tool_list, login_user)


# 助手对话的websocket连接
@router.websocket('/chat/{assistant_id}')
async def chat(*,
               assistant_id: str,
               websocket: WebSocket,
               t: Optional[str] = None,
               chat_id: Optional[str] = None,
               Authorize: AuthJWT = Depends()):
    try:
        if t:
            Authorize.jwt_required(auth_from='websocket', token=t)
            Authorize._token = t
        else:
            Authorize.jwt_required(auth_from='websocket', websocket=websocket)

        payload = Authorize.get_jwt_subject()
        payload = json.loads(payload)
        login_user = UserPayload(**payload)
        request = websocket
        await chat_manager.dispatch_client(request, assistant_id, chat_id, login_user, WorkType.GPTS,
                                           websocket)
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {str(exc)}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as exc:
        logger.exception(f'Error in chat websocket: {str(exc)}')
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if 'Could not validate credentials' in str(exc):
            await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION, reason='Unauthorized')
        else:
            await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=message)


@router.get('/tool_list', response_model=UnifiedResponseModel)
def get_tool_list(*, is_preset: Optional[bool] = None, login_user: UserPayload = Depends(get_login_user)):
    """查询所有可见的tool 列表"""
    return resp_200(AssistantService.get_gpts_tools(login_user, is_preset))


@router.post('/tool/config', response_model=UnifiedResponseModel)
async def update_tool_config(*,
                             login_user: UserPayload = Depends(get_admin_user),
                             tool_id: int = Body(description='工具类别唯一ID'),
                             extra: dict = Body(description='工具配置项')):
    """ 更新工具的配置 """
    data = AssistantService.update_tool_config(login_user, tool_id, extra)
    return resp_200(data=data)


@router.post('/tool_schema', response_model=UnifiedResponseModel)
async def get_tool_schema(*,
                          download_url: Optional[str] = Body(default=None,
                                                             description='下载url不为空的话优先用下载url'),
                          file_content: Optional[str] = Body(default=None, description='上传的文件'),
                          login_user: UserPayload = Depends(get_login_user)):
    """ 下载或者解析openapi schema的内容 转为助手自定义工具的格式 """
    if download_url:
        try:
            file_content = await get_url_content(download_url)
        except Exception as e:
            logger.exception(f'file {download_url} download error')
            return resp_500(message="url文件下载失败：" + str(e))

    if not file_content:
        return resp_500(message="schema内容不能为空")
    # 根据文件内容是否以`{`开头判断用什么解析方式
    try:
        if file_content.startswith("{"):
            res = json.loads(file_content)
        else:
            res = yaml.safe_load(file_content)
    except Exception as e:
        logger.exception(f'openapi schema parse error')
        return resp_500(message=f"openapi schema解析报错，请检查内容是否符合json或者yaml格式: {str(e)}")

    # 解析openapi schema转为助手工具的格式
    try:
        schema = OpenApiSchema(res)
        schema.parse_server()
        if not schema.default_server.startswith(("http", "https")):
            return resp_500(message=f"server中的url必须以http或者https开头: {schema.default_server}")
        tool_type = GptsToolsTypeRead(name=schema.title, description=schema.description,
                                      is_preset=0, is_delete=0, server_host=schema.default_server,
                                      openapi_schema=file_content, children=[])
        # 解析获取所有的api
        schema.parse_paths()
        for one in schema.apis:
            tool_type.children.append(GptsTools(
                name=one['operationId'],
                desc=one['description'],
                tool_key=hashlib.md5(one['operationId'].encode("utf-8")).hexdigest(),
                is_preset=0,
                is_delete=0,
                api_params=one["parameters"],
                extra=json.dumps(one, ensure_ascii=False),
            ))
        return resp_200(data=tool_type)
    except Exception as e:
        logger.exception(f'openapi schema parse error')
        return resp_500(message="openapi schema解析失败：" + str(e))


@router.post('/tool_list', response_model=UnifiedResponseModel[GptsToolsTypeRead])
def add_tool_type(*, req: Dict = Body(default={}, description="openapi解析后的工具对象"),
                  login_user: UserPayload = Depends(get_login_user)):
    """ 新增自定义tool """
    req = GptsToolsTypeRead(**req)
    return AssistantService.add_gpts_tools(login_user, req)


@router.put('/tool_list', response_model=UnifiedResponseModel[GptsToolsTypeRead])
def update_tool_type(*,
                     login_user: UserPayload = Depends(get_login_user),
                     req: Dict = Body(default={}, description="通过openapi 解析后的内容，包含类别的唯一ID")):
    """ 更新自定义tool """
    req = GptsToolsTypeRead(**req)
    return AssistantService.update_gpts_tools(login_user, req)


@router.delete('/tool_list', response_model=UnifiedResponseModel)
def delete_tool_type(*,
                     login_user: UserPayload = Depends(get_login_user),
                     req: DeleteToolTypeReq):
    """ 删除自定义工具 """
    return AssistantService.delete_gpts_tools(login_user, req.tool_type_id)


@router.post('/tool_test', response_model=UnifiedResponseModel)
async def test_tool_type(*,
                         login_user: UserPayload = Depends(get_login_user),
                         req: TestToolReq):
    """ 测试自定义工具 """
    tool_params = OpenApiSchema.parse_openapi_tool_params('test', 'test', req.extra, req.server_host,
                                                          req.auth_method, req.auth_type, req.api_key)

    openapi_tool = OpenApiTools.get_api_tool('test', **tool_params)
    try:
        resp = await openapi_tool.arun(req.request_params)
        return resp_200(data=resp)
    except Exception as e:
        logger.exception('tool_test error')
        return resp_500(message=f"测试请求出错：{str(e)}")
