from __future__ import annotations

from typing import Any

from bisheng.approval.domain.services.channel_subscribe_scenario_handler import ChannelSubscribeScenarioHandler
from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
    KnowledgeSpaceSubscribeScenarioHandler,
)
from bisheng.approval.domain.services.menu_access_handler import MenuAccessApprovalHandler
from bisheng.common.models.space_channel_member import BusinessTypeEnum, SpaceChannelMemberDao
from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
    SpaceChannelMemberRepositoryImpl,
)
from bisheng.core.database import get_async_db_session


async def build_runtime_handler(scenario_code: str) -> Any:
    if scenario_code == "menu_access_request":
        return MenuAccessApprovalHandler()
    if scenario_code == "channel_subscribe_request":
        from bisheng.channel.domain.services.channel_service import ChannelService

        return ChannelSubscribeScenarioHandler(
            _AsyncSpaceChannelMembershipAdapter(),
            sync_permissions=ChannelService.sync_direct_channel_user_permissions,
        )
    if scenario_code == "knowledge_space_subscribe_request":
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        return KnowledgeSpaceSubscribeScenarioHandler(
            find_member=SpaceChannelMemberDao.async_find_member,
            update_member=SpaceChannelMemberDao.update,
            sync_permissions=KnowledgeSpaceService.sync_direct_space_user_permissions,
        )
    if scenario_code == "app_publish_request":
        # Imported inside the branch: the factory is reached from the API
        # process, the Celery worker and the withdraw path, and only one of
        # those has any reason to pull in the publish pipeline.
        #
        # A **new instance every call** is load bearing, not tidiness: the
        # handler carries the self-approval flag of the request it resolved
        # (F055 design D7), and a shared instance would leak it between two
        # concurrent releases.
        from bisheng.app_publish.domain.services.app_publish_scenario_handler import AppPublishScenarioHandler

        return AppPublishScenarioHandler()
    raise KeyError(f"handler not registered for scenario_code={scenario_code}")


class _AsyncSpaceChannelMembershipAdapter:
    async def find_membership(self, business_id: str, business_type: BusinessTypeEnum, user_id: int):
        async with get_async_db_session() as session:
            repository = SpaceChannelMemberRepositoryImpl(session)
            # Activation must locate the PENDING membership (not just ACTIVE) to flip it to ACTIVE.
            return await repository.find_membership(
                business_id=business_id,
                business_type=business_type,
                user_id=user_id,
                include_inactive=True,
            )

    async def update(self, membership):
        return await SpaceChannelMemberDao.update(membership)

    async def delete(self, membership_id: int) -> bool:
        async with get_async_db_session() as session:
            repository = SpaceChannelMemberRepositoryImpl(session)
            return await repository.delete(membership_id)
