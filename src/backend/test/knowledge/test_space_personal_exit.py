from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceGrantedNotJoinedError,
    SpaceNotFoundError,
    SpacePermissionDeniedError,
)
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
def exit_context():
    actor = PermissionActor(user_id=764, current_tenant_id=1)
    target = SimpleNamespace(resource_id="4187", resource_version=4)
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=764, tenant_id=1)
    service._permission_actor = AsyncMock(return_value=actor)
    service.resolve_permission_target = AsyncMock(return_value=target)
    service._require_action = AsyncMock()
    space = SimpleNamespace(id=4187, tenant_id=1, type=3, user_id=3)
    runtime = SimpleNamespace(
        personal_space_exit_status=AsyncMock(return_value=SimpleNamespace(can_exit=True, reason=None)),
        exit_personal_space=AsyncMock(return_value=SimpleNamespace()),
    )
    directory = SimpleNamespace(actor_projected_subjects=AsyncMock(return_value=frozenset({"user:764"})))
    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            AsyncMock(return_value=space),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member",
            AsyncMock(return_value=None),
        ) as member,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.delete_space_member",
            AsyncMock(return_value=1),
        ) as delete,
        patch("bisheng.permission.application.access.get_f048_runtime", AsyncMock(return_value=runtime)),
        patch("bisheng.permission.application.access.get_grant_subject_directory", AsyncMock(return_value=directory)),
    ):
        yield SimpleNamespace(
            service=service,
            actor=actor,
            target=target,
            space=space,
            runtime=runtime,
            member=member,
            delete=delete,
            directory=directory,
        )


async def test_personal_grant_without_legacy_membership_can_exit(exit_context):
    c = exit_context
    assert await c.service.unsubscribe_space(4187) is True
    kwargs = c.runtime.exit_personal_space.await_args.kwargs
    assert kwargs["actor"] == c.actor
    assert kwargs["target"] is c.target
    assert kwargs["actor_projected_subjects"] == frozenset({"user:764"})


async def test_status_uses_the_same_permission_policy_as_execution(exit_context):
    c = exit_context
    result = await c.service.get_space_exit_status(4187)
    assert result.can_exit is True
    assert result.reason is None
    c.runtime.personal_space_exit_status.assert_awaited_once()


@pytest.mark.parametrize("member_exists", [False, True])
async def test_organization_grant_prevents_exit_even_with_personal_membership(exit_context, member_exists):
    c = exit_context
    if member_exists:
        c.member.return_value = SimpleNamespace(user_role=UserRoleEnum.MEMBER)
    c.runtime.personal_space_exit_status.return_value = SimpleNamespace(can_exit=False, reason="organization_grant")
    c.runtime.exit_personal_space.side_effect = PermissionDeniedError()
    with pytest.raises(SpaceGrantedNotJoinedError):
        await c.service.unsubscribe_space(4187)
    c.delete.assert_not_awaited()


async def test_creator_is_not_offered_exit_and_cannot_exit(exit_context):
    c = exit_context
    c.space.user_id = 764
    status = await c.service.get_space_exit_status(4187)
    assert status.can_exit is False
    assert status.reason == "creator"
    with pytest.raises(SpacePermissionDeniedError):
        await c.service.unsubscribe_space(4187)
    c.runtime.exit_personal_space.assert_not_awaited()


async def test_execution_rechecks_organization_permissions_after_status_read(exit_context):
    c = exit_context
    assert (await c.service.get_space_exit_status(4187)).can_exit is True
    c.directory.actor_projected_subjects.return_value = frozenset({"user:764", "department:9#member"})
    c.runtime.exit_personal_space.side_effect = PermissionDeniedError()
    with pytest.raises(SpaceGrantedNotJoinedError):
        await c.service.unsubscribe_space(4187)
    assert "department:9#member" in c.runtime.exit_personal_space.await_args.kwargs["actor_projected_subjects"]
    c.delete.assert_not_awaited()


async def test_failed_projection_preserves_membership_for_retry(exit_context):
    c = exit_context
    c.member.return_value = SimpleNamespace(user_role=UserRoleEnum.MEMBER)
    c.runtime.exit_personal_space.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await c.service.unsubscribe_space(4187)
    c.delete.assert_not_awaited()


async def test_successful_exit_cleans_legacy_membership_and_retry_is_idempotent(exit_context):
    c = exit_context
    c.member.return_value = SimpleNamespace(user_role=UserRoleEnum.MEMBER)
    assert await c.service.unsubscribe_space(4187) is True

    c.delete.assert_awaited_once_with(4187, 764)
    c.member.return_value = None
    c.runtime.personal_space_exit_status.return_value = SimpleNamespace(can_exit=False, reason="no_personal_grant")
    c.runtime.exit_personal_space.return_value = None
    assert await c.service.unsubscribe_space(4187) is True


@pytest.mark.parametrize("kind,tenant", [(0, 1), (3, 2)])
async def test_wrong_resource_kind_or_tenant_cannot_read_or_exit(exit_context, kind, tenant):
    c = exit_context
    c.space.type, c.space.tenant_id = kind, tenant
    for operation in (c.service.get_space_exit_status, c.service.unsubscribe_space):
        with pytest.raises(SpaceNotFoundError):
            await operation(4187)
    c.runtime.exit_personal_space.assert_not_awaited()


async def test_permission_revoked_before_status_read_does_not_expose_eligibility(exit_context):
    c = exit_context
    c.service._require_action.side_effect = PermissionDeniedError()
    with pytest.raises(PermissionDeniedError):
        await c.service.get_space_exit_status(4187)
    c.runtime.personal_space_exit_status.assert_not_awaited()


async def test_legacy_creator_membership_cannot_exit(exit_context):
    c = exit_context
    c.member.return_value = SimpleNamespace(user_role=UserRoleEnum.CREATOR)
    assert (await c.service.get_space_exit_status(4187)).reason == "creator"
    with pytest.raises(SpacePermissionDeniedError):
        await c.service.unsubscribe_space(4187)


async def test_http_status_and_unsubscribe_use_the_verified_service(exit_context):
    import httpx
    from fastapi import FastAPI

    from bisheng.knowledge.api.dependencies import get_knowledge_space_service
    from bisheng.knowledge.api.endpoints.knowledge_space import get_space_exit_status, unsubscribe_space

    app = FastAPI()
    app.add_api_route("/api/v1/knowledge/space/{space_id}/exit-status", get_space_exit_status, methods=["GET"])
    app.add_api_route("/api/v1/knowledge/space/{space_id}/unsubscribe", unsubscribe_space, methods=["POST"])
    app.dependency_overrides[get_knowledge_space_service] = lambda: exit_context.service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/v1/knowledge/space/4187/exit-status")
        assert status.status_code == 200
        assert status.json()["data"] == {"can_exit": True, "reason": None}
        result = await client.post("/api/v1/knowledge/space/4187/unsubscribe")
        assert result.json()["data"] is True
    exit_context.runtime.exit_personal_space.assert_awaited_once()
