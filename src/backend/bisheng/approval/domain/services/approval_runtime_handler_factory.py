from __future__ import annotations

from typing import Any

from bisheng.approval.domain.services.channel_subscribe_scenario_handler import ChannelSubscribeScenarioHandler
from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import KnowledgeSpaceSubscribeScenarioHandler
from bisheng.approval.domain.services.menu_access_handler import MenuAccessApprovalHandler
from bisheng.common.models.space_channel_member import BusinessTypeEnum, SpaceChannelMemberDao
from bisheng.common.repositories.implementations.space_channel_member_repository_impl import SpaceChannelMemberRepositoryImpl
from bisheng.core.database import get_async_db_session


async def build_runtime_handler(scenario_code: str) -> Any:
    if scenario_code == 'menu_access_request':
        return MenuAccessApprovalHandler()
    if scenario_code == 'channel_subscribe_request':
        return ChannelSubscribeScenarioHandler(_AsyncSpaceChannelMembershipAdapter())
    if scenario_code == 'knowledge_space_subscribe_request':
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        return KnowledgeSpaceSubscribeScenarioHandler(
            find_member=SpaceChannelMemberDao.async_find_member,
            update_member=SpaceChannelMemberDao.update,
            sync_permissions=KnowledgeSpaceService.sync_direct_space_user_permissions,
        )
    raise KeyError(f'handler not registered for scenario_code={scenario_code}')


class _AsyncSpaceChannelMembershipAdapter:
    async def find_membership(self, business_id: str, business_type: BusinessTypeEnum, user_id: int):
        async with get_async_db_session() as session:
            repository = SpaceChannelMemberRepositoryImpl(session)
            return await repository.find_membership(
                business_id=business_id,
                business_type=business_type,
                user_id=user_id,
            )

    async def update(self, membership):
        return await SpaceChannelMemberDao.update(membership)
