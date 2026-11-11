"""AC-22: actual business gates must stop comparing used to tenant remaining."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.errcode.channel import ChannelCreateLimitExceededError
from bisheng.common.errcode.knowledge_space import SpaceLimitError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope
from test.quota.test_managed_tenant_quota import quota_db as quota_db
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def creation_budget(quota_db):
    await quota_db.create(Knowledge, DepartmentKnowledgeSpace)
    with bypass_tenant_filter():
        async with quota_db.sessions() as session:
            for role_id in (2, 3):
                (await session.get(Role, role_id)).quota_config = {"channel": 10, "knowledge_space": 10}
            (await session.get(Tenant, 2)).quota_config = {"channel": 8, "knowledge_space": 8}
            session.add_all(
                [
                    Channel(id=f"more-{i}", name=f"more-{i}", user_id=77, tenant_id=2, visibility="private")
                    for i in range(3)
                ]
            )
            session.add_all([Knowledge(id=i, name=f"space-{i}", user_id=77, tenant_id=2, type=3) for i in range(1, 6)])
            await session.commit()
    return quota_db


async def test_channel_prospective_gate_uses_independent_budgets(creation_budget, monkeypatch):
    """AC-22: five created channels, role ten and tenant remaining three permits one."""
    from bisheng.channel.domain.services import channel_service as module

    channels = [SimpleNamespace(id=f"c-{i}") for i in range(5)]
    service = module.ChannelService(
        channel_repository=SimpleNamespace(find_channels_by_ids=AsyncMock(return_value=channels)),
        space_channel_member_repository=SimpleNamespace(
            find_channel_memberships=AsyncMock(return_value=[SimpleNamespace(business_id=c.id) for c in channels])
        ),
        channel_info_source_repository=SimpleNamespace(),
        article_es_service=SimpleNamespace(),
        prospective_grant_application=SimpleNamespace(),
    )
    actor = SimpleNamespace(user_id=77, tenant_id=2, is_admin=lambda: False)
    monkeypatch.setattr(module, "resolve_permission_actor", AsyncMock(return_value=actor))
    with management_scope(home=2, target=2):
        _, _, tenant_id = await service._prospective_creation_access(actor)
    assert tenant_id == 2
    with bypass_tenant_filter():
        async with creation_budget.sessions() as session:
            for role_id in (2, 3):
                (await session.get(Role, role_id)).quota_config = {"channel": 0}
            await session.commit()
    with management_scope(home=2, target=2), pytest.raises(ChannelCreateLimitExceededError):
        await service._prospective_creation_access(actor)


async def test_space_creation_gate_uses_independent_budgets(creation_budget, monkeypatch):
    """AC-22: the real space guard preserves its resource-specific error."""
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=77, tenant_id=2, is_admin=lambda: False)
    monkeypatch.setattr(KnowledgeDao, "async_count_spaces_by_user", AsyncMock(return_value=5))
    with management_scope(home=2, target=2):
        await service._assert_space_creation_quota()
    with bypass_tenant_filter():
        async with creation_budget.sessions() as session:
            for role_id in (2, 3):
                (await session.get(Role, role_id)).quota_config = {"knowledge_space": 0}
            await session.commit()
    with management_scope(home=2, target=2), pytest.raises(SpaceLimitError):
        await service._assert_space_creation_quota()
