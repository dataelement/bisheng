from __future__ import annotations

from loguru import logger

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizeRequest,
)
from bisheng.channel.domain.schemas.channel_manager_schema import (
    ChannelInitialPermissionResult,
    CreateChannelRequest,
)
from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.permission.domain.services.grant_subject_query_service import (
    GrantSubjectQueryService,
)


class ChannelCreationApplicationService:
    def __init__(
        self,
        channel_service: ChannelService,
        grant_subject_query_service: GrantSubjectQueryService,
        channel_authorization_service: ChannelAuthorizationService,
    ):
        self.channel_service = channel_service
        self.grant_subject_query_service = grant_subject_query_service
        self.channel_authorization_service = channel_authorization_service

    async def create(
        self,
        channel_data: CreateChannelRequest,
        login_user: UserPayload,
        request=None,
    ):
        grants = list(channel_data.initial_permissions.grants) if channel_data.initial_permissions else []
        if grants and channel_data.visibility == ChannelVisibilityEnum.PRIVATE:
            raise ChannelPermissionDeniedError()
        if not grants:
            return await self.channel_service.create_channel(channel_data, login_user, request)

        await self.grant_subject_query_service.validate_creation_grants(
            resource_type="channel",
            grants=grants,
            login_user=login_user,
        )
        channel = await self.channel_service.create_channel(channel_data, login_user, request)
        channel_id = str(channel.id)
        authorize_request = ChannelAuthorizeRequest(grants=grants, revokes=[])
        try:
            await self.channel_authorization_service.authorize_channel(
                channel_id,
                authorize_request,
                login_user,
            )
        except BaseErrorCode as exc:
            logger.warning(
                "initial channel authorization failed after creation: channel_id={} error_code={}",
                channel_id,
                exc.code,
            )
            return self._with_permission_result(
                channel,
                ChannelInitialPermissionResult(status="failed", error_code=exc.code),
            )

        return self._with_permission_result(
            channel,
            ChannelInitialPermissionResult(status="success", error_code=None),
        )

    @staticmethod
    def _with_permission_result(channel, result: ChannelInitialPermissionResult) -> dict:
        if isinstance(channel, dict):
            payload = dict(channel)
        elif hasattr(channel, "model_dump"):
            payload = channel.model_dump()
        else:
            payload = {key: value for key, value in vars(channel).items() if not key.startswith("_")}
        if "id" not in payload and getattr(channel, "id", None) is not None:
            payload["id"] = channel.id
        payload["initial_permission_result"] = result.model_dump()
        return payload
