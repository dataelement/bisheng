"""COFCO /info access hints, visibility-first state, and stage diagnostics.

DAO and authorization I/O are replaced at their boundaries. The real service,
entry gate, actor reuse, joined-state logic and response serialization run.
These are offline regressions, not deployed OpenFGA/DM8 performance evidence.
"""

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.common.errcode.knowledge_space import SpaceNotFoundError, SpacePermissionDeniedError
from bisheng.common.models.space_channel_member import MembershipStatusEnum, UserRoleEnum
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeState
from bisheng.knowledge.domain.schemas.knowledge_space_schema import SpaceSubscriptionStatusEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge.test_knowledge_space_service import _make_login_user, _make_member, _make_space

MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"
STAGES = (
    "prepare",
    "auth",
    "member_count",
    "file_count",
    "creator",
    "subscription_role",
    "download_catalog",
    "department",
    "auto_tag",
    "rebuild",
)


@pytest.fixture
def info_case():
    login_user = _make_login_user()
    space = _make_space(space_id=303, user_id=9, is_released=True, auth_type=AuthTypeEnum.APPROVAL)
    actor = PermissionActor(user_id=login_user.user_id, current_tenant_id=login_user.tenant_id)
    member = _make_member(user_id=login_user.user_id, space_id=space.id, user_role=UserRoleEnum.MEMBER)
    service = KnowledgeSpaceService(MagicMock(), login_user)

    with ExitStack() as stack:

        def mock_async(path, **kwargs):
            return stack.enter_context(patch(f"{MODULE}.{path}", new_callable=AsyncMock, **kwargs))

        mocks = SimpleNamespace(
            space=space,
            member=member,
            service=service,
            actor=actor,
            query_space=mock_async("KnowledgeDao.aquery_by_id", return_value=space),
            check=mock_async("check_business_action", return_value=True),
            resolve_actor=mock_async("resolve_permission_actor", return_value=actor),
            grant_visible=mock_async("batch_check_business_visible", return_value={"303": False}),
            member_count=mock_async("SpaceChannelMemberDao.async_count_space_members", return_value=3),
            file_count=mock_async("KnowledgeFileDao.async_count_success_files_batch", return_value={303: 10001}),
            creator=mock_async("UserDao.aget_user", return_value=SimpleNamespace(user_name="creator")),
            find_member=mock_async("SpaceChannelMemberDao.async_find_member", return_value=member),
            runtime=mock_async("get_f048_runtime"),
            actions=stack.enter_context(patch.object(service, "_get_effective_actions", new_callable=AsyncMock)),
            department=stack.enter_context(
                patch.object(service, "_decorate_department_metadata", new_callable=AsyncMock)
            ),
            auto_tag=stack.enter_context(patch.object(service, "_decorate_auto_tag_for_info", new_callable=AsyncMock)),
            metric=stack.enter_context(patch(f"{MODULE}.emit_metric")),
            rebuild=stack.enter_context(patch("bisheng.worker.rebuild_knowledge_celery.delay")),
        )
        mocks.runtime.return_value = SimpleNamespace(effective_actions=AsyncMock(return_value={"download"}))
        yield mocks


async def test_ac01_member_reuses_entry_visibility_and_never_expands_actions(info_case):
    result = await info_case.service.get_space_info(303)

    assert result.actions == ["visible"]
    assert result.user_role == UserRoleEnum.MEMBER
    assert result.subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
    assert result.follower_num == 3
    assert result.file_num == 10001
    info_case.check.assert_awaited_once_with(
        info_case.service.login_user,
        resource_type="knowledge_space",
        resource_id=303,
        action="visible",
        actor=info_case.actor,
    )
    info_case.actions.assert_not_awaited()
    info_case.grant_visible.assert_not_awaited()
    info_case.resolve_actor.assert_awaited_once()
    info_case.query_space.assert_awaited_once_with(303)


@pytest.mark.parametrize("manage_allowed", [False, True])
async def test_ac01_ac04_department_grant_without_membership_preserves_role_check(info_case, manage_allowed):
    info_case.find_member.return_value = None
    info_case.check.side_effect = [True, manage_allowed]

    result = await info_case.service.get_space_info(303)

    assert result.actions == ["visible"]
    assert result.is_followed is True
    assert result.user_role == (UserRoleEnum.ADMIN if manage_allowed else UserRoleEnum.MEMBER)
    assert [entry.kwargs["action"] for entry in info_case.check.await_args_list] == ["visible", "manage_permission"]
    info_case.actions.assert_not_awaited()
    info_case.resolve_actor.assert_awaited_once()


@pytest.mark.parametrize("status", [MembershipStatusEnum.PENDING, MembershipStatusEnum.REJECTED])
async def test_ac02_visible_overrides_old_application_in_info_and_square(info_case, status):
    info_case.member.status = status
    info_case.member.update_time = datetime.now()
    info_case.grant_visible.return_value = {"303": True}

    result = await info_case.service.get_space_info(303)
    with (
        patch(
            f"{MODULE}.KnowledgeDao.async_get_public_spaces_paginated",
            new_callable=AsyncMock,
            return_value=[(info_case.space, status, info_case.member.update_time, 3)],
        ),
        patch(f"{MODULE}.KnowledgeDao.async_count_public_spaces", new_callable=AsyncMock, return_value=1),
        patch(f"{MODULE}.UserDao.aget_user_by_ids", new_callable=AsyncMock, return_value=[]),
    ):
        square = await info_case.service.get_knowledge_square()

    for item in (result, square["data"][0]):
        assert item.subscription_status == SpaceSubscriptionStatusEnum.SUBSCRIBED
        assert item.is_followed is True
        assert item.is_pending is False
    # Presentation does not change the approval/member record.
    assert info_case.member.status == status


@pytest.mark.parametrize("auth_type", [AuthTypeEnum.PUBLIC, AuthTypeEnum.APPROVAL])
@pytest.mark.parametrize("status", [None, MembershipStatusEnum.PENDING, MembershipStatusEnum.REJECTED])
async def test_ac03_preview_retains_application_state_without_catalog_lookup(info_case, auth_type, status):
    info_case.space.auth_type = auth_type
    info_case.check.return_value = False
    if status is None:
        info_case.find_member.return_value = None
        expected = SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
    else:
        info_case.member.status = status
        info_case.member.update_time = datetime.now()
        expected = SpaceSubscriptionStatusEnum(status.value.lower())

    result = await info_case.service.get_space_info(303)

    assert result.actions == []
    assert result.subscription_status == expected
    assert result.is_followed is False
    assert result.is_pending == (expected == SpaceSubscriptionStatusEnum.PENDING)
    info_case.actions.assert_not_awaited()
    info_case.runtime.assert_not_awaited()
    assert [entry.kwargs["action"] for entry in info_case.check.await_args_list] == ["visible"]


@pytest.mark.parametrize("auth_type,is_released", [(AuthTypeEnum.PRIVATE, True), (AuthTypeEnum.PUBLIC, False)])
async def test_ac03_private_or_unreleased_space_is_denied_before_enrichment(info_case, auth_type, is_released):
    info_case.space.auth_type = auth_type
    info_case.space.is_released = is_released
    info_case.check.return_value = False

    with pytest.raises(SpacePermissionDeniedError):
        await info_case.service.get_space_info(303)

    info_case.member_count.assert_not_awaited()
    info_case.runtime.assert_not_awaited()
    info_case.actions.assert_not_awaited()
    fields = info_case.metric.call_args.kwargs
    assert fields["failed_stage"] == "auth"
    assert fields["error_type"] == "SpacePermissionDeniedError"


async def test_ac04_creator_keeps_role_and_still_checks_entry_access(info_case):
    info_case.space.user_id = info_case.service.login_user.user_id

    result = await info_case.service.get_space_info(303)

    assert result.user_role == UserRoleEnum.CREATOR
    assert result.actions == ["visible"]
    assert result.is_followed is True
    info_case.find_member.assert_not_awaited()
    info_case.creator.assert_not_awaited()
    assert [entry.kwargs["action"] for entry in info_case.check.await_args_list] == ["visible"]


async def test_ac04_super_admin_can_enter_without_being_marked_joined(info_case):
    actor = replace(info_case.actor, super_admin=True)
    info_case.resolve_actor.return_value = actor
    info_case.find_member.return_value = None

    result = await info_case.service.get_space_info(303)

    assert result.actions == ["visible"]
    assert result.subscription_status == SpaceSubscriptionStatusEnum.NOT_SUBSCRIBED
    assert result.is_followed is False
    info_case.grant_visible.assert_awaited_once_with(
        info_case.service.login_user,
        resource_type="knowledge_space",
        resource_ids=[303],
        actor=actor,
    )
    info_case.actions.assert_not_awaited()


@pytest.mark.parametrize("download_enabled", [False, True])
async def test_ac05_download_catalog_switch_is_preserved(info_case, download_enabled):
    catalog = info_case.runtime.return_value.effective_actions
    catalog.return_value = {"download"} if download_enabled else set()

    result = await info_case.service.get_space_info(303)

    assert result.download_action_enabled is download_enabled
    catalog.assert_awaited_once_with("knowledge_file")


@pytest.mark.parametrize("failing_stage", STAGES)
async def test_ac06_stage_metrics_include_failed_time_and_propagate_error(info_case, failing_stage):
    clock = [0.0]

    def fail(*args, **kwargs):
        clock[0] += 0.25
        raise RuntimeError("offline injected failure")

    fail_at = {
        "prepare": None,
        "auth": info_case.query_space,
        "member_count": info_case.member_count,
        "file_count": info_case.file_count,
        "creator": info_case.creator,
        "subscription_role": info_case.find_member,
        "download_catalog": info_case.runtime,
        "department": info_case.department,
        "auto_tag": info_case.auto_tag,
        "rebuild": info_case.rebuild,
    }
    if failing_stage != "prepare":
        fail_at[failing_stage].side_effect = fail
    if failing_stage == "rebuild":
        info_case.space.state = KnowledgeState.REBUILDING.value
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}.perf_counter", side_effect=lambda: clock[0]))
        if failing_stage == "prepare":
            stack.enter_context(patch(f"{MODULE}.KnowledgeSpaceInfoResp", side_effect=fail))
        with pytest.raises(RuntimeError, match="offline injected failure"):
            await info_case.service.get_space_info(303)

    info_case.metric.assert_called_once()
    assert info_case.metric.call_args.args == ("knowledge_space_info",)
    fields = info_case.metric.call_args.kwargs
    assert fields["status"] == "error"
    assert fields["failed_stage"] == failing_stage
    assert fields["error_type"] == "RuntimeError"
    assert fields[f"{failing_stage}_elapsed_ms"] == 250.0
    assert fields["total_elapsed_ms"] == 250.0


async def test_ac06_success_metrics_are_bounded_and_counts_are_not_requeried(info_case):
    await info_case.service.get_space_info(303)

    info_case.member_count.assert_awaited_once_with(303)
    info_case.file_count.assert_awaited_once_with([303])
    info_case.metric.assert_called_once()
    fields = info_case.metric.call_args.kwargs
    assert fields["status"] == "success"
    assert fields["failed_stage"] is None
    assert fields["error_type"] is None
    elapsed = [fields[f"{stage}_elapsed_ms"] for stage in STAGES]
    assert all(value >= 0 for value in elapsed)
    assert sum(elapsed) <= fields["total_elapsed_ms"]
    assert fields["actor_resolve_count"] == 1
    assert fields["space_id"] == 303
    assert fields["has_content_permission"] is True
    assert not {"user_name", "sql", "password", "token"} & fields.keys()


@pytest.fixture
def info_client(info_case):
    from bisheng.knowledge.api.endpoints.knowledge_space import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # Exercise the real service with isolated I/O; live authentication is covered
    # by the opt-in deployment suite, not this dependency override.
    app.dependency_overrides[get_knowledge_space_service] = lambda: info_case.service
    with TestClient(app) as client:
        yield client


def test_ac01_api_serializes_visible_hint_without_full_action_lookup(info_client, info_case):
    response = info_client.get("/api/v1/knowledge/space/303/info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_code"] == 200
    assert "status_message" in payload
    assert payload["data"]["actions"] == ["visible"]
    assert payload["data"]["subscription_status"] == "subscribed"
    assert payload["data"]["download_action_enabled"] is True
    info_case.actions.assert_not_awaited()


def test_ac03_api_serializes_preview_without_visible_hint(info_client, info_case):
    info_case.check.return_value = False
    info_case.find_member.return_value = None

    payload = info_client.get("/api/v1/knowledge/space/303/info").json()

    assert payload["status_code"] == 200
    assert payload["data"]["actions"] == []
    assert payload["data"]["subscription_status"] == "not_subscribed"


@pytest.mark.parametrize("missing", [False, True])
def test_ac03_api_propagates_exact_not_found_and_permission_errors(info_client, info_case, missing):
    if missing:
        info_case.query_space.return_value = None
    else:
        info_case.space.auth_type = AuthTypeEnum.PRIVATE
        info_case.check.return_value = False

    expected = SpaceNotFoundError if missing else SpacePermissionDeniedError
    # This minimal app does not install the production exception middleware.
    with pytest.raises(expected) as error:
        info_client.get("/api/v1/knowledge/space/303/info")
    assert error.value.code == expected.Code
    info_case.file_count.assert_not_awaited()


async def test_ac03_authorization_failure_never_falls_back_to_public_preview(info_case):
    info_case.check.side_effect = RuntimeError("authorization unavailable")

    with pytest.raises(RuntimeError, match="authorization unavailable"):
        await info_case.service.get_space_info(303)

    info_case.member_count.assert_not_awaited()
    assert info_case.metric.call_args.kwargs["failed_stage"] == "auth"


@pytest.mark.parametrize("current_tenant_id,should_rebuild", [(1, True), (2, False)])
async def test_ac05_rebuild_dispatch_keeps_tenant_guard(info_case, current_tenant_id, should_rebuild):
    info_case.space.state = KnowledgeState.REBUILDING.value
    info_case.space.tenant_id = 1
    with patch(f"{MODULE}.get_current_tenant_id", return_value=current_tenant_id):
        await info_case.service.get_space_info(303)

    if should_rebuild:
        info_case.rebuild.assert_called_once_with(
            303,
            new_model_id=info_case.space.model,
            invoke_user_id=info_case.service.login_user.user_id,
        )
    else:
        info_case.rebuild.assert_not_called()
