"""Upload picker keeps exact action semantics with bounded target preparation."""

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionEnumerationIncompleteError,
    PermissionFGAUnavailableError,
)
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.domain.schemas import VisibleObjectEnumerationResult
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge.test_knowledge_space_service import _make_login_user, _make_space

MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"


@pytest.fixture
def case():
    user = _make_login_user()
    actor = PermissionActor(user_id=user.user_id, current_tenant_id=1)
    rows = [_make_space(space_id=i) for i in range(370, 0, -1)]
    for row in rows:
        row.tenant_id = 1
        row.update_time = datetime(2026, 11, 2)

    async def snapshots(keys):
        return {key: PermissionResourceSnapshot(*key, 3, "ctx", "CUSTOM", None, None, "READY") for key in keys}

    versions = SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(versions), permission=SimpleNamespace()
    )
    service = KnowledgeSpaceService(None, user, f048_permission_adapter=adapter)
    allowed = {"369", "210", "1"}

    async def check(_actor, targets, action):
        assert action == "upload_file"
        return tuple(target.resource_id in allowed for target in targets)

    runtime = SimpleNamespace(
        batch_check_actions=AsyncMock(side_effect=check),
        list_visible_objects=AsyncMock(
            return_value=VisibleObjectEnumerationResult(
                resource_type="knowledge_space",
                object_ids=tuple(str(row.id) for row in rows),
                status="NORMAL",
                max_results=5000,
            )
        ),
    )

    async def candidates(ids, order_by, *, keyword):
        assert order_by == "update_time"
        return [row for row in rows if row.id in ids]

    async def scan(**kwargs):
        offset = (
            0
            if kwargs["cursor"] is None
            else next(i + 1 for i, row in enumerate(rows) if row.id == kwargs["cursor"][1])
        )
        return rows[offset : offset + kwargs["limit"]]

    with ExitStack() as stack:
        scan_mock = stack.enter_context(
            patch(f"{MODULE}.KnowledgeDao.aget_all_knowledge", new=AsyncMock(side_effect=scan))
        )
        actor_mock = stack.enter_context(patch.object(service, "_permission_actor", new=AsyncMock(return_value=actor)))
        candidate_mock = stack.enter_context(
            patch.object(service.space_listing_repository, "list_spaces", new=AsyncMock(side_effect=candidates))
        )
        stack.enter_context(patch(f"{MODULE}.get_f048_runtime", new=AsyncMock(return_value=runtime)))
        stack.enter_context(
            patch(
                "bisheng.permission.application.business_authorization.get_f048_runtime",
                new=AsyncMock(return_value=runtime),
            )
        )
        stack.enter_context(
            patch(f"{MODULE}.KnowledgeDao.aquery_by_id", new=AsyncMock(side_effect=AssertionError("per-space SELECT")))
        )
        stack.enter_context(
            patch.object(service, "_batch_actions", new=AsyncMock(side_effect=AssertionError("ID re-resolution")))
        )
        yield SimpleNamespace(
            service=service,
            actor=actor,
            actor_mock=actor_mock,
            rows=rows,
            versions=versions,
            runtime=runtime,
            allowed=allowed,
            scan=scan_mock,
            candidates=candidate_mock,
        )


async def test_bulk_preparation_keeps_exact_upload_permission_without_reloading_ids(case):
    result = await case.service.list_uploadable_spaces(keyword="report")
    assert [row.id for row in result] == [369, 210, 1]
    case.actor_mock.assert_awaited_once()
    assert case.versions.get_permission_snapshots.await_count == 4
    assert case.runtime.batch_check_actions.await_count == 4
    assert all(len(call.args[1]) <= 100 for call in case.runtime.batch_check_actions.await_args_list)
    case.scan.assert_not_awaited()
    case.candidates.assert_awaited_once_with([row.id for row in case.rows], "update_time", keyword="report")


async def test_sparse_visible_set_avoids_tenant_scan_and_checks_only_visible_candidates(case):
    case.runtime.list_visible_objects.return_value = case.runtime.list_visible_objects.return_value.model_copy(
        update={"object_ids": ("369", "210", "1")}
    )
    assert [row.id for row in await case.service.list_uploadable_spaces()] == [369, 210, 1]
    case.versions.get_permission_snapshots.assert_awaited_once()
    case.runtime.batch_check_actions.assert_awaited_once()
    assert len(case.runtime.batch_check_actions.await_args.args[1]) == 3
    case.scan.assert_not_awaited()


@pytest.mark.parametrize("limit", [1, 100, 200, 250])
async def test_limit_applies_to_authorized_rows_in_database_order(case, limit):
    case.allowed.update(str(row.id) for row in case.rows)
    result = await case.service.list_uploadable_spaces(limit=limit)
    assert [row.id for row in result] == [row.id for row in case.rows[:limit]]
    assert case.versions.get_permission_snapshots.await_count == (limit + 99) // 100
    case.scan.assert_not_awaited()


async def test_default_limit_and_full_scope_super_admin_fast_path(case):
    case.actor_mock.return_value = replace(case.actor, super_admin=True, data_scope=DATA_SCOPE_ALL)
    result = await case.service.list_uploadable_spaces()
    assert len(result) == 200
    assert [row.id for row in result] == [row.id for row in case.rows[:200]]
    case.versions.get_permission_snapshots.assert_not_awaited()
    case.runtime.batch_check_actions.assert_not_awaited()
    case.actor_mock.assert_awaited_once()
    case.runtime.list_visible_objects.assert_not_awaited()
    assert case.scan.await_count == 2
    assert case.scan.await_args_list[1].kwargs["cursor"] == [case.rows[99].update_time, case.rows[99].id]


async def test_narrowed_super_admin_keeps_runtime_data_scope_enforcement(case):
    case.actor_mock.return_value = replace(case.actor, super_admin=True, data_scope=DATA_SCOPE_PERSONAL)
    assert [row.id for row in await case.service.list_uploadable_spaces()] == [369, 210, 1]
    assert case.runtime.batch_check_actions.await_count == 4


async def test_tenant_admin_does_not_gain_a_new_personal_visibility_requirement(case):
    case.actor_mock.return_value = replace(case.actor, tenant_admin_tenant_ids=frozenset({1}))
    case.allowed.update(str(row.id) for row in case.rows)
    assert len(await case.service.list_uploadable_spaces()) == 200
    assert case.runtime.batch_check_actions.await_count == 2
    case.runtime.list_visible_objects.assert_not_awaited()
    case.candidates.assert_not_awaited()


async def test_narrowed_tenant_admin_cannot_bypass_visible_or_data_scope_filtering(case):
    case.actor_mock.return_value = replace(
        case.actor, tenant_admin_tenant_ids=frozenset({1}), data_scope=DATA_SCOPE_PERSONAL
    )
    assert [row.id for row in await case.service.list_uploadable_spaces()] == [369, 210, 1]
    case.runtime.list_visible_objects.assert_awaited_once()
    case.scan.assert_not_awaited()


async def test_invalid_business_rows_are_not_permission_targets(case):
    case.rows[1].tenant_id = 2  # The tenant adapter must reject the otherwise allowed row.
    case.rows[-1].state = 999
    assert [row.id for row in await case.service.list_uploadable_spaces()] == [210]
    checked = {
        target.resource_id for call in case.runtime.batch_check_actions.await_args_list for target in call.args[1]
    }
    assert "369" not in checked and "1" not in checked


async def test_disabled_action_produces_empty_picker(case):
    case.runtime.batch_check_actions.side_effect = InvalidCatalogActionError()
    assert await case.service.list_uploadable_spaces() == []


async def test_permission_outage_propagates_without_fallback(case):
    case.runtime.batch_check_actions.side_effect = PermissionFGAUnavailableError()
    with pytest.raises(PermissionFGAUnavailableError):
        await case.service.list_uploadable_spaces()
    case.scan.assert_not_awaited()
    case.candidates.assert_awaited_once()


@pytest.mark.parametrize("limit", [0, -1])
async def test_nonpositive_limit_has_no_io(case, limit):
    assert await case.service.list_uploadable_spaces(limit=limit) == []
    case.actor_mock.assert_not_awaited()
    case.scan.assert_not_awaited()


async def test_empty_visible_set_short_circuits_storage_and_actions(case):
    case.runtime.list_visible_objects.return_value = case.runtime.list_visible_objects.return_value.model_copy(
        update={"object_ids": ()}
    )
    assert await case.service.list_uploadable_spaces() == []
    case.candidates.assert_not_awaited()
    case.runtime.batch_check_actions.assert_not_awaited()
    case.scan.assert_not_awaited()


@pytest.mark.parametrize("bad", ["status", "type", "id", "noncanonical", "capacity", "unavailable"])
async def test_incomplete_visible_enumeration_fails_closed_without_tenant_scan(case, bad):
    updates = {
        "status": {"status": "incomplete"},
        "type": {"resource_type": "knowledge_file"},
        "id": {"object_ids": ("broken",)},
        "noncanonical": {"object_ids": ("01",)},
        "capacity": {"object_ids": tuple(str(i) for i in range(1, 5002))},
    }
    if bad == "unavailable":
        case.runtime.list_visible_objects.side_effect = PermissionFGAUnavailableError()
    else:
        case.runtime.list_visible_objects.return_value = case.runtime.list_visible_objects.return_value.model_copy(
            update=updates[bad]
        )
    with pytest.raises(PermissionFGAUnavailableError if bad == "unavailable" else PermissionEnumerationIncompleteError):
        await case.service.list_uploadable_spaces()
    case.candidates.assert_not_awaited()
    case.scan.assert_not_awaited()
