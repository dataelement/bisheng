"""F048 visible-ids-first refactor of ``/api/v1/knowledge`` list.

These tests cover the three branches added to
``KnowledgeService.get_knowledge``:

  * regular user → ``list_visible_objects("knowledge_library")`` is called and
    its result is threaded into ``KnowledgeDao.aget_all_knowledge`` as
    ``id_in``; for ``action != "visible"`` the per-batch BatchCheck still
    narrows the result;
  * super admin / tenant admin → the F048 runtime is not touched and ``id_in``
    is ``None`` (unfiltered);
  * every returned row carries only the already-proven ``visible`` marker;
  * empty visible set → an empty page is returned without hitting the DB.

Plus a handler-level check that ``type=3`` (SPACE) is rejected with the new
``KnowledgeSpaceListNotSupportedError``.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge import KnowledgeSpaceListNotSupportedError
from bisheng.knowledge.domain.models.knowledge import (
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.services import knowledge_service as ks_mod
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.permission.domain.schemas import (
    VisibilityEnumerationStatus,
    VisibleObjectEnumerationResult,
)


class _User:
    """The minimum interface ``resolve_permission_actor`` reads."""

    user_id = 41
    tenant_id = 7


def _knowledge(kid: int, *, name: str = "kb", minutes: int = 0) -> Knowledge:
    stamp = datetime(2026, 8, 13, 8, minutes)
    return Knowledge(
        id=kid,
        user_id=_User.user_id,
        tenant_id=_User.tenant_id,
        name=f"{name}-{kid}",
        type=KnowledgeTypeEnum.NORMAL.value,
        state=KnowledgeState.PUBLISHED.value,
        create_time=stamp,
        update_time=stamp,
    )


def _visible(*ids: str) -> VisibleObjectEnumerationResult:
    return VisibleObjectEnumerationResult(
        resource_type="knowledge_library",
        object_ids=ids,
        max_results=5_000,
        status=VisibilityEnumerationStatus.NORMAL,
    )


def _actor(*, super_admin: bool = False, tenant_admin: bool = False) -> SimpleNamespace:
    admin_tenants = frozenset({_User.tenant_id}) if tenant_admin else frozenset()
    return SimpleNamespace(
        user_id=_User.user_id,
        current_tenant_id=_User.tenant_id,
        super_admin=super_admin,
        tenant_admin_tenant_ids=admin_tenants,
    )


def _stub_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The list envelope enriches rows through UserDao — short-circuit it."""

    monkeypatch.setattr(
        ks_mod.UserDao,
        "get_user_by_ids",
        lambda _ids: [SimpleNamespace(user_id=_User.user_id, user_name="alice")],
    )
    monkeypatch.setattr(ks_mod, "emit_metric", lambda *a, **k: None)


@pytest.mark.asyncio
async def test_regular_user_threads_visible_ids_into_dao_and_runs_use_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_enrichment(monkeypatch)

    visible_result = _visible("100", "101", "102")
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=visible_result))
    monkeypatch.setattr(ks_mod, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(ks_mod, "resolve_permission_actor", AsyncMock(return_value=_actor()))

    dao_calls: list[dict] = []

    async def _fake_aget_all_knowledge(*args, **kwargs):
        dao_calls.append(kwargs)
        # First (and only) call returns two rows — the second is dropped because
        # the per-batch ``use`` check filters it out.
        return [_knowledge(100), _knowledge(101)]

    monkeypatch.setattr(ks_mod.KnowledgeDao, "aget_all_knowledge", _fake_aget_all_knowledge)

    action_map_calls: list[list[str]] = []

    async def _fake_action_map(login_user, ids, actions):
        action_map_calls.append(list(actions))
        # Only id=100 has ``use``; id=101 is visible but not use-able.
        return {100: {"use", "visible"}, 101: {"visible"}}

    with patch.object(
        KnowledgeService.permission_service,
        "get_knowledge_action_map_async",
        side_effect=_fake_action_map,
    ):
        page = await KnowledgeService.get_knowledge(
            request=None,
            login_user=_User(),
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            page_size=10,
            action="use",
        )

    # visible enumeration was asked for the library type at the shared cap.
    runtime.list_visible_objects.assert_awaited_once()
    call = runtime.list_visible_objects.await_args
    assert call.kwargs["resource_type"] == "knowledge_library"
    assert call.kwargs["max_results"] == 5_000

    # The DAO scan received the visible ids as its ``id_in`` filter.
    assert dao_calls, "DAO must be called for a non-empty visible set"
    assert dao_calls[0]["id_in"] == [100, 101, 102]

    # Only the requested ``use`` filter is checked. The surviving page is not
    # decorated with unrelated actions.
    assert action_map_calls == [["use"]]

    # Only id=100 survived the ``use`` check; the row is decorated from the
    # already-proven visible marker.
    assert [row.id for row in page.data] == [100]
    assert page.data[0].actions == ["visible"]
    assert page.has_more is False


@pytest.mark.asyncio
async def test_regular_visible_list_does_not_load_page_action_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_enrichment(monkeypatch)

    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=_visible("100")))
    monkeypatch.setattr(ks_mod, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(ks_mod, "resolve_permission_actor", AsyncMock(return_value=_actor()))
    monkeypatch.setattr(
        ks_mod.KnowledgeDao,
        "aget_all_knowledge",
        AsyncMock(return_value=[_knowledge(100)]),
    )

    with patch.object(
        KnowledgeService.permission_service,
        "get_knowledge_action_map_async",
        new=AsyncMock(),
    ) as action_map:
        page = await KnowledgeService.get_knowledge(
            request=None,
            login_user=_User(),
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            page_size=10,
            action="visible",
        )

    action_map.assert_not_awaited()
    assert [row.id for row in page.data] == [100]
    assert page.data[0].actions == ["visible"]


@pytest.mark.asyncio
async def test_regular_user_empty_visible_set_short_circuits_before_dao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_enrichment(monkeypatch)

    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=_visible()))
    monkeypatch.setattr(ks_mod, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(ks_mod, "resolve_permission_actor", AsyncMock(return_value=_actor()))

    dao_calls: list[dict] = []

    async def _fake_aget_all_knowledge(*args, **kwargs):
        dao_calls.append(kwargs)
        return []

    monkeypatch.setattr(ks_mod.KnowledgeDao, "aget_all_knowledge", _fake_aget_all_knowledge)

    with patch.object(
        KnowledgeService.permission_service,
        "get_knowledge_action_map_async",
        new=AsyncMock(return_value={}),
    ) as action_map:
        page = await KnowledgeService.get_knowledge(
            request=None,
            login_user=_User(),
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            page_size=10,
            action="use",
        )

    runtime.list_visible_objects.assert_awaited_once()
    # Empty visible set → no DAO scan and no per-batch BatchCheck.
    assert dao_calls == []
    action_map.assert_not_awaited()
    assert page.data == []
    assert page.has_more is False
    assert page.next_cursor is None


@pytest.mark.parametrize("identity_kind", ["super_admin", "tenant_admin"])
@pytest.mark.asyncio
async def test_admin_bypass_skips_permission_runtime_and_returns_visible_only(
    monkeypatch: pytest.MonkeyPatch,
    identity_kind: str,
) -> None:
    _stub_enrichment(monkeypatch)

    runtime = SimpleNamespace(list_visible_objects=AsyncMock())
    monkeypatch.setattr(ks_mod, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        ks_mod,
        "resolve_permission_actor",
        AsyncMock(
            return_value=_actor(
                super_admin=(identity_kind == "super_admin"),
                tenant_admin=(identity_kind == "tenant_admin"),
            )
        ),
    )

    dao_calls: list[dict] = []

    async def _fake_aget_all_knowledge(*args, **kwargs):
        dao_calls.append(kwargs)
        return [_knowledge(200), _knowledge(201)]

    monkeypatch.setattr(ks_mod.KnowledgeDao, "aget_all_knowledge", _fake_aget_all_knowledge)

    permission_mock = AsyncMock()
    with patch.object(
        KnowledgeService.permission_service,
        "get_knowledge_action_map_async",
        new=permission_mock,
    ):
        page = await KnowledgeService.get_knowledge(
            request=None,
            login_user=_User(),
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            page_size=10,
            action="use",
        )

    # Admin path — no F048 enumeration, no BatchCheck.
    runtime.list_visible_objects.assert_not_awaited()
    permission_mock.assert_not_awaited()

    # DAO scan runs unfiltered (id_in=None).
    assert dao_calls, "DAO must still be scanned for the admin path"
    assert dao_calls[0]["id_in"] is None

    # Admin list rows use the same minimal response shape as ordinary users.
    assert {row.id for row in page.data} == {200, 201}
    for row in page.data:
        assert row.actions == ["visible"]


@pytest.mark.asyncio
async def test_handler_rejects_knowledge_space_type() -> None:
    """`/api/v1/knowledge` does not serve knowledge spaces regardless of role.

    The handler raises ``KnowledgeSpaceListNotSupportedError`` before any
    service work runs — a super admin previously received the full SPACE set
    because the resource-type mismatch was only detected inside F048 target
    resolution, which super_admin bypassed.
    """
    from bisheng.knowledge.api.endpoints import knowledge as endpoint

    with pytest.raises(Exception) as excinfo:
        await endpoint.get_knowledge(
            request=None,
            login_user=MagicMock(),
            action="visible",
            name=None,
            knowledge_type=KnowledgeTypeEnum.SPACE.value,
            sort_by="update_time",
            preferred_ids=None,
            page_size=10,
            cursor=None,
        )
    assert excinfo.value.status_code == KnowledgeSpaceListNotSupportedError.Code
