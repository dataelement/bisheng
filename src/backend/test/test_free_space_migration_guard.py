import pytest
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.knowledge.domain.services.free_space_migration_service import (
    FreeSpaceMigrationService,
)

MOD = "bisheng.knowledge.domain.services.free_space_migration_service"


class _Space:
    def __init__(self, id, user_id, state=KnowledgeState.PUBLISHED.value, model="emb-1"):
        self.id = id
        self.user_id = user_id
        self.state = state
        self.model = model


class _Scope:
    def __init__(self, level):
        self.level = level


def _patches(*, binding=None, scope_level="team", target_id=None, target_model="emb-1"):
    return [
        patch(f"{MOD}.DepartmentKnowledgeSpaceDao.aget_by_space_id", new=AsyncMock(return_value=binding)),
        patch(f"{MOD}.KnowledgeSpaceScopeDao.aget_by_space_id", new=AsyncMock(return_value=_Scope(scope_level))),
        patch.object(FreeSpaceMigrationService, "resolve_target_department_space", new=AsyncMock(return_value=target_id)),
        patch(f"{MOD}.KnowledgeDao.aquery_by_id", new=AsyncMock(return_value=_Space(target_id, 0, model=target_model) if target_id else None)),
    ]


async def _run(space, **kw):
    ps = _patches(**kw)
    for p in ps:
        p.start()
    try:
        return await FreeSpaceMigrationService.pre_delete_guard(space)
    finally:
        for p in ps:
            p.stop()


@pytest.mark.asyncio
async def test_migrating_state_blocks():
    d = await _run(_Space(1, 5, state=KnowledgeState.COPYING.value))
    assert d.action == "block"
    assert d.reason == "migrating"


@pytest.mark.asyncio
async def test_bound_department_space_blocks():
    d = await _run(_Space(1, 5), binding=object())
    assert d.action == "block"
    assert d.reason == "department_space_forbidden"


@pytest.mark.asyncio
async def test_non_team_space_normal_delete():
    d = await _run(_Space(1, 5), scope_level="personal")
    assert d.action == "normal_delete"


@pytest.mark.asyncio
async def test_free_space_no_target_blocks():
    d = await _run(_Space(1, 5), target_id=None)
    assert d.action == "block"
    assert d.reason == "target_not_found"


@pytest.mark.asyncio
async def test_free_space_embedding_mismatch_blocks():
    d = await _run(_Space(1, 5, model="emb-1"), target_id=900, target_model="emb-2")
    assert d.action == "block"
    assert d.reason == "embedding_mismatch"


@pytest.mark.asyncio
async def test_free_space_ok_migrates():
    d = await _run(_Space(1, 5, model="emb-1"), target_id=900, target_model="emb-1")
    assert d.action == "migrate"
    assert d.target_space_id == 900
