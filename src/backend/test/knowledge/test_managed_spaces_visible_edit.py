"""F116 offline contracts; real service/adapter/helper, substituted storage and FGA.

Counts below are I/O-boundary calls, not production latency measurements.
"""

from contextlib import ExitStack, asynccontextmanager
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mysql
from sqlmodel import Session, create_engine

from bisheng.common.errcode.permission import PermissionEnumerationIncompleteError, PermissionFGAUnavailableError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.knowledge_space_listing_repository import KnowledgeSpaceListingRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL
from bisheng.permission.domain.schemas import VisibilityEnumerationStatus, VisibleObjectEnumerationResult
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge.test_knowledge_space_service import _make_login_user, _make_member, _make_space

MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"
BUSINESS = "bisheng.permission.application.business_authorization"


@pytest.fixture
def case():
    user = _make_login_user()
    actor = PermissionActor(user_id=user.user_id, current_tenant_id=1)
    rows = [_make_space(space_id=i, user_id=user.user_id if i == 1 else 99) for i in range(1, 8)]
    for row in rows:
        row.tenant_id = 1
    grants = {
        "edit": {"1", "2", "3", "6", "7"},
        "visible": {"1", "2", "3", "4", "5", "7"},
        "manage_permission": {"2", "5", "7"},
    }

    async def check(_actor, targets, action):
        return tuple(target.resource_id in grants[action] for target in targets)

    async def snapshots(keys):
        return {key: PermissionResourceSnapshot(*key, 3, "ctx3", "CUSTOM", None, None, "READY") for key in keys}

    versions = SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(versions), permission=SimpleNamespace()
    )
    service = KnowledgeSpaceService(None, user, f048_permission_adapter=adapter)
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(
            return_value=VisibleObjectEnumerationResult(
                resource_type="knowledge_space",
                object_ids=tuple(str(row.id) for row in rows),
                status=VisibilityEnumerationStatus.NORMAL,
                max_results=5000,
            )
        ),
        batch_check_actions=AsyncMock(side_effect=check),
    )
    members = [_make_member(user_id=user.user_id, space_id=2, user_role=UserRoleEnum.ADMIN)]
    with ExitStack() as stack:

        def mock(path, **kwargs):
            return stack.enter_context(patch(f"{MODULE}.{path}", new_callable=AsyncMock, **kwargs))

        state = SimpleNamespace(
            user=user,
            actor=actor,
            service=service,
            rows=rows,
            runtime=runtime,
            versions=versions,
            grants=grants,
            actor_mock=stack.enter_context(
                patch.object(service, "_permission_actor", new=AsyncMock(return_value=actor))
            ),
            candidates=stack.enter_context(
                patch.object(service.space_listing_repository, "list_spaces", new=AsyncMock(return_value=rows))
            ),
            members=mock("SpaceChannelMemberDao.async_get_user_managed_members", return_value=members),
            pins=mock("KnowledgeSpaceUserPinDao.list_pinned_space_ids", return_value={7}),
            counts=stack.enter_context(patch.object(service, "_populate_root_file_counts", new=AsyncMock())),
            department=stack.enter_context(
                patch.object(service, "_decorate_department_metadata", new=AsyncMock(side_effect=lambda items: items))
            ),
            metrics=stack.enter_context(patch(f"{MODULE}.emit_metric")),
        )
        mock("get_f048_runtime", return_value=runtime)
        stack.enter_context(patch(f"{BUSINESS}.get_f048_runtime", new=AsyncMock(return_value=runtime)))
        # A reintroduced tenant scan or ID re-resolution must fail this suite.
        mock("KnowledgeDao.aget_all_knowledge", side_effect=AssertionError("tenant scan"))
        mock("KnowledgeDao.aquery_by_id", side_effect=AssertionError("per-space lookup"))
        yield state


async def test_ac01_visible_intersect_edit_and_roles_pins_database_order(case):
    """AC-01/05: viewer and manage-only excluded; creator/admin/editor retained."""
    result = await case.service.get_my_managed_spaces()
    assert [item.id for item in result] == [7, 1, 2, 3]
    assert [item.user_role for item in result] == [
        UserRoleEnum.ADMIN,
        UserRoleEnum.CREATOR,
        UserRoleEnum.ADMIN,
        UserRoleEnum.MEMBER,
    ]
    assert all(item.is_followed for item in result)
    case.candidates.assert_awaited_once_with(list(range(1, 8)), "name")
    calls = case.runtime.batch_check_actions.await_args_list
    assert [(call.args[2], [t.resource_id for t in call.args[1]]) for call in calls] == [
        ("edit", [str(i) for i in range(1, 8)]),
        ("visible", ["1", "2", "3", "6", "7"]),
        ("manage_permission", ["3", "7"]),
    ]
    case.counts.assert_awaited_once()
    case.department.assert_awaited_once()


@pytest.mark.parametrize("count", [1, 100, 101, 1001])
async def test_ac03_permission_preparation_scales_by_batches_not_tenant_size(case, count):
    """AC-03: visible candidates produce bounded batch work; no tenant scan."""
    rows = [_make_space(space_id=i, user_id=99) for i in range(1, count + 1)]
    for row in rows:
        row.tenant_id = 1
    case.runtime.list_visible_objects.return_value = case.runtime.list_visible_objects.return_value.model_copy(
        update={"object_ids": tuple(str(row.id) for row in rows)}
    )
    case.candidates.return_value = rows
    case.grants["edit"] = {str(row.id) for row in rows}
    case.grants["visible"] = case.grants["edit"]
    case.members.return_value = []
    result = await case.service.get_my_managed_spaces()
    assert len(result) == count
    assert case.candidates.await_count == 1
    assert case.versions.get_permission_snapshots.await_count == (count + 99) // 100
    assert case.runtime.batch_check_actions.await_count == 3 * ((count + 99) // 100)
    assert all(len(call.args[1]) <= 100 for call in case.runtime.batch_check_actions.await_args_list)


async def test_ac02_empty_visible_set_does_no_business_or_permission_io(case):
    """AC-02: empty complete enumeration is authoritative."""
    case.runtime.list_visible_objects.return_value = case.runtime.list_visible_objects.return_value.model_copy(
        update={"object_ids": ()}
    )
    assert await case.service.get_my_managed_spaces() == []
    case.candidates.assert_not_awaited()
    case.members.assert_not_awaited()
    case.runtime.batch_check_actions.assert_not_awaited()


@pytest.mark.parametrize("scope", [DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL])
async def test_ac04_tenant_admin_keeps_personal_visible_boundary(case, scope):
    """AC-04: tenant administration never substitutes for visible enumeration."""
    case.actor_mock.return_value = replace(
        case.actor, tenant_admin_tenant_ids=frozenset({case.actor.current_tenant_id}), data_scope=scope
    )
    case.runtime.list_visible_objects.return_value = case.runtime.list_visible_objects.return_value.model_copy(
        update={"object_ids": ()}
    )
    assert await case.service.get_my_managed_spaces() == []
    case.runtime.list_visible_objects.assert_awaited_once()
    case.candidates.assert_not_awaited()
    case.runtime.batch_check_actions.assert_not_awaited()


@pytest.mark.parametrize("bad", ["status", "type", "id", "noncanonical", "capacity", "unavailable"])
async def test_ac02_incomplete_enumeration_never_falls_back_to_tenant_scan(case, bad):
    """AC-02/06: enum errors propagate with a terminal failure metric."""
    value = case.runtime.list_visible_objects.return_value
    if bad == "status":
        value = value.model_copy(update={"status": "incomplete"})
    elif bad == "type":
        value = value.model_copy(update={"resource_type": "knowledge_file"})
    elif bad == "id":
        value = value.model_copy(update={"object_ids": ("broken",)})
    elif bad == "noncanonical":
        value = value.model_copy(update={"object_ids": ("01",)})
    elif bad == "capacity":
        value = value.model_copy(update={"object_ids": tuple(str(i) for i in range(1, 5002))})
    else:
        case.runtime.list_visible_objects.side_effect = PermissionFGAUnavailableError()
    case.runtime.list_visible_objects.return_value = value
    with pytest.raises(PermissionFGAUnavailableError if bad == "unavailable" else PermissionEnumerationIncompleteError):
        await case.service.get_my_managed_spaces()
    case.candidates.assert_not_awaited()
    fields = case.metrics.call_args.kwargs
    assert fields["status"] == "error" and fields["failed_stage"] == "visible_ids"
    assert fields["total_elapsed_ms"] >= fields["visible_ids_elapsed_ms"] >= 0


@pytest.mark.parametrize("scope", [DATA_SCOPE_ALL, DATA_SCOPE_PERSONAL])
async def test_ac04_super_admin_only_bypasses_enumeration_with_full_scope(case, scope):
    """AC-04: restricted system tokens still enumerate and check their scope."""
    case.actor_mock.return_value = replace(case.actor, super_admin=True, data_scope=scope)
    case.candidates.return_value.append(_make_space(space_id=999))  # missing tenant, exclude defensively
    result = await case.service.get_my_managed_spaces()
    assert all(item.id != 999 for item in result)
    if scope == DATA_SCOPE_ALL:
        case.runtime.list_visible_objects.assert_not_awaited()
        case.runtime.batch_check_actions.assert_not_awaited()
        case.candidates.assert_awaited_once_with(None, "name")
    else:
        case.runtime.list_visible_objects.assert_awaited_once()
        assert case.runtime.batch_check_actions.await_count > 0


@pytest.mark.parametrize("stage", ["candidates", "members", "permission", "metadata"])
async def test_ac06_stage_errors_propagate_and_emit_terminal_metric(case, stage):
    """AC-06: failed phases do not turn into partial successful lists."""
    failing = {
        "candidates": case.candidates,
        "members": case.members,
        "permission": case.runtime.batch_check_actions,
        "metadata": case.counts,
    }[stage]
    failing.side_effect = RuntimeError("injected phase failure")
    with pytest.raises(RuntimeError, match="phase failure"):
        await case.service.get_my_managed_spaces()
    case.metrics.assert_called_once()
    assert case.metrics.call_args.kwargs["failed_stage"] == stage
    assert case.metrics.call_args.kwargs["error_type"] == "RuntimeError"


def test_ac05_route_serialization_with_real_service(case):
    """AC-05: actual /managed route returns the unchanged response envelope."""
    from bisheng.knowledge.api.endpoints.knowledge_space import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_knowledge_space_service] = lambda: case.service
    with TestClient(app) as client:
        response = client.get("/api/v1/knowledge/space/managed?order_by=name")
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert [item["id"] for item in body["data"]] == [7, 1, 2, 3]
    assert {"user_role", "subscription_status", "is_pinned", "file_num"} <= body["data"][0].keys()


async def test_ac03_repository_uses_bounded_in_lists_and_preserves_db_order():
    """AC-03/05: one SQL statement, <=500 IDs per IN, no application sorting."""
    captured = []

    async def execute(statement):
        captured.append(statement)
        return SimpleNamespace(all=lambda: [])

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(exec=execute)

    await KnowledgeSpaceListingRepository(session_factory=session).list_spaces(list(range(1, 1002)), "name")
    assert len(captured) == 1
    sql = str(captured[0].compile(dialect=mysql.dialect()))
    assert sql.count("knowledge.id IN") == 3
    assert "knowledge.type =" in sql
    assert "ORDER BY knowledge.name" in sql
    assert all(len(values) <= 500 for key, values in captured[0].compile().params.items() if key.startswith("id_"))


@pytest.mark.parametrize("ids", [None, [1, 2, 3]])
@pytest.mark.parametrize("keyword", [None, "matched", "absent"])
async def test_ac04_repository_keeps_global_and_visible_lists_in_current_tenant(ids, keyword):
    """AC-04: real SQL execution stays strict even with inherited tenant visibility."""
    register_tenant_filter_events()
    engine = create_engine("sqlite://")
    knowledge_module.Knowledge.__table__.create(engine)
    tenant_token = set_current_tenant_id(1)
    visibility_token = set_visible_tenant_ids(frozenset({1, 2}))
    try:
        with Session(engine) as db:
            rows = [_make_space(space_id=i) for i in range(1, 4)]
            for row in rows:
                row.tenant_id = 2 if row.id == 2 else 1
            rows[0].name = "matched name"
            rows[1].name = "matched foreign tenant"
            rows[2].description = "matched description"
            with bypass_tenant_filter():
                db.add_all(rows)
                db.commit()

            async def execute(statement):
                return db.exec(statement)

            @asynccontextmanager
            async def session():
                yield SimpleNamespace(exec=execute)

            result = await KnowledgeSpaceListingRepository(session_factory=session).list_spaces(ids, keyword=keyword)
            assert {row.id for row in result} == (set() if keyword == "absent" else {1, 3})
    finally:
        visible_tenant_ids.reset(visibility_token)
        current_tenant_id.reset(tenant_token)
        engine.dispose()


async def test_ac04_bulk_adapter_retains_status_tenant_kind_and_snapshot_guards(case):
    """AC-04: no extra row loads; stale, unpublished and foreign rows are omitted."""
    rows = [_make_space(space_id=i) for i in range(1, 6)]
    for row in rows:
        row.tenant_id = 1
        row.update_time = datetime(2026, 11, 2)
    rows[1].state = KnowledgeState.FAILED.value
    rows[2].tenant_id = 2
    rows[3].type = KnowledgeTypeEnum.NORMAL.value
    case.versions.get_permission_snapshots.side_effect = None
    case.versions.get_permission_snapshots.return_value = {
        (int(row.tenant_id), "knowledge_space", str(row.id)): PermissionResourceSnapshot(
            int(row.tenant_id), "knowledge_space", str(row.id), 7, "ctx7", "CUSTOM", None, None, "READY"
        )
        for row in rows[:4]
    }
    adapter = case.service.f048_permission_adapter
    targets = await adapter.resolve_permission_targets_from_rows(
        rows=rows, resource_type="knowledge_space", actor=case.actor
    )
    assert len(targets) == 1
    assert targets[0].resource_id == "1" and targets[0].resource_version == 7
    assert len(targets[0].context_version) == 64
    case.versions.get_permission_snapshots.assert_awaited_once()
