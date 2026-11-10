"""覆盖 AC: AC-09, AC-11, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from test.dsh.test_operation_worker import operation_scope  # noqa: F401
from test.dsh.test_policy_repository import NOW, sql_store  # noqa: F401


def build(scope, gateway):
    from bisheng.dsh.domain.services.admin import DshManagementService

    async def authorize(actor_id, tenant_id, user_id=None):
        if actor_id != 90 or tenant_id not in (None, 2):
            raise PermissionError()
        return {"user_id": "90", "tenant_id": "2", "scope": "tenant"}, 2

    state = {"now": NOW}
    profiles = AsyncMock(
        return_value={
            20: {"tenant_id": "2", "user_id": "20", "username": "Fresh", "display_name": "Fresh", "profile_version": 2}
        }
    )
    service = DshManagementService(
        repository_scope=scope,
        sessions=None,
        authorize=authorize,
        profiles=profiles,
        policy=SimpleNamespace(),
        policy_view=AsyncMock(),
        now=lambda: state["now"],
    )
    return service, profiles, state


async def test_subject_policy_management_stays_in_authorized_tenant(operation_scope):  # noqa: F811
    gateway = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "status": "active",
                "seat_limit": 10,
                "assigned": 1,
                "available": 9,
                "as_of": "2026-09-09T00:00:00Z",
                "license_id": "license",
                "expires_at": "2027-09-09T00:00:00Z",
            }
        )
    )
    service, _, _ = build(operation_scope, gateway)
    service.subject_grant = AsyncMock()
    service.subject_policy_view = AsyncMock(
        return_value={
            "tenant_id": 2,
            "model_id": 7,
            "departments": [
                {
                    "subject_type": "DEPARTMENT",
                    "subject_id": 10,
                    "name": "研发中心",
                    "parent_id": None,
                    "depth": 0,
                    "version": 0,
                    "enabled": False,
                    "monthly_token_limit": 0,
                }
            ],
            "roles": [],
        }
    )
    service.subject_grant = AsyncMock(
        return_value={
            "subject_type": "DEPARTMENT",
            "subject_id": 10,
            "model_id": 7,
            "name": "研发中心",
            "version": 1,
            "enabled": True,
            "monthly_token_limit": 200,
        }
    )
    inventory = await service.model_subjects(90, 7, tenant_id=2)
    assert inventory["departments"][0]["name"] == "研发中心"
    request = SimpleNamespace(expected_version=0, enabled=True, monthly_token_limit=200)
    result = await service.update_subject_policy(90, 7, "DEPARTMENT", 10, request, tenant_id=2)
    assert result["version"] == 1
    service.subject_grant.assert_awaited_once_with(
        actor={"user_id": "90", "tenant_id": "2", "scope": "tenant"},
        tenant=2,
        model_id=7,
        subject_type="DEPARTMENT",
        subject_id=10,
        actor_id=90,
        request=request,
    )


async def test_root_operation_lookup_is_instance_authorized(operation_scope):  # noqa: F811
    from bisheng.dsh.domain.models.admin_operation import DshAdminOperation

    operation_id = "00000000-0000-4000-8000-000000000002"
    service, _, _ = build(operation_scope, None)
    with operation_scope() as repository:
        repository.session.add(
            DshAdminOperation(
                operation_id=operation_id,
                tenant_id=2,
                user_id=20,
                actor_user_id=90,
                action="UPDATE_POLICY",
                expected_policy_version=0,
                payload_hash="x" * 64,
                payload={},
                status="SUCCEEDED",
            )
        )

    async def root_authorize(*args):
        return {"user_id": "90", "tenant_id": "1", "scope": "instance"}, None

    service.authorize = root_authorize
    result = await service.operation(90, "00000000-0000-4000-8000-000000000002")
    assert result["tenant_id"] == 2 and result["status"] == "SUCCEEDED"
