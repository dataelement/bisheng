import json
from typing import Optional, Dict

from fastapi import APIRouter, Depends, Body, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.mcp_manage.langchain.tool import McpTool
from bisheng.mcp_manage.manager import ClientManager
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
    """Query all visibletool Vertical"""
    res = await ToolServices(login_user=login_user).get_tool_list(is_preset)
    return resp_200(data=res)


@router.post('')
async def add_tool_type(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                        req: Dict = Body(default={})):
    """ Add customizationtool """
    req = GptsToolsTypeRead(**req)
    services = ToolServices(request=request, login_user=login_user)

    return resp_200(data=await services.add_tools(req))


@router.put('')
async def update_tool_type(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                           req: Dict = Body(default={})):
    """ Custom field updated.tool """
    req = GptsToolsTypeRead(**req)
    services = ToolServices(request=request, login_user=login_user)

    return resp_200(data=await services.update_tools(req))


@router.delete('')
async def delete_tool_type(*, request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                           tool_type_id: int = Body(..., embed=True)):
    """ Remove Customizer """
    services = ToolServices(request=request, login_user=login_user)

    await services.delete_tools(tool_type_id)
    return resp_200()


@router.post('/config')
async def update_tool_config(*,
                             login_user: UserPayload = Depends(UserPayload.get_admin_user),
                             tool_id: int = Body(description='Tool Category UniqueID'),
                             extra: Dict = Body(..., description='Configuration information for the tool')):
    """ Update the configuration of the tool """
    data = await ToolServices(login_user=login_user).update_tool_config(tool_id, extra)
    return resp_200(data=data)


@router.post('/schema')
async def get_tool_schema(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                          download_url: Optional[str] = Body(default=None,
                                                             description='MengunduhurlIf it is not empty, download it firsturl'),
                          file_content: Optional[str] = Body(default=None, description='files uploaded')):
    """ Download or parseopenapi schemaThe contents of the Convert to Assistant Customizer Format """
    services = ToolServices(request=request, login_user=login_user)
    tool_type = await services.parse_openapi_schema(download_url, file_content)
    return resp_200(data=tool_type)


@router.post('/mcp/schema')
async def get_mcp_tool_schema(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                              file_content: Optional[str] = Body(default=None, embed=True,
                                                                 description='mcpService Configuration Content')):
    """ analyzingmcpTool Profile """
    services = ToolServices(request=request, login_user=login_user)
    tool_type = await services.parse_mcp_schema(file_content)
    return resp_200(data=tool_type)


@router.post('/test')
async def tool_run(*, login_user: UserPayload = Depends(UserPayload.get_login_user), req: TestToolReq):
    """ Test custom tool """
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
    """ TestmcpTools for Services """
    # Instantiatemcpservice object, getting a list of tools
    client = await ClientManager.connect_mcp_from_json(req.openapi_schema)
    extra = json.loads(req.extra)
    tool_name = extra.get('name')
    mcp_tool = McpTool.get_mcp_tool(name=tool_name, description=extra.get("description"), mcp_client=client,
                                    mcp_tool_name=tool_name, arg_schema=extra.get('inputSchema', {}))
    resp = await mcp_tool.arun(req.request_params)
    return resp_200(data=resp)


@router.post('/mcp/refresh')
async def refresh_all_mcp_tools(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Refresh all of the user's currentmcpTools List """
    services = ToolServices(request=request, login_user=login_user)
    error_name = await services.refresh_all_mcp()
    return resp_200(data=error_name)


@router.get("/linsight/preset", summary="Get a list of Ideas presets", response_model=UnifiedResponseModel)
async def get_linsight_tools():
    """
    Get a list of Ideas presets
    """
    tools = await ToolServices.get_linsight_tools()
    return resp_200(data=tools)
