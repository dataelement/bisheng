from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError, PermissionTupleWriteError
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRequest


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
    resource_authorization_service = MagicMock()
    resource_authorization_service.authorize = AsyncMock()
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
    query_service.validate_creation_grants.side_effect = lambda **_: events.append("validate")

    async def _create_once(**_):
        events.append("create")
        return _CreatedSpace()

    async def _authorize_once(*_):
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
    }
    query_service.validate_creation_grants.assert_awaited_once_with(
        resource_type="knowledge_space",
        grants=grants,
        login_user=login_user,
    )
    knowledge_service.create_knowledge_space.assert_awaited_once()
    authorization_service.authorize.assert_awaited_once_with(
        "knowledge_space",
        "101",
        AuthorizeRequest(grants=grants, revokes=[]),
        login_user,
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
    }
    query_service.validate_creation_grants.assert_awaited_once()
    knowledge_service.create_knowledge_space.assert_awaited_once()
    authorization_service.authorize.assert_awaited_once()
    assert knowledge_service.mock_calls == [_expected_create_call()]


async def test_invalid_grant_rejected_before_create():
    grants = [AuthorizeGrantItem(subject_type="department", subject_id=9, relation="owner")]
    service, knowledge_service, query_service, authorization_service = _build_service()
    login_user = SimpleNamespace(user_id=7, tenant_id=3)
    query_service.validate_creation_grants.side_effect = PermissionDeniedError()

    with pytest.raises(PermissionDeniedError):
        await service.create(
            req=_CreateRequest(initial_permissions=SimpleNamespace(grants=grants)),
            login_user=login_user,
        )

    query_service.validate_creation_grants.assert_awaited_once_with(
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

    query_service.validate_creation_grants.assert_not_awaited()
    knowledge_service.create_knowledge_space.assert_not_awaited()
    authorization_service.authorize.assert_not_awaited()
