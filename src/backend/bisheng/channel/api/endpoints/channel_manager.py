from fastapi import APIRouter, Depends

from bisheng.channel.api.dependencies import get_channel_service
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix='/manager', tags=['Channel Manager'])


@router.post("/create")
async def create_channel(
        req_param: CreateChannelRequest,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        channel_service: 'ChannelService' = Depends(get_channel_service)
):
    """Endpoint to create a new channel."""
    channel = await channel_service.create_channel(req_param, login_user)

    return resp_200(data=channel)
