"""覆盖 AC: AC-09, AC-11, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
        gateway=gateway,
        authorize=authorize,
        profiles=profiles,
        policy=SimpleNamespace(),
        policy_view=AsyncMock(),
        now=lambda: state["now"],
    )
    return service, profiles, state


async def test_users_preserves_gateway_pagination_and_batches_current_page(operation_scope):  # noqa: F811
    gateway = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "items": [
                    {
                        "user_id": "20",
                        "tenant_id": "2",
                        "seat_id": "seat",
                        "state": "ASSIGNED",
                        "grant_version": 1,
                        "username": "Old",
                        "display_name": "Old",
                        "profile_version": 1,
                        "profile_synced_at": None,
                        "last_login_at": None,
                        "last_seen_at": None,
                        "active_session_count": 0,
                        "login_state": "NO_SESSIONS",
                        "created_at": "2026-09-09T00:00:00Z",
                    }
                ],
                "next_cursor": "opaque",
                "has_more": True,
            }
        )
    )
    service, profiles, _ = build(operation_scope, gateway)
    result = await service.users(90, cursor="prior", limit=10)
    assert result["next_cursor"] == "opaque" and result["has_more"] is True
    assert result["items"][0]["username"] == "Fresh"
    profiles.assert_awaited_once_with([20])
    assert gateway.request.await_args.args[1]["cursor"] == "prior"
    with pytest.raises(PermissionError):
        await service.users(91)
    with pytest.raises(PermissionError):
        await service.users(90, tenant_id=3)


async def test_gateway_failure_is_unavailable_not_zero(operation_scope):  # noqa: F811
    from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError

    service, _, _ = build(operation_scope, SimpleNamespace(request=AsyncMock(side_effect=TimeoutError())))
    with pytest.raises(DshAuthorizationUnavailableError):
        await service.license(90)


async def test_command_timeout_recovers_original_operation_without_new_intent(operation_scope):  # noqa: F811
    gateway = SimpleNamespace(
        request=AsyncMock(
            side_effect=[
                TimeoutError(),
                {
                    "operation_id": "00000000-0000-4000-8000-000000000001",
                    "status": "SUCCEEDED",
                    "result_grant_version": 2,
                    "result_code": None,
                },
                {
                    "operation_id": "00000000-0000-4000-8000-000000000001",
                    "status": "SUCCEEDED",
                    "result_grant_version": 2,
                    "result_code": None,
                },
            ]
        )
    )
    service, _, state = build(operation_scope, gateway)
    result = await service.command(90, 20, "REVOKE", "00000000-0000-4000-8000-000000000001", 1, tenant_id=2)
    assert result["status"] == "PROCESSING"
    state["now"] += timedelta(seconds=31)
    result = await service.command(90, 20, "REVOKE", "00000000-0000-4000-8000-000000000001", 1, tenant_id=2)
    assert result["status"] == "SUCCEEDED"
    assert result["actor_user_id"] == 90 and result["before_values"] == {"grant_version": 1, "state": "ASSIGNED"}
    assert gateway.request.await_args_list[1].args == (
        "operation",
        {"operation_id": "00000000-0000-4000-8000-000000000001"},
    )
    assert result["after_values"] == {"grant_version": 2, "state": "REVOKED"}
    assert gateway.request.await_count == 3
    assert gateway.request.await_args_list[2] == gateway.request.await_args_list[0]


async def test_foreign_tenant_page_is_refused(operation_scope):  # noqa: F811
    from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError

    gateway = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "items": [
                    {
                        "user_id": "20",
                        "tenant_id": "3",
                        "seat_id": "seat",
                        "state": "ASSIGNED",
                        "grant_version": 1,
                        "username": "Old",
                        "display_name": "Old",
                        "profile_version": 1,
                        "profile_synced_at": None,
                        "last_login_at": None,
                        "last_seen_at": None,
                        "active_session_count": 0,
                        "login_state": "NO_SESSIONS",
                        "created_at": "2026-09-09T00:00:00Z",
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            }
        )
    )
    service, profiles, _ = build(operation_scope, gateway)
    with pytest.raises(DshAuthorizationUnavailableError):
        await service.users(90)
    profiles.assert_not_awaited()


async def test_root_operation_lookup_is_instance_authorized(operation_scope):  # noqa: F811
    gateway = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "operation_id": "00000000-0000-4000-8000-000000000002",
                "status": "SUCCEEDED",
                "result_grant_version": 2,
                "result_code": None,
            }
        )
    )
    service, _, _ = build(operation_scope, gateway)
    await service.command(90, 20, "REVOKE", "00000000-0000-4000-8000-000000000002", 1, tenant_id=2)

    async def root_authorize(*args):
        return {"user_id": "90", "tenant_id": "1", "scope": "instance"}, None

    service.authorize = root_authorize
    result = await service.operation(90, "00000000-0000-4000-8000-000000000002")
    assert result["tenant_id"] == 2 and result["status"] == "SUCCEEDED"


async def test_revoked_actor_cannot_send_unexecuted_retry(operation_scope):  # noqa: F811
    from fastapi import HTTPException

    gateway = SimpleNamespace(
        request=AsyncMock(
            side_effect=[
                TimeoutError(),
                {
                    "operation_id": "00000000-0000-4000-8000-000000000003",
                    "status": "UNKNOWN",
                    "result_grant_version": None,
                    "result_code": None,
                },
            ]
        )
    )
    service, _, state = build(operation_scope, gateway)
    await service.command(90, 20, "REVOKE", "00000000-0000-4000-8000-000000000003", 1, tenant_id=2)
    state["now"] += timedelta(seconds=31)

    async def denied(*args):
        raise HTTPException(403, "Role removed")

    service.authorize = denied
    result = await service.resume("00000000-0000-4000-8000-000000000003")
    assert result["status"] == "FAILED" and result["result_code"] == "permission_denied"
    assert gateway.request.await_count == 2


async def test_terminal_lookup_requires_matching_intent_replay(operation_scope):  # noqa: F811
    from bisheng.dsh.infrastructure.gateway_client import GatewayCommandRejected

    operation_id = "00000000-0000-4000-8000-000000000004"
    gateway = SimpleNamespace(
        request=AsyncMock(
            side_effect=[
                TimeoutError(),
                {"operation_id": operation_id, "status": "SUCCEEDED", "result_grant_version": 9, "result_code": None},
                GatewayCommandRejected(),
            ]
        )
    )
    service, _, state = build(operation_scope, gateway)
    original = await service.command(90, 20, "REVOKE", operation_id, 1, tenant_id=2)
    assert original["status"] == "PROCESSING"
    state["now"] += timedelta(seconds=31)
    result = await service.resume(operation_id)
    assert result["status"] == "FAILED" and result["result_code"] == "authorization_conflict"
    assert result["payload"] == original["payload"]
    assert result["after_values"] != {"grant_version": 9}
    assert gateway.request.await_args_list[0] == gateway.request.await_args_list[2]
    assert (await service.resume(operation_id))["status"] == "FAILED"
    assert gateway.request.await_count == 3


@pytest.mark.parametrize("code", ["dsh_disabled", "license_invalid", "license_expired", "seat_limit_reached"])
async def test_durable_failure_replay_finishes_without_replacing_intent(operation_scope, code):  # noqa: F811
    operation_id = "00000000-0000-4000-8000-000000000005"
    terminal = {"operation_id": operation_id, "status": "FAILED", "result_grant_version": None, "result_code": code}
    gateway = SimpleNamespace(request=AsyncMock(side_effect=[TimeoutError(), terminal, terminal]))
    service, _, state = build(operation_scope, gateway)
    original = await service.command(90, 20, "REASSIGN", operation_id, 2, tenant_id=2)
    assert original["status"] == "PROCESSING"
    state["now"] += timedelta(seconds=31)
    result = await service.resume(operation_id)
    assert result["status"] == "FAILED" and result["result_code"] == code
    assert result["payload"] == original["payload"] and result["actor_user_id"] == 90
    assert gateway.request.await_args_list[0] == gateway.request.await_args_list[2]


async def test_terminal_lookup_does_not_override_unavailable_intent_confirmation(operation_scope):  # noqa: F811
    operation_id = "00000000-0000-4000-8000-000000000006"
    terminal = {"operation_id": operation_id, "status": "SUCCEEDED", "result_grant_version": 2, "result_code": None}
    gateway = SimpleNamespace(request=AsyncMock(side_effect=[TimeoutError(), terminal, TimeoutError()]))
    service, _, state = build(operation_scope, gateway)
    await service.command(90, 20, "REVOKE", operation_id, 1, tenant_id=2)
    state["now"] += timedelta(seconds=31)
    result = await service.resume(operation_id)
    assert result["status"] == "PROCESSING"
    assert result["result_code"] == "authorization_unavailable"
