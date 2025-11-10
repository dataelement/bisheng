from typing import Optional

from fastapi import APIRouter, Depends

from bisheng.api.services.tool import ToolServices
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.constants import ToolPresetType

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
        login_user: UserPayload = Depends(get_login_user)):
    """
    获取有管理权限的工具列表
    """
    if is_preset is not None:
        is_preset = ToolPresetType(is_preset)
    tools = await ToolServices(login_user=login_user).get_manage_tools(is_preset)
    return resp_200(data=tools)
