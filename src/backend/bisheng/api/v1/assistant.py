import json
from typing import Dict, List, Optional

from fastapi import (APIRouter, Body, Depends, HTTPException, Query, Request, WebSocket,
                     WebSocketException)
from fastapi import status as http_status
from fastapi.responses import StreamingResponse

from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.openapi import OpenApiSchema
from bisheng.api.services.tool import ToolServices
from bisheng.api.services.user_service import UserPayload, get_admin_user, get_login_user
from bisheng.api.v1.schemas import (AssistantCreateReq, AssistantUpdateReq,
                                    DeleteToolTypeReq, StreamData, TestToolReq,
                                    resp_200, resp_500)
from bisheng.cache.redis import redis_client
from bisheng.chat.manager import ChatManager
from bisheng.chat.types import WorkType
from bisheng.database.constants import ToolPresetType
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.gpts_tools import GptsToolsTypeRead
from bisheng.mcp_manage.langchain.tool import McpTool
from bisheng.mcp_manage.manager import ClientManager
from bisheng.utils import generate_uuid
from bisheng.utils.logger import logger
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/assistant', tags=['Assistant'])
chat_manager = ChatManager()


@router.get('')
def get_assistant(*,
                  name: str = Query(default=None, description='助手名称，模糊匹配, 包含描述的模糊匹配'),
                  tag_id: int = Query(default=None, description='标签ID'),
                  page: Optional[int] = Query(default=1, gt=0, description='页码'),
                  limit: Optional[int] = Query(default=10, gt=0, description='每页条数'),
                  status: Optional[int] = Query(default=None, description='是否上线状态'),
                  login_user: UserPayload = Depends(get_login_user)):
    return AssistantService.get_assistant(login_user, name, status, tag_id, page, limit)


# 获取某个助手的详细信息
@router.get('/info/{assistant_id}')
def get_assistant_info(*, assistant_id: str, login_user: UserPayload = Depends(get_login_user)):
    """获取助手信息"""
    return AssistantService.get_assistant_info(assistant_id, login_user)


@router.post('/delete')
def delete_assistant(*,
                     request: Request,
                     assistant_id: str,
                     login_user: UserPayload = Depends(get_login_user)):
    """删除助手"""
    return AssistantService.delete_assistant(request, login_user, assistant_id)


@router.post('')
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
        return resp_500(message=f'创建助手出错：{str(e)}')


@router.put('')
async def update_assistant(*,
                           request: Request,
                           req: AssistantUpdateReq,
                           login_user: UserPayload = Depends(get_login_user)):
    # get login user
    return await AssistantService.update_assistant(request, login_user, req)


@router.post('/status')
async def update_status(*,
                        request: Request,
                        assistant_id: str = Body(description='助手唯一ID', alias='id'),
                        status: int = Body(description='是否上线，1:上线，0:下线'),
                        login_user: UserPayload = Depends(get_login_user)):
    return await AssistantService.update_status(request, login_user, assistant_id, status)


@router.post('/auto/task')
async def auto_update_assistant_task(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                     assistant_id: str = Body(description='助手唯一ID'),
                                     prompt: str = Body(description='用户填写的提示词')):
    # 存入缓存
    task_id = generate_uuid()
    redis_client.set(f'auto_update_task:{task_id}', {
        'assistant_id': assistant_id,
        'prompt': prompt,
    })
    return resp_200(data={
        'task_id': task_id
    })


# 自动优化prompt和工具选择
@router.get('/auto', response_class=StreamingResponse)
async def auto_update_assistant(*, task_id: str = Query(description='优化任务唯一ID')):
    task = redis_client.get(f'auto_update_task:{task_id}')
    if not task:
        raise HTTPException(status_code=404, detail='task info not found')
    assistant_id = task['assistant_id']
    prompt = task['prompt']

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
@router.post('/prompt')
async def update_prompt(*,
                        assistant_id: str = Body(description='助手唯一ID', alias='id'),
                        prompt: str = Body(description='用户使用的prompt'),
                        login_user: UserPayload = Depends(get_login_user)):
    return AssistantService.update_prompt(assistant_id, prompt, login_user)


@router.post('/flow')
async def update_flow_list(*,
                           assistant_id: str = Body(description='助手唯一ID', alias='id'),
                           flow_list: List[str] = Body(description='用户选择的技能列表'),
                           login_user: UserPayload = Depends(get_login_user)):
    return AssistantService.update_flow_list(assistant_id, flow_list, login_user)


@router.post('/tool')
async def update_tool_list(*,
                           assistant_id: str = Body(description='助手唯一ID', alias='id'),
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
        await chat_manager.dispatch_client(request, assistant_id, chat_id, login_user,
                                           WorkType.GPTS, websocket)
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


@router.get('/tool_list')
def get_tool_list(*,
                  is_preset: Optional[int | bool] = None,
                  login_user: UserPayload = Depends(get_login_user)):
    """查询所有可见的tool 列表"""
    if is_preset is not None and type(is_preset) == bool:
        is_preset = ToolPresetType.PRESET.value if is_preset else ToolPresetType.API.value
    return resp_200(AssistantService.get_gpts_tools(login_user, is_preset))


@router.post('/tool/config')
async def update_tool_config(*,
                             login_user: UserPayload = Depends(get_admin_user),
                             tool_id: int = Body(description='工具类别唯一ID'),
                             extra: dict = Body(description='工具配置项')):
    """ 更新工具的配置 """
    data = AssistantService.update_tool_config(login_user, tool_id, extra)
    return resp_200(data=data)


@router.post('/tool_schema')
async def get_tool_schema(request: Request, login_user: UserPayload = Depends(get_login_user),
                          download_url: Optional[str] = Body(default=None,
                                                             description='下载url不为空的话优先用下载url'),
                          file_content: Optional[str] = Body(default=None, description='上传的文件')):
    """ 下载或者解析openapi schema的内容 转为助手自定义工具的格式 """
    services = ToolServices(request=request, login_user=login_user)
    tool_type = await services.parse_openapi_schema(download_url, file_content)
    return resp_200(data=tool_type)


@router.post('/mcp/tool_schema')
async def get_mcp_tool_schema(request: Request, login_user: UserPayload = Depends(get_login_user),
                              file_content: Optional[str] = Body(default=None, embed=True,
                                                                 description='mcp服务配置内容')):
    """ 解析mcp的工具配置文件 """
    services = ToolServices(request=request, login_user=login_user)
    tool_type = await services.parse_mcp_schema(file_content)
    return resp_200(data=tool_type)


@router.post('/mcp/tool_test')
async def mcp_tool_run(login_user: UserPayload = Depends(get_login_user),
                       req: TestToolReq = None):
    """ 测试mcp服务的工具 """
    try:
        # 实例化mcp服务对象，获取工具列表
        client = await ClientManager.connect_mcp_from_json(req.openapi_schema)
        extra = json.loads(req.extra)
        tool_name = extra.get('name')
        mcp_tool = McpTool.get_mcp_tool(name=tool_name, description=extra.get("description"), mcp_client=client,
                                        mcp_tool_name=tool_name, arg_schema=extra.get('inputSchema', {}))
        resp = await mcp_tool.arun(req.request_params)
        return resp_200(data=resp)
    except Exception as e:
        logger.exception('mcp_tool_run error')
        return resp_500(message=f'测试请求出错：{str(e)}')


@router.post('/mcp/refresh')
async def refresh_all_mcp_tools(request: Request, login_user: UserPayload = Depends(get_login_user)):
    """ 刷新用户当前所有的mcp工具列表 """
    services = ToolServices(request=request, login_user=login_user)
    error_msg = await services.refresh_all_mcp()
    if error_msg:
        return resp_500(message=error_msg)
    return resp_200(message='刷新成功')


@router.post('/tool_list')
async def add_tool_type(*,
                        req: Dict = Body(default={}, description='openapi解析后的工具对象'),
                        login_user: UserPayload = Depends(get_login_user)):
    """ 新增自定义tool """
    req = GptsToolsTypeRead(**req)
    return await AssistantService.add_gpts_tools(login_user, req)


@router.put('/tool_list')
async def update_tool_type(*,
                           login_user: UserPayload = Depends(get_login_user),
                           req: Dict = Body(default={}, description='通过openapi 解析后的内容，包含类别的唯一ID')):
    """ 更新自定义tool """
    req = GptsToolsTypeRead(**req)
    return resp_200(data=await ToolServices.update_gpts_tools(login_user, req))


@router.delete('/tool_list')
def delete_tool_type(*, login_user: UserPayload = Depends(get_login_user), req: DeleteToolTypeReq):
    """ 删除自定义工具 """
    return AssistantService.delete_gpts_tools(login_user, req.tool_type_id)


@router.post('/tool_test')
async def tool_run(*, login_user: UserPayload = Depends(get_login_user), req: TestToolReq):
    """ 测试自定义工具 """
    extra = json.loads(req.extra)
    extra.update({'api_location': req.api_location, 'parameter_name': req.parameter_name})
    tool_params = OpenApiSchema.parse_openapi_tool_params('test', 'test', json.dumps(extra),
                                                          req.server_host, req.auth_method,
                                                          req.auth_type, req.api_key)

    openapi_tool = OpenApiTools.get_api_tool('test', **tool_params)
    try:
        resp = await openapi_tool.arun(req.request_params)
        return resp_200(data=resp)
    except Exception as e:
        logger.exception('tool_test error')
        return resp_500(message=f'测试请求出错：{str(e)}')
