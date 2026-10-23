"""Current identity adapter delegates to existing user and membership lookups."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords


async def test_current_membership_and_deleted_user_are_not_cached(monkeypatch):
    from bisheng.database.models.tenant import TenantDao, UserTenantDao
    from bisheng.user.domain.models.user import UserDao

    user = SimpleNamespace(user_id=1001, user_name="alice", delete=0, dsh_profile_version=3)
    membership = SimpleNamespace(tenant_id=2, status="active", is_active=1)
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(return_value=user))
    monkeypatch.setattr(UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=membership))
    monkeypatch.setattr(
        TenantDao, "aget_by_id", AsyncMock(return_value=SimpleNamespace(status="active", tenant_name="Team"))
    )
    records = CurrentIdentityRecords()
    assert (await records.get("2", "1001")).active
    assert await records.get("3", "1001") is None
    user.delete = 1
    assert not (await records.get("2", "1001")).active
    membership.status = "disabled"
    assert not (await records.get("2", "1001")).tenant_active
