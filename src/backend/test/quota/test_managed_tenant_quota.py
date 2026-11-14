"""F009 AC-20..27: counts and independent role / tenant remaining."""

from types import SimpleNamespace

import pytest
from sqlmodel import delete

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.errcode.tenant_quota import (
    QuotaResponsibilityChangedError,
    QuotaUsageUnavailableError,
    TenantRoleQuotaExceededError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.flow import Flow
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant
from bisheng.database.models.user_role import UserRole
from bisheng.role.domain.services.quota_service import QuotaService
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def quota_db(policy_db, monkeypatch):
    import bisheng.database.models.tenant as tenants
    from bisheng.role.domain.repositories import quota_repository

    await policy_db.create(Flow, Channel)
    monkeypatch.setattr(quota_repository, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(tenants, "get_async_db_session", policy_db.sessions)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            for role_id in (2, 3):
                (await session.get(Role, role_id)).quota_config = {"workflow": 10, "channel": 0}
            (await session.get(Tenant, 2)).quota_config = {"workflow": 8}
            session.add_all(
                [Flow(id=f"f-{i}", name=f"flow-{i}", user_id=77, tenant_id=2, flow_type=10) for i in range(5)]
            )
            session.add(Flow(id="old", name="old", user_id=77, tenant_id=1, flow_type=10))
            session.add_all(
                [
                    Channel(id="old-a", name="old", user_id=77, tenant_id=1, visibility="private", source_list=["old"]),
                    Channel(
                        id="new-a", name="new", user_id=77, tenant_id=2, visibility="private", source_list=["a", "b"]
                    ),
                    Channel(
                        id="new-b", name="new2", user_id=77, tenant_id=2, visibility="private", source_list=["b", "c"]
                    ),
                ]
            )
            await session.commit()
    return policy_db


async def test_user_counts_are_q_and_t_not_all_historical_tenants(quota_db):
    """AC-21: M and historical rows cannot inflate the home count."""
    with management_scope(home=2, target=3):
        assert await QuotaService.get_user_resource_count(77, "workflow", tenant_id=2) == 5
        assert await QuotaService._distinct_info_source_ids("user_id", 77, tenant_id=2) == {"a", "b", "c"}


async def test_role_ten_user_five_tenant_three_allows_one(quota_db, monkeypatch):
    """AC-22: cumulative user usage is not compared to tenant remaining."""
    actor = SimpleNamespace(user_id=77, tenant_id=2, is_admin=lambda: False)
    with management_scope(home=2, target=3):
        assert await QuotaService.check_quota(77, "workflow", 2, login_user=actor)
    import bisheng.role.domain.services.quota_service as module

    monkeypatch.setattr(module, "DEFAULT_ROLE_QUOTA", {"workflow": -1})
    items = await QuotaService.get_all_effective_quotas(77, 2, login_user=actor)
    assert items[0].available == 3 and items[0].user_used == 5


async def test_global_zero_is_not_default_when_view_changes(quota_db):
    """AC-20: both effective roles explicitly deny channel creation."""
    with management_scope(home=2, target=3), pytest.raises(TenantRoleQuotaExceededError):
        await QuotaService.check_quota(77, "channel", 2)


async def test_missing_table_is_unknown_not_zero(policy_db, monkeypatch):
    """AC-23: a real SQL count failure cannot allow a subsequent increment."""
    from bisheng.role.domain.repositories import quota_repository

    monkeypatch.setattr(quota_repository, "get_async_db_session", policy_db.sessions)
    with pytest.raises(QuotaUsageUnavailableError):
        await QuotaService.get_user_resource_count(77, "workflow", tenant_id=2)


async def test_old_channel_responsibility_cannot_use_current_tenant_budget(quota_db):
    """AC-24/25: q is now H=2, resource belongs to T=1; no editor substitution."""
    with pytest.raises(QuotaResponsibilityChangedError):
        await QuotaService.check_info_source_subscribe_limit(77, 1, ["new-source"])
    # No net new source in that budget is maintenance, not an increment.
    await QuotaService.check_info_source_subscribe_limit(77, 1, ["old"])


async def test_subscription_count_keeps_root_and_excludes_foreign_child(quota_db):
    """AC-21/37: Root subscription budget remains, foreign child membership does not."""
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        SpaceChannelMember,
        UserRoleEnum,
    )

    await quota_db.create(SpaceChannelMember)
    with bypass_tenant_filter():
        async with quota_db.sessions() as session:
            session.add(Channel(id="foreign", name="B", user_id=77, tenant_id=3, visibility="private"))
            session.add_all(
                [
                    SpaceChannelMember(
                        id=i,
                        business_id=cid,
                        business_type=BusinessTypeEnum.CHANNEL,
                        user_id=77,
                        user_role=UserRoleEnum.MEMBER,
                        status=MembershipStatusEnum.ACTIVE,
                    )
                    for i, cid in enumerate(["old-a", "new-a", "foreign"], 1)
                ]
            )
            await session.commit()
    assert await QuotaService.get_user_resource_count(77, "channel_subscribe", tenant_id=2) == 2
    assert await QuotaService.get_tenant_resource_count(2, "channel_subscribe") == 1


async def test_space_subscription_count_keeps_root_and_excludes_foreign_child(quota_db):
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        SpaceChannelMember,
        UserRoleEnum,
    )
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    await quota_db.create(Knowledge, SpaceChannelMember)
    with bypass_tenant_filter():
        async with quota_db.sessions() as session:
            for space_id, tenant_id in ((10, 1), (20, 2), (30, 3)):
                session.add(Knowledge(id=space_id, tenant_id=tenant_id, user_id=77, name=f"space-{space_id}", type=3))
                session.add(
                    SpaceChannelMember(
                        id=space_id,
                        business_id=str(space_id),
                        business_type=BusinessTypeEnum.SPACE,
                        user_id=77,
                        user_role=UserRoleEnum.MEMBER,
                        status=MembershipStatusEnum.ACTIVE,
                    )
                )
            await session.commit()
    assert await QuotaService.get_user_resource_count(77, "knowledge_space_subscribe", tenant_id=2) == 2
    assert await QuotaService.get_tenant_resource_count(2, "knowledge_space_subscribe") == 1
