import json
from typing import Optional, Dict

from fastapi import APIRouter, Depends, Body, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.mcp_manage.langchain.tool import McpTool
from bisheng.mcp_manage.manager import ClientManager
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsToolsTypeRead
from bisheng.tool.domain.schemas import TestToolReq
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng.tool.domain.services.tool import ToolServices
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools

router = APIRouter(prefix='/tool', tags=['Tool'])


@router.get('')
async def get_tool_list(*,
                        is_preset: Optional[int] = None,
                        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """查询所有可见的tool 列表"""
    res = await ToolServices(login_user=login_user).get_tool_list(is_preset)
    return resp_200(data=res)


@router.post('')
async def add_tool_type(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                        req: Dict = Body(default={})):
    """ 新增自定义tool """
    req = GptsToolsTypeRead(**req)
    services = ToolServices(request=request, login_user=login_user)

    return resp_200(data=await services.add_tools(req))


@router.put('')
async def update_tool_type(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                           req: Dict = Body(default={})):
    """ 更新自定义tool """
    req = GptsToolsTypeRead(**req)
    services = ToolServices(request=request, login_user=login_user)

    return resp_200(data=await services.update_tools(req))


@router.delete('')
async def delete_tool_type(*, request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                           tool_type_id: int = Body(..., embed=True)):
    """ 删除自定义工具 """
    services = ToolServices(request=request, login_user=login_user)

    await services.delete_tools(tool_type_id)
    return resp_200()


@router.post('/config')
async def update_tool_config(*,
                             login_user: UserPayload = Depends(UserPayload.get_admin_user),
                             tool_id: int = Body(description='工具类别唯一ID'),
                             extra: dict = Body(description='工具配置项')):
    """ 更新工具的配置 """
    data = await ToolServices(login_user=login_user).update_tool_config(tool_id, extra)
    return resp_200(data=data)


@router.post('/tool_schema')
async def get_tool_schema(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                          download_url: Optional[str] = Body(default=None,
                                                             description='下载url不为空的话优先用下载url'),
                          file_content: Optional[str] = Body(default=None, description='上传的文件')):
    """ 下载或者解析openapi schema的内容 转为助手自定义工具的格式 """
    services = ToolServices(request=request, login_user=login_user)
    tool_type = await services.parse_openapi_schema(download_url, file_content)
    return resp_200(data=tool_type)


@router.post('/mcp/tool_schema')
async def get_mcp_tool_schema(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                              file_content: Optional[str] = Body(default=None, embed=True,
                                                                 description='mcp服务配置内容')):
    """ 解析mcp的工具配置文件 """
    services = ToolServices(request=request, login_user=login_user)
    tool_type = await services.parse_mcp_schema(file_content)
    return resp_200(data=tool_type)


@router.post('/test')
async def tool_run(*, login_user: UserPayload = Depends(UserPayload.get_login_user), req: TestToolReq):
    """ 测试自定义工具 """
    extra = json.loads(req.extra)
    extra.update({'api_location': req.api_location, 'parameter_name': req.parameter_name})
    tool_params = OpenApiSchema.parse_openapi_tool_params('test', 'test', json.dumps(extra),
                                                          req.server_host, req.auth_method,
                                                          req.auth_type, req.api_key)

    openapi_tool = OpenApiTools.get_api_tool('test', **tool_params)
    resp = await openapi_tool.arun(req.request_params)
    return resp_200(data=resp)


@router.post('/mcp/test')
async def mcp_tool_run(login_user: UserPayload = Depends(UserPayload.get_login_user),
                       req: TestToolReq = None):
    """ 测试mcp服务的工具 """
    # 实例化mcp服务对象，获取工具列表
    client = await ClientManager.connect_mcp_from_json(req.openapi_schema)
    extra = json.loads(req.extra)
    tool_name = extra.get('name')
    mcp_tool = McpTool.get_mcp_tool(name=tool_name, description=extra.get("description"), mcp_client=client,
                                    mcp_tool_name=tool_name, arg_schema=extra.get('inputSchema', {}))
    resp = await mcp_tool.arun(req.request_params)
    return resp_200(data=resp)


@router.post('/mcp/refresh')
async def refresh_all_mcp_tools(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ 刷新用户当前所有的mcp工具列表 """
    services = ToolServices(request=request, login_user=login_user)
    error_name = await services.refresh_all_mcp()
    return resp_200(data=error_name)


@router.get("/linsight/preset", summary="获取灵思预置工具列表", response_model=UnifiedResponseModel)
async def get_linsight_tools():
    """
    获取灵思预置工具列表
    """
    tools = await ToolServices.get_linsight_tools()
    return resp_200(data=tools)


@router.get("/manage", summary="获取有管理权限的工具列表", response_model=UnifiedResponseModel)
async def get_manage_tools(
        is_preset: Optional[int] = None,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    获取有管理权限的工具列表
    """
    if is_preset is not None:
        is_preset = ToolPresetType(is_preset)
    tools = await ToolServices(login_user=login_user).get_manage_tools(is_preset)
    return resp_200(data=tools)
