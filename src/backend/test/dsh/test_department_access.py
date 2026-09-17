"""覆盖 AC: AC-06, AC-07, AC-08, AC-09, AC-11."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.dsh.domain.services.access_status import read_access_statuses
from test.dsh.test_subject_policy import subject_store, update  # noqa: F401


def seat(user_id, state="ASSIGNED", tenant=2):
    return {
        "user_id": str(user_id),
        "tenant_id": str(tenant),
        "seat_id": "s",
        "state": state,
        "grant_version": 1,
        "username": "User",
        "display_name": "User",
        "profile_version": 1,
        "profile_synced_at": None,
        "last_login_at": None,
        "last_seen_at": None,
        "active_session_count": 0,
        "login_state": "NO_SESSIONS",
        "created_at": "2026-09-17T00:00:00Z",
    }


@pytest.mark.parametrize("available,expected", [(1, "PENDING_LOGIN"), (0, "SEAT_LIMIT_REACHED")])
async def test_access_status_uses_seats_and_capacity(available, expected):
    async def request(_operation, payload):
        user_id = int(payload["target"]["user_id"])
        state = {1: "ASSIGNED", 2: "REVOKED"}.get(user_id)
        rows = [seat(user_id, state)] if state == payload["seat_state"] else []
        return {"items": rows, "next_cursor": None, "has_more": False}

    rows = [{"user_id": i, "authorized": i > 0} for i in range(4)]
    result = await read_access_statuses(
        rows,
        tenant=2,
        actor={},
        snapshot=AsyncMock(return_value={"status": "active", "available": available}),
        request=request,
    )
    assert result == {0: "UNAUTHORIZED", 1: "AUTHORIZED", 2: "REVOKED", 3: expected}


async def test_unavailable_license_and_foreign_seat_are_explicit():
    from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError

    rows = [{"user_id": 1, "authorized": True}]
    result = await read_access_statuses(
        rows,
        tenant=2,
        actor={},
        snapshot=AsyncMock(side_effect=DshAuthorizationUnavailableError()),
        request=AsyncMock(),
    )
    assert result[1] == "UNAVAILABLE"
    request = AsyncMock(return_value={"items": [seat(1, tenant=3)], "next_cursor": None, "has_more": False})
    result = await read_access_statuses(
        rows, tenant=2, actor={}, snapshot=AsyncMock(return_value={"status": "active", "available": 0}), request=request
    )
    assert result[1] == "UNAVAILABLE"


async def test_quota_write_keeps_capacity_at_login():
    from bisheng.dsh.domain.services.admin import DshManagementService

    policy = SimpleNamespace(update_policy=AsyncMock(return_value={"status": "SUCCEEDED"}))
    gateway = SimpleNamespace(request=AsyncMock(side_effect=AssertionError("Quota save is local")))
    service = DshManagementService(
        repository_scope=None,
        gateway=gateway,
        authorize=AsyncMock(return_value=({}, 2)),
        profiles=None,
        policy=policy,
        policy_view=None,
        now=None,
    )
    await service.update_policy(
        90, 20, SimpleNamespace(enabled=True, monthly_token_limit=100000), model_id=7, tenant_id=2
    )
    assert policy.update_policy.await_args.kwargs["seat_limit"] is None
    gateway.request.assert_not_awaited()


@pytest.mark.parametrize("license_status", ["license_invalid", "license_expired", "dsh_disabled"])
async def test_license_state_preserves_quota_and_zero_quota_status(license_status):
    request = AsyncMock()
    result = await read_access_statuses(
        [{"user_id": 1, "authorized": True}, {"user_id": 2, "authorized": False}],
        tenant=2,
        actor={},
        snapshot=AsyncMock(return_value={"status": license_status}),
        request=request,
    )
    assert result == {1: "LICENSE_UNAVAILABLE", 2: "UNAUTHORIZED"}
    request.assert_not_awaited()


@pytest.mark.parametrize("personal,expected", [(0, 100000), (6000, 100000), (1000000, 1000000)])
def test_department_and_personal_quota_maximum(subject_store, personal, expected):  # noqa: F811
    from sqlmodel import Session

    from bisheng.dsh.domain.models.user_policy import DshUserPolicy
    from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository

    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        update(repository, "DEPARTMENT", 10, 100000)
        session.add(
            DshUserPolicy(
                user_id=20,
                tenant_id=2,
                model_id=7,
                enabled=int(personal > 0),
                monthly_token_limit=personal,
                version=1,
                quota_epoch=1,
                quota_sync_state="READY",
                updated_by=90,
            )
        )
        session.flush()
        assert (
            repository.user_permissions([(20, "admin")], model_id=7, limit=10)["items"][0]["monthly_token_limit"]
            == expected
        )


def test_unassigned_and_numeric_user_search(subject_store):  # noqa: F811
    from sqlmodel import Session

    from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository

    with Session(subject_store) as session:
        assert UserDshProfileRepository.access_users(session, keyword="20") == [(20, "admin")]
        assert UserDshProfileRepository.access_users(session, unassigned_only=True) == [(21, "guest")]
