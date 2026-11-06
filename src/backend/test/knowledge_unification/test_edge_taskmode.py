"""F073 task mode consumes unified knowledge with its original S/D identity."""

from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from bisheng.common.cursor import encode_cursor
from bisheng.common.errcode.knowledge import (
    KnowledgeInvalidCursorError,
    KnowledgeNotExistError,
    KnowledgeTypeNotSupportedError,
)
from bisheng.common.errcode.knowledge_space import (
    KnowledgeSpaceInvalidCursorError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionFGAUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.services import knowledge_space_service
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.application.resource_authorization import ResourceAuthorizationRegistry
from bisheng.permission.domain.services.permission_action_service import F048PermissionService, PermissionActor
from bisheng.workstation.domain.services.chat_service import _to_linsight_submit
from test.knowledge_unification.test_kn_list import catalog as catalog
from test.knowledge_unification.test_kn_list import concrete_tenant as concrete_tenant
from test.knowledge_unification.test_kn_list import row
from test.open_api.task_mode_support import _req, delegated_principal, sa_principal


@pytest.fixture(params=["S", "D"])
async def admission(request, catalog, monkeypatch):
    principal = (sa_principal() if request.param == "S" else delegated_principal()).model_copy(
        update={"tenant_id": 101, "resource_owner_user_id": 99 if request.param == "S" else 55}
    )
    actor = PermissionActor(
        subject_type=principal.authorization_subject_type,
        subject_id=principal.authorization_subject_id,
        tenant_id=101,
    )
    operator = SimpleNamespace(user_id=principal.resource_owner_user_id, tenant_id=101)
    allowed, checks = set(), []

    async def batch_check(values, **_options):
        assert catalog.facts.open_sessions == 0
        checks.extend(values)
        return [(value["user"], value["object"]) in allowed for value in values]

    fga = SimpleNamespace(batch_check=AsyncMock(side_effect=batch_check))
    runtime = F048PermissionService(
        catalog=SimpleNamespace(
            ensure_runtime_ready=AsyncMock(), effective_actions=AsyncMock(return_value=("visible", "edit", "delete"))
        ),
        scope_fence=SimpleNamespace(ensure_readable=AsyncMock(return_value=False)),
        marker=SimpleNamespace(consistency_for=AsyncMock(return_value=None)),
        fga=fga,
        list_policy=SimpleNamespace(),
    )
    adapter = catalog.service.f048_permission_adapter
    adapter._loader._versions.get_permission_version = AsyncMock(return_value=(3, "ctx3"))
    registry = ResourceAuthorizationRegistry()
    for kind in ("knowledge_library", "knowledge_space"):
        registry.register(
            kind,
            SimpleNamespace(resolve_permission_target=partial(adapter.resolve_permission_target, resource_type=kind)),
        )
    monkeypatch.setattr(knowledge_module, "get_async_db_session", catalog.repository._session_factory)
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(knowledge_space_service, "KnowledgeSpaceListingRepository", lambda: catalog.repository)
    monkeypatch.setattr(KnowledgeSpaceService, "_resource_adapter", staticmethod(AsyncMock(return_value=adapter)))
    monkeypatch.setattr(
        "bisheng.common.dependencies.user_deps.UserPayload.assert_effective_web_menu_contains", AsyncMock()
    )
    principal_token = set_current_open_api_principal(principal)
    actor_token = set_current_permission_actor(actor)
    try:
        yield SimpleNamespace(
            catalog=catalog,
            principal=principal,
            actor=actor,
            operator=operator,
            allowed=allowed,
            checks=checks,
            fga=fga,
        )
    finally:
        reset_current_permission_actor(actor_token)
        reset_current_open_api_principal(principal_token)


async def test_library_slot_groups_original_and_migrated_ids_once_using_visible(admission, monkeypatch):
    await admission.catalog.seed([row(1, kind=0), row(2)])
    admission.allowed.update(
        {(admission.actor.fga_subject, "knowledge_library:1"), (admission.actor.fga_subject, "knowledge_space:2")}
    )
    original = business.batch_check_business_actions
    calls = []

    async def batch(login_user, **options):
        assert login_user is admission.operator
        calls.append(options)
        return await original(login_user, **options)

    monkeypatch.setattr(business, "batch_check_business_actions", batch)
    await OpenTaskModeService.check_knowledge_libraries(admission.operator, [1, 2, 2, 1])
    assert [(call["resource_type"], tuple(call["resource_ids"]), call["actions"]) for call in calls] == [
        ("knowledge_library", (1,), ("visible",)),
        ("knowledge_space", (2,), ("visible",)),
    ]
    assert len(admission.catalog.facts.queries) == 3  # one candidates query plus two distinct verified-target reads
    assert {check["object"] for check in admission.checks} == {"knowledge_library:1", "knowledge_space:2"}
    assert all(
        check["user"] == admission.actor.fga_subject and check["relation"] == "visible" for check in admission.checks
    )


@pytest.mark.parametrize("kind", [1, 2, 99])
async def test_library_slot_keeps_qa_retired_and_unknown_type_rejection(admission, kind):
    await admission.catalog.seed([row(1, kind=kind)])
    with pytest.raises(KnowledgeTypeNotSupportedError):
        await OpenTaskModeService.check_knowledge_libraries(admission.operator, [1])
    admission.fga.batch_check.assert_not_awaited()


@pytest.mark.parametrize("foreign", [False, True])
async def test_missing_and_other_tenant_ids_are_not_targets(admission, foreign):
    if foreign:
        await admission.catalog.seed([row(1, kind=0, tenant=202)])
    with pytest.raises(KnowledgeNotExistError):
        await OpenTaskModeService.check_knowledge_libraries(admission.operator, [1])
    admission.fga.batch_check.assert_not_awaited()


async def test_library_candidates_remain_strict_under_ambient_bypass(admission):
    await admission.catalog.seed([row(1, kind=0, tenant=202)])
    with bypass_tenant_filter(), pytest.raises(KnowledgeNotExistError):
        await OpenTaskModeService.check_knowledge_libraries(admission.operator, [1])
    admission.fga.batch_check.assert_not_awaited()


@pytest.mark.parametrize("kind", [0, 3])
async def test_owner_grant_does_not_replace_original_actor(admission, kind):
    await admission.catalog.seed([row(1, kind=kind)])
    namespace = "knowledge_library" if kind == 0 else "knowledge_space"
    admission.allowed.add(("user:99", f"{namespace}:1"))
    with pytest.raises(PermissionDeniedError):
        await OpenTaskModeService.check_knowledge_libraries(admission.operator, [1])
    assert admission.checks == [
        {"user": admission.actor.fga_subject, "relation": "visible", "object": f"{namespace}:1"}
    ]


async def test_narrowed_delegated_actor_cannot_gain_owner_or_admin_shortcut(admission, monkeypatch):
    await admission.catalog.seed([row(1, kind=0)])
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.get_data_scope_resolver", lambda: None
    )
    actor = PermissionActor(user_id=55, tenant_id=101, super_admin=True, data_scope="PERSONAL")
    token = set_current_permission_actor(actor)
    try:
        with pytest.raises(PermissionDeniedError):
            await OpenTaskModeService.check_knowledge_libraries(admission.operator, [1])
    finally:
        reset_current_permission_actor(token)
    admission.fga.batch_check.assert_not_awaited()


@pytest.mark.parametrize("kind", [0, 1, 2])
async def test_actual_space_slot_still_rejects_non_space_rows(admission, kind):
    await admission.catalog.seed([row(1, kind=kind)])
    with pytest.raises(SpaceNotFoundError):
        await OpenTaskModeService.check_knowledge_spaces(admission.operator, [1])
    admission.fga.batch_check.assert_not_awaited()


async def test_actual_space_slot_preserves_its_denial_error(admission):
    await admission.catalog.seed([row(1)])
    with pytest.raises(SpacePermissionDeniedError):
        await OpenTaskModeService.check_knowledge_spaces(admission.operator, [1])


@pytest.mark.parametrize("alias", ["library", "space"])
async def test_both_list_aliases_consume_real_name_only_seek_pages_and_same_actor(admission, alias):
    description_only = row(2, name="other")
    description_only.description = "policy%_"
    await admission.catalog.seed(
        [
            row(1, name="POLICY%_"),
            description_only,
            row(3, name="prefix Policy%_ suffix"),
            row(4, kind=0, name="Policy%_"),
            row(5, tenant=202, name="Policy%_"),
            row(6, name="owner Policy%_"),
        ]
    )
    admission.allowed.update(
        {
            (admission.actor.fga_subject, "knowledge_space:1"),
            (admission.actor.fga_subject, "knowledge_space:3"),
            ("user:99", "knowledge_space:6"),
        }
    )
    options = {"knowledge_type": alias, "name": "  policy%_  ", "page_size": 1}
    request = Request({"type": "http"})
    first = await OpenTaskModeService.list_knowledge(
        request, admission.principal, admission.operator, cursor=None, **options
    )
    assert [item["id"] for item in first.data] == [3] and first.has_more
    assert set(first.data[0]) == {"id", "name", "description", "update_time"}
    last = await OpenTaskModeService.list_knowledge(
        request, admission.principal, admission.operator, cursor=first.next_cursor, **options
    )
    assert [item["id"] for item in last.data] == [1] and not last.has_more
    await OpenTaskModeService.check_knowledge_libraries(admission.operator, [3, 1])
    assert all(
        check["user"] == admission.actor.fga_subject and check["relation"] == "visible" for check in admission.checks
    )


@pytest.mark.parametrize(
    "alias,error", [("library", KnowledgeInvalidCursorError), ("space", KnowledgeSpaceInvalidCursorError)]
)
async def test_old_offset_and_malformed_cursors_preserve_alias_error(admission, alias, error):
    for cursor in ["broken", encode_cursor((2,), context="open_task|knowledge_space")]:
        with pytest.raises(error):
            await OpenTaskModeService.list_knowledge(
                Request({"type": "http"}),
                admission.principal,
                admission.operator,
                knowledge_type=alias,
                name=None,
                cursor=cursor,
                page_size=20,
            )
    assert not admission.catalog.facts.queries
    admission.fga.batch_check.assert_not_awaited()


@pytest.mark.parametrize("alias", ["library", "space"])
async def test_list_transport_failure_propagates_without_empty_success(admission, alias):
    await admission.catalog.seed([row(1)])
    admission.fga.batch_check.side_effect = RuntimeError("FGA unavailable")
    with pytest.raises(PermissionFGAUnavailableError):
        await OpenTaskModeService.list_knowledge(
            Request({"type": "http"}),
            admission.principal,
            admission.operator,
            knowledge_type=alias,
            name=None,
            cursor=None,
            page_size=20,
        )


async def test_library_alias_keeps_empty_sparse_page_and_native_sql_budget(admission):
    await admission.catalog.seed([row(ident) for ident in range(1, 1202)])
    admission.allowed.add((admission.actor.fga_subject, "knowledge_space:1"))
    options = {"knowledge_type": "library", "name": None, "page_size": 100}
    first = await OpenTaskModeService.list_knowledge(
        Request({"type": "http"}), admission.principal, admission.operator, cursor=None, **options
    )
    assert first.data == [] and first.has_more and first.next_cursor
    assert len(admission.checks) == 1000 and len(admission.catalog.facts.queries) == 11
    last = await OpenTaskModeService.list_knowledge(
        Request({"type": "http"}), admission.principal, admission.operator, cursor=first.next_cursor, **options
    )
    assert [item["id"] for item in last.data] == [1] and not last.has_more
    assert len(admission.checks) == 1201


async def test_existing_workstation_and_worker_keep_migrated_original_ids_without_new_user_checks(admission):
    await admission.catalog.seed([row(1), row(2), row(3)])
    mapped = _to_linsight_submit(_req(knowledge_ids=[1], knowledge_space_ids=[2]).to_internal())
    assert mapped.organization_knowledge_ids == [1] and mapped.knowledge_space_ids == [2] and mapped.model == "7"
    task = LinsightWorkflowTask()
    session = SimpleNamespace(
        organization_knowledge_ids=mapped.organization_knowledge_ids, knowledge_space_ids=mapped.knowledge_space_ids
    )
    token = set_current_permission_actor(None)
    try:
        assert await task._resolve_allowed_knowledge_ids(session) == {"1", "2"}
    finally:
        reset_current_permission_actor(token)
    admission.fga.batch_check.assert_not_awaited()
