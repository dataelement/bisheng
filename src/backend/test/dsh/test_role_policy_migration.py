"""覆盖 AC: AC-10, AC-11."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.dsh.domain.services.role_migration import migrate_role_policies, role_migration_plan


def member(direct=6000, role=100000):
    return {
        "user_id": 20,
        "direct_enabled": True,
        "direct_monthly_token_limit": direct,
        "direct_version": 3,
        "direct_pending_operation_id": None,
        "monthly_token_limit": max(direct, role),
        "sources": [{"subject_type": "ROLE", "monthly_token_limit": role}],
    }


@pytest.mark.parametrize("direct,expected", [(0, 100000), (6000, 100000), (1000000, 1000000)])
def test_role_plan_preserves_the_maximum(direct, expected):
    assert role_migration_plan([member(direct)])[0]["target_limit"] == expected


async def test_failed_user_write_keeps_role_policy_enabled():
    user = member()
    service = SimpleNamespace(
        model_subjects=AsyncMock(
            return_value={"roles": [{"subject_id": 41, "enabled": True, "monthly_token_limit": 100000, "version": 1}]}
        ),
        model_user_permissions=AsyncMock(return_value={"items": [user], "has_more": False}),
        update_policy=AsyncMock(side_effect=RuntimeError("Unavailable")),
        update_subject_policy=AsyncMock(),
    )
    with pytest.raises(RuntimeError):
        await migrate_role_policies(service, actor_id=90, tenant_id=2, model_id=7, apply=True)
    service.update_subject_policy.assert_not_awaited()


async def test_dry_run_and_completed_migration_are_write_free():
    service = SimpleNamespace(
        model_subjects=AsyncMock(return_value={"roles": []}),
        model_user_permissions=AsyncMock(return_value={"items": [member()], "has_more": False}),
        update_policy=AsyncMock(),
        update_subject_policy=AsyncMock(),
    )
    result = await migrate_role_policies(service, actor_id=90, tenant_id=2, model_id=7, apply=True)
    assert result["roles"] == []
    service.update_policy.assert_not_awaited()


async def test_migration_verifies_personal_quota_before_retiring_roles_and_is_repeatable():
    user = member()
    role = {"subject_id": 41, "enabled": True, "monthly_token_limit": 100000, "version": 1}
    events = []

    async def save_user(actor, user_id, request, **kwargs):
        events.append("personal")
        assert request.monthly_token_limit == 100000
        assert request.expected_version == 3
        user.update(direct_monthly_token_limit=100000, direct_version=4)
        return {"status": "SUCCEEDED", "operation_id": request.operation_id}

    async def save_role(actor, model_id, subject_type, subject_id, request, **kwargs):
        events.append("role")
        assert user["direct_monthly_token_limit"] == 100000
        assert request.enabled is False
        assert request.expected_version == 1
        role["enabled"] = False
        user["sources"] = []

    service = SimpleNamespace(
        model_subjects=AsyncMock(side_effect=lambda *a, **kw: {"roles": [role]}),
        model_user_permissions=AsyncMock(side_effect=lambda *a, **kw: {"items": [dict(user)], "has_more": False}),
        update_policy=AsyncMock(side_effect=save_user),
        update_subject_policy=AsyncMock(side_effect=save_role),
    )
    dry_run = await migrate_role_policies(service, actor_id=90, tenant_id=2, model_id=7)
    assert dry_run["users"][0]["target_limit"] == 100000
    assert events == []
    result = await migrate_role_policies(service, actor_id=90, tenant_id=2, model_id=7, apply=True)
    assert result["effective_limits"] == {20: 100000}
    assert events == ["personal", "role"]
    await migrate_role_policies(service, actor_id=90, tenant_id=2, model_id=7, apply=True)
    assert events == ["personal", "role"]
