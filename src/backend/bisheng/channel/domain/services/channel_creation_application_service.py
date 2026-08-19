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

        from bisheng.core.context.tenant import get_current_tenant_id

        tenant_id = get_current_tenant_id() or int(login_user.tenant_id)
        async with self.channel_authorization_service.invite_scenario_guard_for_grants(
            grants,
            tenant_id=int(tenant_id),
        ):
            validated_tenant_id = await self.grant_subject_query_service.validate_creation_grant_request(
                resource_type="channel",
                grants=grants,
                login_user=login_user,
            )
            direct_grants = [grant for grant in grants if grant.subject_type != "user"]
            await self.grant_subject_query_service.validate_creation_grant_subjects(
                resource_type="channel",
                grants=direct_grants,
                login_user=login_user,
                tenant_id=validated_tenant_id,
            )
            channel = await self.channel_service.create_channel(channel_data, login_user, request)
            channel_id = str(channel.id)
            authorize_request = ChannelAuthorizeRequest(grants=grants, revokes=[])
            try:
                authorization_result = await self.channel_authorization_service.authorize_channel(
                    channel_id,
                    authorize_request,
                    login_user,
                    scenario_guarded=True,
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

        if authorization_result is None:
            # Compatibility for legacy/injected implementations that returned no
            # authorization result before F045 added per-item outcomes.
            return self._with_permission_result(
                channel,
                ChannelInitialPermissionResult(status="success", error_code=None),
            )
        first_failed = next(
            (item for item in authorization_result.results if item.outcome == "failed"),
            None,
        )
        return self._with_permission_result(
            channel,
            ChannelInitialPermissionResult(
                status="failed" if authorization_result.failed_count else "success",
                error_code=first_failed.error_code if first_failed else None,
                direct_applied_count=authorization_result.direct_applied_count,
                invite_created_count=authorization_result.invite_created_count,
                invite_existing_count=authorization_result.invite_existing_count,
                failed_count=authorization_result.failed_count,
                results=authorization_result.results,
            ),
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
