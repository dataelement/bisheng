from typing import Optional

from fastapi import APIRouter, Depends

from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.services.tool import ToolServices

router = APIRouter(prefix='/tool', tags=['Tool'])


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
