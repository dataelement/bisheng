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
from bisheng.tenant.domain.services.tenant_admin_service import (
    TenantAdminService,
)


def _types_by_name() -> dict[str, dict]:
    model = build_authorization_model_f048()
    return {
        definition["type"]: definition
        for definition in model["type_definitions"]
    }


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
    subject_types = grant["metadata"]["relations"][
        "ordinary_assignee"
    ]["directly_related_user_types"]
    assert {"type": "tenant", "relation": "member"} not in subject_types
    assert {
        "type": "department",
        "relation": "subtree_member",
    } in subject_types


@pytest.mark.asyncio
async def test_normal_user_has_no_child_tenant_admin_shortcut() -> None:
    from bisheng.common.dependencies.user_deps import UserPayload

    with patch("bisheng.user.domain.services.auth.UserRoleDao") as role_dao:
        role_dao.get_user_roles.return_value = []
        user = UserPayload(
            user_id=200,
            user_name="normal",
            user_role=[],
            tenant_id=1,
        )
    fake_fga = MagicMock()
    fake_fga.check = AsyncMock(return_value=False)
    with patch(
        "bisheng.core.openfga.manager.aget_fga_client",
        AsyncMock(return_value=fake_fga),
    ):
        assert await user.has_tenant_admin(5) is False


@pytest.mark.asyncio
async def test_root_tenant_never_uses_tenant_admin_tuple() -> None:
    from bisheng.common.dependencies.user_deps import UserPayload

    with patch("bisheng.user.domain.services.auth.UserRoleDao") as role_dao:
        role_dao.get_user_roles.return_value = []
        user = UserPayload(
            user_id=300,
            user_name="superx",
            user_role=[],
            tenant_id=1,
        )
    with patch("bisheng.core.openfga.manager.aget_fga_client") as get_fga:
        assert await user.has_tenant_admin(1) is False
    get_fga.assert_not_called()


@pytest.mark.asyncio
async def test_child_admin_grant_writes_only_the_child_tuple() -> None:
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    fake_fga = MagicMock()
    fake_fga.write_tuples = AsyncMock()

    with (
        patch(
            "bisheng.tenant.domain.services.tenant_admin_service.TenantDao"
        ) as tenant_dao,
        patch(
            "bisheng.tenant.domain.services.tenant_admin_service."
            "_aget_fga_client_with_fallback",
            AsyncMock(return_value=fake_fga),
        ),
    ):
        tenant_dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.grant_tenant_admin(
            tenant_id=5,
            user_id=10,
        )

    fake_fga.write_tuples.assert_awaited_once_with(
        writes=[
            {
                "user": "user:10",
                "relation": "admin",
                "object": "tenant:5",
            }
        ]
    )


@pytest.mark.asyncio
async def test_direct_root_admin_grant_is_rejected_before_fga() -> None:
    with (
        patch(
            "bisheng.tenant.domain.services.tenant_admin_service.TenantDao"
        ) as tenant_dao,
        patch(
            "bisheng.tenant.domain.services.tenant_admin_service."
            "_aget_fga_client_with_fallback"
        ) as get_fga,
    ):
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(
                tenant_id=1,
                user_id=10,
            )
        tenant_dao.aget_by_id.assert_not_called()
        get_fga.assert_not_called()
