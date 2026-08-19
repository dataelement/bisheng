from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError, PermissionTupleWriteError
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizationItemResult,
    AuthorizationResult,
    AuthorizeGrantItem,
    AuthorizeRequest,
)


class _CreateRequest:
    def __init__(self, *, initial_permissions=None, auth_type="public"):
        self.name = "Alpha"
        self.description = "A knowledge space"
        self.icon = "alpha.svg"
        self.auth_type = auth_type
        self.is_released = False
        self.auto_tag_enabled = False
        self.auto_tag_library_id = None
        self.auto_tag_custom_tags = None
        self.initial_permissions = initial_permissions


class _CreatedSpace:
    def __init__(self, space_id: int = 101):
        self.id = space_id

    def model_dump(self, *args, **kwargs):
        return {
            "id": self.id,
            "name": "Alpha",
            "description": "A knowledge space",
            "auth_type": "public",
        }


def _build_service(created_space: _CreatedSpace | None = None):
    from bisheng.knowledge.domain.services.knowledge_space_creation_application_service import (
        KnowledgeSpaceCreationApplicationService,
    )

    knowledge_space_service = MagicMock()
    knowledge_space_service.create_knowledge_space = AsyncMock(return_value=created_space or _CreatedSpace())
    grant_subject_query_service = MagicMock()
    grant_subject_query_service.validate_creation_grants = AsyncMock()
    grant_subject_query_service.validate_creation_grant_request = AsyncMock(return_value=3)
    grant_subject_query_service.validate_creation_grant_subjects = AsyncMock()
    resource_authorization_service = MagicMock()
    resource_authorization_service.authorize = AsyncMock()
    resource_authorization_service.ensure_invite_scenario_available_for_grants = AsyncMock()

    @asynccontextmanager
    async def scenario_guard(**_kwargs):
        await resource_authorization_service.ensure_invite_scenario_available_for_grants(**_kwargs)
        yield

    resource_authorization_service.invite_scenario_guard_for_grants = MagicMock(
        side_effect=scenario_guard,
    )
    service = KnowledgeSpaceCreationApplicationService(
        knowledge_space_service=knowledge_space_service,
        grant_subject_query_service=grant_subject_query_service,
        resource_authorization_service=resource_authorization_service,
    )
    return (
        service,
        knowledge_space_service,
        grant_subject_query_service,
        resource_authorization_service,
    )


def _expected_create_call():
    return call.create_knowledge_space(
        name="Alpha",
        description="A knowledge space",
        icon="alpha.svg",
        auth_type="public",
        is_released=False,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
        auto_tag_custom_tags=None,
    )


async def test_create_without_initial_permissions_compatible():
    created_space = _CreatedSpace()
    service, knowledge_service, query_service, authorization_service = _build_service(created_space)
    login_user = SimpleNamespace(user_id=7, tenant_id=3)

    result = await service.create(
        req=_CreateRequest(initial_permissions=None),
        login_user=login_user,
    )

    assert result is created_space
    assert knowledge_service.mock_calls == [_expected_create_call()]
    query_service.validate_creation_grants.assert_not_awaited()
    authorization_service.authorize.assert_not_awaited()


async def test_create_then_grant():
    grants = [
        AuthorizeGrantItem(
            subject_type="user",
            subject_id=42,
            relation="editor",
            include_children=False,
            model_id="editor",
        )
    ]
    events: list[str] = []
    service, knowledge_service, query_service, authorization_service = _build_service()
    login_user = SimpleNamespace(user_id=7, tenant_id=3)
    query_service.validate_creation_grant_request.side_effect = lambda **_: events.append("validate") or 3

    async def _create_once(**_):
        events.append("create")
        return _CreatedSpace()

    async def _authorize_once(*_, **__):
        events.append("authorize")

    knowledge_service.create_knowledge_space.side_effect = _create_once
    authorization_service.authorize.side_effect = _authorize_once

    result = await service.create(
        req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
        login_user=login_user,
    )

    assert events == ["validate", "create", "authorize"]
    assert result["id"] == 101
    assert result["initial_permission_result"] == {
        "status": "success",
        "error_code": None,
        "direct_applied_count": 0,
        "invite_created_count": 0,
        "invite_existing_count": 0,
        "failed_count": 0,
        "results": [],
    }
    query_service.validate_creation_grant_request.assert_awaited_once_with(
        resource_type="knowledge_space",
        grants=grants,
        login_user=login_user,
    )
    query_service.validate_creation_grant_subjects.assert_awaited_once_with(
        resource_type="knowledge_space",
        grants=[],
        login_user=login_user,
        tenant_id=3,
    )
    knowledge_service.create_knowledge_space.assert_awaited_once()
    authorization_service.authorize.assert_awaited_once_with(
        "knowledge_space",
        "101",
        AuthorizeRequest(grants=grants, revokes=[]),
        login_user,
        scenario_guarded=True,
    )
    # The legacy service remains the sole owner of creator membership, owner tuple,
    # audit, and other creation side effects. The application layer only calls it once.
    assert knowledge_service.mock_calls == [_expected_create_call()]


async def test_grant_failure_keeps_resource():
    grants = [AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer")]
    service, knowledge_service, query_service, authorization_service = _build_service()
    login_user = SimpleNamespace(user_id=7, tenant_id=3)
    failure = PermissionTupleWriteError()
    authorization_service.authorize.side_effect = failure

    result = await service.create(
        req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
        login_user=login_user,
    )

    assert result["id"] == 101
    assert result["initial_permission_result"] == {
        "status": "failed",
        "error_code": failure.code,
        "direct_applied_count": 0,
        "invite_created_count": 0,
        "invite_existing_count": 0,
        "failed_count": 0,
        "results": [],
    }
    query_service.validate_creation_grant_request.assert_awaited_once()
    query_service.validate_creation_grant_subjects.assert_awaited_once()
    knowledge_service.create_knowledge_space.assert_awaited_once()
    authorization_service.authorize.assert_awaited_once()
    assert knowledge_service.mock_calls == [_expected_create_call()]


async def test_invalid_grant_rejected_before_create():
    grants = [AuthorizeGrantItem(subject_type="department", subject_id=9, relation="owner")]
    service, knowledge_service, query_service, authorization_service = _build_service()
    login_user = SimpleNamespace(user_id=7, tenant_id=3)
    query_service.validate_creation_grant_request.side_effect = PermissionDeniedError()

    with pytest.raises(PermissionDeniedError):
        await service.create(
            req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
            login_user=login_user,
        )

    query_service.validate_creation_grant_request.assert_awaited_once_with(
        resource_type="knowledge_space",
        grants=grants,
        login_user=login_user,
    )
    knowledge_service.create_knowledge_space.assert_not_awaited()
    authorization_service.authorize.assert_not_awaited()


async def test_private_space_rejects_initial_grants_before_validation_or_create():
    grants = [AuthorizeGrantItem(subject_type="user", subject_id=42, relation="viewer")]
    service, knowledge_service, query_service, authorization_service = _build_service()

    with pytest.raises(PermissionDeniedError):
        await service.create(
            req=_CreateRequest(
                auth_type="private",
                initial_permissions=SimpleNamespace(grants=grants),
            ),
            login_user=SimpleNamespace(user_id=7, tenant_id=3),
        )

    query_service.validate_creation_grant_request.assert_not_awaited()
    knowledge_service.create_knowledge_space.assert_not_awaited()
    authorization_service.authorize.assert_not_awaited()


async def test_create_disabled_invite_scene_before_resource():
    from bisheng.common.errcode.approval import ApprovalScenarioDisabledError

    grants = [AuthorizeGrantItem(subject_type="user", subject_id=42, relation="viewer")]
    service, knowledge_service, query_service, authorization_service = _build_service()
    authorization_service.ensure_invite_scenario_available_for_grants.side_effect = ApprovalScenarioDisabledError()

    with (
        patch("bisheng.core.context.tenant.get_current_tenant_id", return_value=5),
        pytest.raises(ApprovalScenarioDisabledError),
    ):
        await service.create(
            req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
            login_user=SimpleNamespace(user_id=7, tenant_id=3),
        )

    authorization_service.ensure_invite_scenario_available_for_grants.assert_awaited_once_with(
        grants=grants,
        tenant_id=5,
    )
    knowledge_service.create_knowledge_space.assert_not_awaited()
    query_service.validate_creation_grant_request.assert_not_awaited()
    authorization_service.authorize.assert_not_awaited()


async def test_create_response_contains_mixed_item_results():
    grants = [
        AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
        AuthorizeGrantItem(subject_type="user", subject_id=42, relation="viewer"),
    ]
    service, knowledge_service, _, authorization_service = _build_service()
    authorization_service.authorize.return_value = AuthorizationResult(
        direct_applied_count=1,
        invite_created_count=1,
        results=[
            AuthorizationItemResult(
                operation="grant",
                subject_type="department",
                subject_id=9,
                relation="viewer",
                outcome="applied",
            ),
            AuthorizationItemResult(
                operation="grant",
                subject_type="user",
                subject_id=42,
                relation="viewer",
                outcome="invite_created",
                approval_instance_id=88,
            ),
        ],
    )

    result = await service.create(
        req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
        login_user=SimpleNamespace(user_id=7, tenant_id=3),
    )

    permission_result = result["initial_permission_result"]
    assert permission_result["status"] == "success"
    assert permission_result["direct_applied_count"] == 1
    assert permission_result["invite_created_count"] == 1
    assert permission_result["results"][1]["approval_instance_id"] == 88
    knowledge_service.create_knowledge_space.assert_awaited_once()


async def test_creation_prevalidates_only_direct_subjects_before_mixed_result():
    grants = [
        AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
        AuthorizeGrantItem(subject_type="user", subject_id=99, relation="viewer"),
    ]
    service, knowledge_service, query_service, authorization_service = _build_service()
    authorization_service.authorize.return_value = AuthorizationResult(
        direct_applied_count=1,
        failed_count=1,
        results=[
            AuthorizationItemResult(
                operation="grant",
                subject_type="department",
                subject_id=9,
                relation="viewer",
                outcome="applied",
            ),
            AuthorizationItemResult(
                operation="grant",
                subject_type="user",
                subject_id=99,
                relation="viewer",
                outcome="failed",
                error_code=21009,
            ),
        ],
    )
    login_user = SimpleNamespace(user_id=7, tenant_id=3)

    result = await service.create(
        req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
        login_user=login_user,
    )

    query_service.validate_creation_grant_request.assert_awaited_once_with(
        resource_type="knowledge_space",
        grants=grants,
        login_user=login_user,
    )
    query_service.validate_creation_grant_subjects.assert_awaited_once_with(
        resource_type="knowledge_space",
        grants=[grants[0]],
        login_user=login_user,
        tenant_id=3,
    )
    knowledge_service.create_knowledge_space.assert_awaited_once()
    assert result["initial_permission_result"]["failed_count"] == 1
