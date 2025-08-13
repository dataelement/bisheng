from fastapi import APIRouter

from bisheng.api.services.tool import ToolServices
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200

router = APIRouter(prefix='/tool', tags=['Tool'])


@router.get("/linsight/preset", summary="获取灵思预置工具列表", response_model=UnifiedResponseModel)
async def get_linsight_tools():
    """
    获取灵思预置工具列表
    """
    tools = await ToolServices.get_linsight_tools()
    return resp_200(data=tools)
