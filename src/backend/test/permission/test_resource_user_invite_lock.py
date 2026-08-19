from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from bisheng.permission.domain.models.resource_user_invite_request import ResourceUserInviteRequest
from bisheng.permission.domain.services.resource_user_invite_lock import (
    build_resource_user_invite_business_key,
    build_resource_user_invite_lock_key,
    resource_user_invite_lock,
)


class FakeRedis:
    def __init__(self, *, release_error: Exception | None = None) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool, int | None]] = []
        self.eval_calls: list[tuple[str, int, str, str, tuple[object, ...]]] = []
        self.release_error = release_error

    async def set(self, name: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        self.set_calls.append((name, value, nx, ex))
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        token: str,
        *args: object,
    ) -> int:
        self.eval_calls.append((script, numkeys, key, token, args))
        if self.values.get(key) != token:
            return 0
        if args:
            return 1
        if self.release_error is not None:
            raise self.release_error
        self.values.pop(key, None)
        return 1


def test_business_and_lock_keys_only_use_stable_invite_identity() -> None:
    business_key = build_resource_user_invite_business_key(
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
    )

    assert business_key == "resource-user-invite:knowledge_space:88:user:9"
    assert business_key == build_resource_user_invite_business_key(
        resource_type="knowledge_space",
        resource_id="88",
        target_user_id=9,
    )
    assert (
        build_resource_user_invite_lock_key(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=88,
            target_user_id=9,
        )
        == "permission:resource-user-invite:7:knowledge_space:88:9"
    )


async def test_lock_uses_atomic_set_with_configured_ttl() -> None:
    redis = FakeRedis()
    lock_key = build_resource_user_invite_lock_key(
        tenant_id=7,
        resource_type="channel",
        resource_id="news",
        target_user_id=9,
    )

    async with resource_user_invite_lock(
        tenant_id=7,
        resource_type="channel",
        resource_id="news",
        target_user_id=9,
        redis_client=redis,
        ttl_seconds=17,
    ) as lock:
        lock.ensure_owned()
        assert redis.set_calls == [(lock_key, lock.token, True, 17)]

    assert lock_key not in redis.values


async def test_release_only_deletes_the_callers_token() -> None:
    redis = FakeRedis()
    lock_key = build_resource_user_invite_lock_key(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
    )

    async with resource_user_invite_lock(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
        redis_client=redis,
        ttl_seconds=15,
    ) as lock:
        previous_token = lock.token
        redis.values[lock_key] = "replacement-owner-token"

    assert redis.values[lock_key] == "replacement-owner-token"
    assert redis.eval_calls[-1][2:4] == (lock_key, previous_token)


async def test_context_manager_releases_lock_after_business_exception() -> None:
    redis = FakeRedis()
    lock_key = build_resource_user_invite_lock_key(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
    )

    with pytest.raises(ValueError, match="business failed"):
        async with resource_user_invite_lock(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=88,
            target_user_id=9,
            redis_client=redis,
            ttl_seconds=15,
        ):
            raise ValueError("business failed")

    assert lock_key not in redis.values


async def test_release_failure_does_not_replace_business_exception() -> None:
    redis = FakeRedis(release_error=RuntimeError("redis release failed"))

    with pytest.raises(ValueError, match="business failed"):
        async with resource_user_invite_lock(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=88,
            target_user_id=9,
            redis_client=redis,
            ttl_seconds=15,
        ):
            raise ValueError("business failed")

    assert redis.eval_calls


async def test_release_failure_propagates_after_successful_business_block() -> None:
    redis = FakeRedis(release_error=RuntimeError("redis release failed"))

    with pytest.raises(RuntimeError, match="redis release failed"):
        async with resource_user_invite_lock(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=88,
            target_user_id=9,
            redis_client=redis,
            ttl_seconds=15,
        ):
            pass


async def test_cancelled_business_block_attempts_release_and_preserves_cancellation() -> None:
    redis = FakeRedis(release_error=RuntimeError("redis release failed"))
    lock_key = build_resource_user_invite_lock_key(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
    )

    with pytest.raises(asyncio.CancelledError):
        async with resource_user_invite_lock(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=88,
            target_user_id=9,
            redis_client=redis,
            ttl_seconds=15,
        ):
            raise asyncio.CancelledError

    assert redis.eval_calls
    assert lock_key in redis.values


def _invite_values(*, business_key: str, inviter_user_id: int) -> dict[str, object]:
    return {
        "tenant_id": 7,
        "business_key": business_key,
        "active_marker": 0,
        "request_fingerprint": "request-fingerprint",
        "resource_type": "knowledge_space",
        "resource_id": "88",
        "resource_name": "Knowledge Space",
        "inviter_user_id": inviter_user_id,
        "inviter_user_name": f"inviter-{inviter_user_id}",
        "target_user_id": 9,
        "target_user_name": "target-user",
        "relation": "editor",
        "model_id": None,
        "include_children": False,
        "role_snapshot": {"role": "editor"},
        "role_fingerprint": "role-fingerprint",
        "approval_instance_id": None,
        "decision_event_id": None,
        "execution_state": "awaiting_approval",
        "execution_token": None,
        "error_summary": None,
        "result_snapshot": {},
    }


async def test_database_unique_constraint_is_authoritative_when_redis_lock_is_partitioned() -> None:
    first_redis = FakeRedis()
    second_redis = FakeRedis()
    business_key = build_resource_user_invite_business_key(
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
    )
    engine = create_engine("sqlite://")
    ResourceUserInviteRequest.__table__.create(engine)

    async with resource_user_invite_lock(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id=88,
        target_user_id=9,
        redis_client=first_redis,
        ttl_seconds=15,
    ):
        async with resource_user_invite_lock(
            tenant_id=7,
            resource_type="knowledge_space",
            resource_id=88,
            target_user_id=9,
            redis_client=second_redis,
            ttl_seconds=15,
        ):
            with engine.begin() as connection:
                connection.execute(
                    ResourceUserInviteRequest.__table__.insert(),
                    _invite_values(business_key=business_key, inviter_user_id=101),
                )

            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        ResourceUserInviteRequest.__table__.insert(),
                        _invite_values(business_key=business_key, inviter_user_id=202),
                    )
