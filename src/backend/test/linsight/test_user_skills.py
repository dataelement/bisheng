from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.linsight.domain.services.user_skills import SkillAvailabilityRepository, UserSkillsService, visible_to


def record(id, source="builtin", owner=None):
    return SimpleNamespace(id=id, name=f"skill-{id}", source=source, created_by=owner)


@pytest.mark.parametrize("owner,current,allowed", [(7, 7, True), (7, 8, False), (7, None, False)])
def test_personal_ownership(owner, current, allowed):
    assert visible_to(record(1, "personal", owner), current) is allowed
    assert visible_to(record(2), current)


async def test_account_switches_keep_disabled_entries_manageable_and_filter_runtime(monkeypatch):
    from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao

    rows = [record(1), record(2, "personal", 7), record(3, "personal", 8)]
    monkeypatch.setattr(LinsightSkillDao, "list_enabled", AsyncMock(return_value=rows))
    repo = SimpleNamespace(disabled_ids=AsyncMock(return_value={1}), save=AsyncMock())
    service = UserSkillsService(7, repo)
    assert [(r.id, on) for r, on in await service.records(False)] == [(1, False), (2, True)]
    assert [r.id for r, _ in await service.records()] == [2]
    with pytest.raises(HTTPException):
        await service.require(1)
    await service.toggle(1, True)
    repo.save.assert_awaited_once_with(7, 1, True)
    for id in [1, 3]:
        with pytest.raises(HTTPException):
            await service.personal(id)
    assert (await service.personal(2)).id == 2
    with pytest.raises(HTTPException):
        await service.toggle(3, True)


def test_durable_settings_include_tenant_account_and_skill_namespace():
    set_current_tenant_id(2)
    assert SkillAvailabilityRepository.prefix(7) == "user-skill-availability:2:7:"
    set_current_tenant_id(3)
    assert SkillAvailabilityRepository.prefix(7) == "user-skill-availability:3:7:"
    set_current_tenant_id(None)
    with pytest.raises(PermissionError):
        SkillAvailabilityRepository.prefix(7)
