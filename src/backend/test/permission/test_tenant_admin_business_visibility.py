"""Business access admits tenant administrators; personal visibility stays exact."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.permission.test_f048_permission_service import _service


@pytest.fixture
def access(monkeypatch):
    service, _, _, _, fga, *_ = _service()
    actor = PermissionActor(user_id=7, current_tenant_id=101, tenant_admin_tenant_ids=frozenset({101}))
    registry = SimpleNamespace(resolve=AsyncMock())
    monkeypatch.setattr(business, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=service))
    monkeypatch.setattr(business, "_require_creation_ready", AsyncMock())
    return SimpleNamespace(service=service, actor=actor, registry=registry, fga=fga)


def target(resource_type, tenant=101):
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=tenant, resource_type=resource_type, resource_id="9", resource_version=1, context_version="v1"
    )


@pytest.mark.parametrize(
    "resource_type", ["knowledge_space", "folder", "knowledge_file", "workflow", "assistant", "app"]
)
async def test_tenant_admin_can_open_same_tenant_business_without_personal_visible_tuple(access, resource_type):
    access.registry.resolve.return_value = target(resource_type)
    with tenant_execution_scope(101):
        assert await business.check_business_action(
            UserPayload(user_id=7, tenant_id=101, user_role=[]),
            resource_type=resource_type,
            resource_id="9",
            action="visible",
        )
        result = await business.batch_check_business_actions(
            object(), resource_type=resource_type, resource_ids=["9"], actions=["visible"]
        )
    assert result == {"9": frozenset({"visible"})}
    assert access.registry.resolve.await_count == 2
    assert access.fga.checks == [] and access.fga.batches == []
    assert not await access.service.check_visible(access.actor, target(resource_type))


@pytest.mark.parametrize("tenant", [1, 202])
async def test_tenant_admin_cannot_open_other_tenant_business(access, tenant):
    access.registry.resolve.return_value = target("workflow", tenant)
    with tenant_execution_scope(101):
        assert not await business.check_business_action(
            object(), resource_type="workflow", resource_id="9", action="visible"
        )
        assert await business.batch_check_business_actions(
            object(), resource_type="workflow", resource_ids=["9"], actions=["visible"]
        ) == {"9": frozenset()}


async def test_narrowed_admin_does_not_take_business_visibility_shortcut(access):
    access.registry.resolve.return_value = target("workflow")
    actor = PermissionActor(
        user_id=7, current_tenant_id=101, tenant_admin_tenant_ids=frozenset({101}), data_scope=DATA_SCOPE_PERSONAL
    )
    check = AsyncMock(side_effect=PersonalTokenDataScopeError())
    access.service.check_action = check
    with tenant_execution_scope(101), pytest.raises(PersonalTokenDataScopeError):
        await business.check_business_action(
            object(), resource_type="workflow", resource_id="9", action="visible", actor=actor
        )
    check.assert_awaited_once()


async def test_ordinary_user_still_requires_personal_resource_visibility(access):
    access.registry.resolve.return_value = target("knowledge_space")
    actor = PermissionActor(user_id=8, current_tenant_id=101)
    with tenant_execution_scope(101):
        assert not await business.check_business_action(
            object(), resource_type="knowledge_space", resource_id="9", action="visible", actor=actor
        )
    assert access.fga.checks[-1][1] == "visible"


async def test_admin_never_skips_business_target_validation(access):
    from bisheng.common.errcode.permission import PermissionInvalidResourceError

    access.registry.resolve.side_effect = PermissionInvalidResourceError()
    with tenant_execution_scope(101), pytest.raises(PermissionInvalidResourceError):
        await business.check_business_action(
            object(), resource_type="knowledge_space", resource_id="9", action="visible"
        )


async def test_space_directory_read_admits_non_owner_tenant_admin(access, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    access.registry.resolve.return_value = target("knowledge_space")
    row = Knowledge(id=9, tenant_id=101, type=3, user_id=99, name="Someone else's space")
    monkeypatch.setattr(KnowledgeDao, "aquery_by_id", AsyncMock(return_value=row))
    service = KnowledgeSpaceService(None, UserPayload(user_id=7, tenant_id=101, user_role=[]))
    service._permission_actor_cache = access.actor
    with tenant_execution_scope(101):
        space, parent = await service._require_container_read_permission(9, None)
    assert space is row and parent is None


async def test_workflow_detail_admits_non_owner_tenant_admin(access, monkeypatch):
    from bisheng.api.services.flow import FlowService
    from bisheng.database.models.flow import Flow, FlowDao

    access.registry.resolve.return_value = target("workflow")
    row = Flow(id="9", tenant_id=101, flow_type=10, user_id=99, name="Someone else's workflow")
    monkeypatch.setattr(FlowDao, "aget_flow_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(FlowService, "get_logo_share_link_async", AsyncMock(return_value=None))
    with tenant_execution_scope(101):
        result = await FlowService.get_one_flow(UserPayload(user_id=7, tenant_id=101, user_role=[]), "9")
    assert result.data["id"] == "9"
