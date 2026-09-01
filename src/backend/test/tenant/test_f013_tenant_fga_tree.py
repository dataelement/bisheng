"""Tenant identity invariants retained by the F048 authorization model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.tenant_fga import (
    RootTenantAdminNotAllowedError,
)
from bisheng.core.openfga.authorization_model_f048 import (
    build_authorization_model_f048,
)
from bisheng.permission.application import PermissionObject, PermissionRelation, PermissionSubject
from bisheng.tenant.domain.services.tenant_admin_service import (
    TenantAdminService,
)


def _types_by_name() -> dict[str, dict]:
    model = build_authorization_model_f048()
    return {definition["type"]: definition for definition in model["type_definitions"]}


def test_f048_retains_tenant_and_department_identity_relations() -> None:
    types = _types_by_name()
    assert set(types["tenant"]["relations"]) == {
        "admin",
        "member",
        "shared_to",
    }
    assert {
        "admin",
        "child",
        "member",
        "parent",
        "subtree_member",
    } <= set(types["department"]["relations"])
    assert "visible" in types["workflow"]["relations"]
    assert "can_edit" in types["workflow"]["relations"]
    assert "llm_server" in types
    assert "llm_model" in types


def test_tenant_membership_is_not_a_resource_grant_subject() -> None:
    grant = _types_by_name()["permission_grant"]
    subject_types = grant["metadata"]["relations"]["ordinary_assignee"]["directly_related_user_types"]
    assert {"type": "tenant", "relation": "member"} not in subject_types
    assert {
        "type": "department",
        "relation": "subtree_member",
    } in subject_types


@pytest.mark.asyncio
async def test_child_admin_grant_writes_only_the_child_tuple() -> None:
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    permissions = MagicMock()
    permissions.grant = AsyncMock()

    with (
        patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as tenant_dao,
        patch(
            "bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api",
            AsyncMock(return_value=permissions),
        ),
    ):
        tenant_dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.grant_tenant_admin(
            tenant_id=5,
            user_id=10,
        )

    permissions.grant.assert_awaited_once_with(
        (
            PermissionRelation(
                subject=PermissionSubject("user", "10"),
                relation="admin",
                resource=PermissionObject("tenant", "5"),
            ),
        )
    )


@pytest.mark.asyncio
async def test_direct_root_admin_grant_is_rejected_before_fga() -> None:
    with (
        patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as tenant_dao,
        patch("bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api") as get_permissions,
    ):
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(
                tenant_id=1,
                user_id=10,
            )
        tenant_dao.aget_by_id.assert_not_called()
        get_permissions.assert_not_called()
