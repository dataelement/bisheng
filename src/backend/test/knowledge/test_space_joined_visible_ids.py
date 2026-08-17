"""F048 joined-space listing uses the complete personal visible-ID set."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import sqlite

from bisheng.common.errcode.permission import PermissionEnumerationIncompleteError
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeDao,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.schemas import (
    VisibilityEnumerationStatus,
    VisibleObjectEnumerationResult,
)

_SERVICE = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 41
    tenant_id = 7
    is_global_super = False

    def is_admin(self) -> bool:
        return False


def _space(space_id: int, *, creator: int, minutes: int) -> Knowledge:
    timestamp = datetime(2026, 8, 13, 8, 0) + timedelta(minutes=minutes)
    return Knowledge(
        id=space_id,
        user_id=creator,
        tenant_id=7,
        name=f"space-{space_id}",
        type=KnowledgeTypeEnum.SPACE.value,
        state=KnowledgeState.PUBLISHED.value,
        create_time=timestamp,
        update_time=timestamp,
    )


def _visible(*object_ids: str) -> VisibleObjectEnumerationResult:
    return VisibleObjectEnumerationResult(
        resource_type="knowledge_space",
        object_ids=object_ids,
        max_results=5_000,
        status=VisibilityEnumerationStatus.NORMAL,
    )


def _actor() -> SimpleNamespace:
    return SimpleNamespace(
        user_id=_User.user_id,
        current_tenant_id=_User.tenant_id,
        super_admin=False,
        tenant_admin_tenant_ids=frozenset(),
    )


async def test_joined_repository_applies_tenant_active_type_creator_and_stable_order_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace()
    captured = None

    class _Rows:
        @staticmethod
        def all() -> list[Knowledge]:
            return []

    async def _exec(statement):
        nonlocal captured
        captured = statement
        return _Rows()

    session.exec = _exec

    @asynccontextmanager
    async def _session_context():
        yield session

    monkeypatch.setattr(knowledge_module, "get_async_db_session", _session_context)
    await KnowledgeDao.async_get_joined_spaces_by_visible_ids(
        [10, 20],
        tenant_id=7,
        exclude_creator_id=41,
        order_by="update_time",
    )

    sql = str(
        captured.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    compact = " ".join(sql.split())
    assert "knowledge.id in (10, 20)" in compact
    assert "knowledge.tenant_id = 7" in compact
    assert f"knowledge.type = {KnowledgeTypeEnum.SPACE.value}" in compact
    assert f"knowledge.state = {KnowledgeState.PUBLISHED.value}" in compact
    assert "knowledge.user_id != 41" in compact
    assert "order by knowledge.update_time desc, knowledge.id desc" in compact


async def test_joined_uses_all_visible_sources_and_only_lightweight_db_results() -> None:
    """The source kind is irrelevant once every source projects canonical visible."""

    service = KnowledgeSpaceService(request=None, login_user=_User())
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(
            return_value=_visible("101", "102", "103", "104", "105")
        )
    )
    rows = [
        _space(105, creator=99, minutes=5),  # another valid projected source
        _space(104, creator=99, minutes=4),  # manual subscription
        _space(103, creator=99, minutes=3),  # group grant
        _space(102, creator=99, minutes=2),  # department grant
        _space(101, creator=99, minutes=1),  # direct grant
    ]

    with (
        patch.object(service, "_permission_actor", new=AsyncMock(return_value=_actor())),
        patch(f"{_SERVICE}.get_f048_runtime", new=AsyncMock(return_value=runtime)),
        patch(
            f"{_SERVICE}.KnowledgeDao.async_get_joined_spaces_by_visible_ids",
            new=AsyncMock(return_value=rows),
        ) as list_rows,
        patch(
            f"{_SERVICE}.KnowledgeSpaceUserPinDao.list_pinned_space_ids",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            f"{_SERVICE}.SpaceChannelMemberDao.async_get_user_followed_members",
            new=AsyncMock(side_effect=AssertionError("joined must not read membership")),
        ),
        patch.object(
            service,
            "_batch_actions",
            new=AsyncMock(side_effect=AssertionError("joined must not repeat visible or read actions")),
        ),
        patch.object(
            service,
            "_populate_root_file_counts",
            new=AsyncMock(side_effect=AssertionError("joined must not count files")),
        ),
        patch.object(
            service,
            "_decorate_department_metadata",
            new=AsyncMock(side_effect=AssertionError("joined must not load department metadata")),
        ),
    ):
        result = await service.get_my_followed_spaces("update_time")

    runtime.list_visible_objects.assert_awaited_once()
    call = runtime.list_visible_objects.await_args
    assert call.kwargs["resource_type"] == "knowledge_space"
    assert call.kwargs["max_results"] == 5_000
    assert call.args[0].user_id == _User.user_id
    assert call.args[0].current_tenant_id == _User.tenant_id
    list_rows.assert_awaited_once_with(
        [101, 102, 103, 104, 105],
        tenant_id=7,
        exclude_creator_id=41,
        order_by="update_time",
    )
    assert [item.id for item in result] == [105, 104, 103, 102, 101]
    assert all(
        key not in item.model_dump()
        for item in result
        for key in ("user_role", "file_num", "department_id", "department_name")
    )
    assert all(item.actions is None for item in result)


async def test_joined_chunks_visible_ids_and_excludes_canonical_creator() -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    visible_ids = tuple(str(index) for index in range(1, 1_002))
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=_visible(*visible_ids)))
    owned = _space(1, creator=_User.user_id, minutes=20)
    other_old = _space(500, creator=88, minutes=10)
    other_new = _space(1_001, creator=88, minutes=30)
    db_calls: list[list[int]] = []

    async def _list_chunk(
        ids: list[int],
        *,
        tenant_id: int,
        exclude_creator_id: int,
        order_by: str,
    ) -> list[Knowledge]:
        assert tenant_id == 7
        assert exclude_creator_id == 41
        assert order_by == "update_time"
        db_calls.append(ids)
        return [row for row in (owned, other_old, other_new) if row.id in ids and row.user_id != 41]

    with (
        patch.object(service, "_permission_actor", new=AsyncMock(return_value=_actor())),
        patch(f"{_SERVICE}.get_f048_runtime", new=AsyncMock(return_value=runtime)),
        patch(
            f"{_SERVICE}.KnowledgeDao.async_get_joined_spaces_by_visible_ids",
            new=AsyncMock(side_effect=_list_chunk),
        ),
        patch(
            f"{_SERVICE}.KnowledgeSpaceUserPinDao.list_pinned_space_ids",
            new=AsyncMock(return_value={500}),
        ),
    ):
        result = await service.get_my_followed_spaces("update_time")

    assert [len(chunk) for chunk in db_calls] == [500, 500, 1]
    assert [item.id for item in result] == [500, 1_001]
    assert [item.is_pinned for item in result] == [True, False]


@pytest.mark.parametrize("identity_kind", ["ordinary", "super_admin", "tenant_admin"])
async def test_joined_admin_identities_use_the_same_personal_visible_enumeration(
    identity_kind: str,
) -> None:
    user = _User()
    if identity_kind == "super_admin":
        user.is_global_super = True
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=_visible()))
    actor = SimpleNamespace(
        user_id=user.user_id,
        current_tenant_id=user.tenant_id,
        super_admin=identity_kind == "super_admin",
        tenant_admin_tenant_ids=(frozenset({user.tenant_id}) if identity_kind == "tenant_admin" else frozenset()),
    )
    service = KnowledgeSpaceService(request=None, login_user=user)

    with (
        patch.object(service, "_permission_actor", new=AsyncMock(return_value=actor)),
        patch(f"{_SERVICE}.get_f048_runtime", new=AsyncMock(return_value=runtime)),
    ):
        assert await service.get_my_followed_spaces() == []

    runtime.list_visible_objects.assert_awaited_once_with(
        actor,
        resource_type="knowledge_space",
        max_results=5_000,
    )


@pytest.mark.parametrize("reason", ["stream failed", "5,001 visible objects"])
async def test_joined_propagates_incomplete_visible_enumeration_as_25014(reason: str) -> None:
    service = KnowledgeSpaceService(request=None, login_user=_User())
    failure = PermissionEnumerationIncompleteError(msg=reason)
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(side_effect=failure))

    with (
        patch.object(service, "_permission_actor", new=AsyncMock(return_value=_actor())),
        patch(f"{_SERVICE}.get_f048_runtime", new=AsyncMock(return_value=runtime)),
    ):
        with pytest.raises(PermissionEnumerationIncompleteError) as exc_info:
            await service.get_my_followed_spaces()

    assert exc_info.value.Code == 25014
