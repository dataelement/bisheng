"""Personal skills resolve for their owner. Enterprise skills do not."""

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.linsight.domain.services.f048_skill_permission import (
    F048SkillPermissionAdapter,
    SkillPermissionRecord,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def _record(**overrides) -> SkillPermissionRecord:
    values = {
        "tenant_id": 5,
        "resource_id": "4",
        "owner_user_id": 11,
        "permission_version": 0,
        "context_version": "a" * 64,
    }
    values.update(overrides)
    return SkillPermissionRecord(**values)


class _Loader:
    def __init__(self, record: SkillPermissionRecord | None) -> None:
        self.record = record

    async def load_permission_record(self, resource_id: str) -> SkillPermissionRecord | None:
        if self.record is None or self.record.resource_id != resource_id:
            return None
        return self.record


def _actor(user_id: int = 11, tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=user_id, current_tenant_id=tenant_id)


class TestSkillPermissionPort:
    async def test_the_owner_resolves_the_skill(self):
        adapter = F048SkillPermissionAdapter(loader=_Loader(_record()), permission=object())
        target = await adapter.resolve_permission_target(resource_id="4", actor=_actor(), action="edit")
        assert target.resource_type == "linsight_skill"
        assert target.resource_id == "4"
        assert target.tenant_id == 5
        assert target.resource_version == 0

    async def test_someone_else_or_a_missing_row_is_not_a_target(self):
        adapter = F048SkillPermissionAdapter(loader=_Loader(_record()), permission=object())
        with pytest.raises(PermissionInvalidResourceError):
            await adapter.resolve_permission_target(resource_id="4", actor=_actor(user_id=22), action="delete")
        empty = F048SkillPermissionAdapter(loader=_Loader(None), permission=object())
        with pytest.raises(PermissionInvalidResourceError):
            await empty.resolve_permission_target(resource_id="4", actor=_actor(), action="edit")
