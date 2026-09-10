"""覆盖 AC: AC-18, AC-21, AC-22, AC-27, AC-28, AC-29, AC-30, AC-34."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
from bisheng.dsh.domain.services.admin_policy import DshAdminService
from test.dsh.test_policy_repository import NOW, sql_store  # noqa: F401
from test.dsh.test_quota_admission import quota as real_quota  # noqa: F401
from test.dsh.test_quota_admission import running


class QuotaDouble:
    def __init__(self, fail_after=None):
        self.calls = []
        self.reasons = {"STORAGE_UNCERTAIN:request-1"}
        self.version = 0
        self.generation = 0
        self.fail_after = fail_after
        self.crashed = False

    async def ensure_new_user(self, tenant_id, user_id, **kwargs):
        assert kwargs["proof"]["history_empty"]

    def crashed_after(self, name):
        if self.fail_after == name and not self.crashed:
            self.crashed = True
            raise TimeoutError("injected response loss after side effect")

    async def block_policy(self, tenant_id, user_id, **kwargs):
        self.calls.append("block")
        self.generation = kwargs["lease_generation"]
        self.reasons.add("POLICY_SYNC:" + kwargs["operation_id"])
        self.crashed_after("block")

    async def install_policy(self, tenant_id, user_id, **kwargs):
        self.calls.append("install")
        assert kwargs["lease_generation"] == self.generation
        self.version = kwargs["version"]
        self.crashed_after("install")

    async def finish_policy(self, tenant_id, user_id, **kwargs):
        self.calls.append("finish")
        assert kwargs["lease_generation"] == self.generation
        assert kwargs["expected_policy_version"] == self.version
        self.reasons.discard("POLICY_SYNC:" + kwargs["operation_id"])
        self.crashed_after("finish")


@pytest.fixture
def service_factory(sql_store):  # noqa: F811 - Imported pytest fixture is injected by name.
    def build(failure=None, quota=None):
        state = {"allowed": True, "models_allowed": True, "now": NOW, "fail_sql": failure, "crashed": False}

        @contextmanager
        def repository_scope():
            with Session(sql_store) as session, session.begin():
                repository = DshPolicyRepository(session)
                yield repository
                operation = repository.operations.get("a")
                phase = (operation.result_payload or {}).get("phase") if operation else None
                if state["fail_sql"] is not None and state["fail_sql"] == phase and not state["crashed"]:
                    state["crashed"] = True
                    raise TimeoutError("injected SQL transaction rollback")

        async def authorize(actor_user_id, user_id):
            assert (actor_user_id, user_id) == (90, 20)
            return state["allowed"]

        async def models(actor_user_id, user_id, model_ids):
            assert model_ids == [2]
            return state["models_allowed"]

        quota = quota or QuotaDouble()
        service = DshAdminService(
            repository_scope=repository_scope,
            quota=quota,
            authorize=authorize,
            validate_models=models,
            now=lambda: state["now"],
        )
        return service, state, quota

    return build


def request():
    return DshUserPolicyInput(
        operation_id="a",
        expected_version=0,
        monthly_token_limit=100,
        enabled=True,
    )


async def test_update_policy_keeps_storage_freeze_and_audit(service_factory):
    service, _state, quota = service_factory()
    result = await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    assert result["status"] == "SUCCEEDED"
    assert quota.calls == ["block", "install", "finish"]
    assert quota.reasons == {"STORAGE_UNCERTAIN:request-1"}
    original = deepcopy(result)
    repeated = await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    assert repeated == original
    assert quota.calls == ["block", "install", "finish"]


@pytest.mark.parametrize("failure", ["block", "install", "finish"])
async def test_remote_result_loss_resumes_same_operation(service_factory, failure):
    service, state, quota = service_factory(quota=QuotaDouble(failure))
    processing = await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    assert processing["status"] == "PROCESSING"
    committed = deepcopy(processing["after_values"])
    state["now"] += timedelta(seconds=31)
    result = await service.resume("a")
    assert result["status"] == "SUCCEEDED"
    assert result["after_values"]["version"] == 1
    if committed:
        assert result["after_values"] == committed
    assert quota.version == 1
    assert quota.reasons == {"STORAGE_UNCERTAIN:request-1"}


@pytest.mark.parametrize("phase", ["SQL_COMMITTED", "SQL_READY", "EFFECTIVE"])
async def test_sql_crash_resumes_without_extra_policy_version(service_factory, phase):
    service, state, quota = service_factory(failure=phase)
    processing = await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    assert processing["status"] == "PROCESSING"
    state["now"] += timedelta(seconds=31)
    result = await service.resume("a")
    assert result["status"] == "SUCCEEDED"
    assert result["after_values"]["version"] == 1
    assert quota.reasons == {"STORAGE_UNCERTAIN:request-1"}


async def test_revoked_permission_before_commit_fails_but_committed_intent_finishes(service_factory):
    service, state, quota = service_factory(quota=QuotaDouble("block"))
    await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    state["allowed"] = False
    state["now"] += timedelta(seconds=31)
    failed = await service.resume("a")
    assert failed["status"] == "FAILED"
    assert failed["committed_at"] is None
    assert quota.version == 0
    assert quota.reasons == {"STORAGE_UNCERTAIN:request-1"}


async def test_revoked_permission_after_commit_preserves_authorized_intent(service_factory):
    service, state, _quota = service_factory(quota=QuotaDouble("install"))
    await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    state["allowed"] = False
    state["models_allowed"] = False
    state["now"] += timedelta(seconds=31)
    result = await service.resume("a")
    assert result["status"] == "SUCCEEDED"
    assert result["after_values"]["version"] == 1


async def test_two_operations_cannot_replace_pending_owner(service_factory):
    from bisheng.common.errcode.dsh import DshOperationInProgressError

    service, _state, _quota = service_factory(quota=QuotaDouble("block"))
    await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    other = request().model_copy(update={"operation_id": "b"})
    with pytest.raises(DshOperationInProgressError):
        await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=other)
    assert service._read("a")["status"] == "PROCESSING"


async def test_old_worker_cannot_commit_after_new_lease(service_factory):
    import asyncio

    service, state, quota = service_factory()
    waiting = asyncio.Event()
    proceed = asyncio.Event()
    count = 0

    async def pause_first_validation(actor_user_id, user_id, model_ids):
        nonlocal count
        count += 1
        if count == 1:
            waiting.set()
            await proceed.wait()
        return True

    service.validate_models = pause_first_validation
    old = asyncio.create_task(service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request()))
    await asyncio.wait_for(waiting.wait(), timeout=2)
    state["now"] += timedelta(seconds=31)
    latest = await service.resume("a")
    proceed.set()
    stale_result = await asyncio.wait_for(old, timeout=2)
    assert latest["status"] == stale_result["status"] == "SUCCEEDED"
    assert latest["lease_generation"] == 2
    assert latest["after_values"]["version"] == 1
    assert quota.calls.count("install") == 1


async def test_inaccessible_models_fail_without_committing_policy(service_factory):
    service, state, quota = service_factory()
    state["models_allowed"] = False
    result = await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    assert result["status"] == "FAILED"
    assert result["result_code"] == "model_not_allowed"
    assert result["before_values"] is None and result["after_values"] is None
    assert quota.version == 0
    assert quota.reasons == {"STORAGE_UNCERTAIN:request-1"}


@pytest.mark.parametrize("failure", [None, "block_policy", "install_policy", "finish_policy"])
async def test_real_redis_policy_recovery_preserves_storage_block(service_factory, real_quota, failure):  # noqa: F811
    quota = real_quota
    gate, _month, _models, blocks, *_ = quota.keys(running())
    await quota.redis.sadd(blocks, "STORAGE_UNCERTAIN:prior-month")

    class ResponseLoss:
        crashed = False

        def __getattr__(self, name):
            async def invoke(*args, **kwargs):
                await getattr(quota, name)(*args, **kwargs)
                if failure == name and not self.crashed:
                    self.crashed = True
                    raise TimeoutError("injected response loss after real Redis mutation")

            return invoke

    await quota.redis.hset(
        gate, mapping={"version:2": "1", "model:2": "1", "limit:2": "1000", "version": "3", "limit": "3000"}
    )
    service, state, _quota = service_factory(quota=ResponseLoss())
    with service.repository_scope() as repository:
        repository.session.add(
            DshUserPolicy(
                user_id=20,
                version=1,
                quota_sync_state="READY",
                model_id=2,
                monthly_token_limit=1000,
                enabled=1,
                updated_by=90,
            )
        )
    result = await service.update_policy(
        model_id=2, user_id=20, actor_user_id=90, request=request().model_copy(update={"expected_version": 1})
    )
    if failure:
        assert result["status"] == "PROCESSING"
        state["now"] += timedelta(seconds=31)
        result = await service.resume("a")
    assert result["status"] == "SUCCEEDED"
    assert result["after_values"]["version"] == 2
    assert await quota.redis.hget(gate, "version:2") == "2"
    assert await quota.redis.hget(gate, "limit") == "2100"
    assert await quota.redis.hget(gate, "limit:2") == "100"
    assert await quota.redis.hget(gate, "limit:5") == "1000"
    assert await quota.redis.hget(gate, "model:2") == "1"
    assert await quota.redis.hget(gate, "model:4") == "1"
    assert await quota.redis.smembers(blocks) == {"STORAGE_UNCERTAIN:prior-month"}


async def test_first_policy_creates_only_proven_empty_redis_gate(service_factory, real_quota):  # noqa: F811
    quota = real_quota
    keys = [key async for key in quota.redis.scan_iter(match=quota.prefix + "*")]
    if keys:
        await quota.redis.delete(*keys)
    service, _state, _ = service_factory(quota=quota)
    result = await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    assert result["status"] == "SUCCEEDED"
    gate, *_ = quota.keys(running())
    assert await quota.redis.hget(gate, "version") == "1"
    assert await quota.redis.hget(gate, "limit") == "100"
    assert await quota.redis.hget(gate, "limit:2") == "100"
    assert await quota.redis.hget(gate, "limit:5") is None


@pytest.mark.parametrize("denial", ["permission", "model", "dependency"])
async def test_production_callback_exceptions_close_only_definitive_rejections(service_factory, denial):
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from bisheng.common.errcode.dsh import DshModelNotAllowedError

    service, state, quota = service_factory(quota=QuotaDouble("block"))
    await service.update_policy(model_id=2, user_id=20, actor_user_id=90, request=request())
    state["now"] += timedelta(seconds=31)
    if denial == "permission":
        service.authorize = AsyncMock(side_effect=HTTPException(403, "Role removed"))
    else:
        service.validate_models = AsyncMock(
            side_effect=DshModelNotAllowedError() if denial == "model" else TimeoutError()
        )
    result = await service.resume("a")
    assert result["committed_at"] is None
    if denial == "dependency":
        assert result["status"] == "PROCESSING"
        assert quota.reasons == {"STORAGE_UNCERTAIN:request-1", "POLICY_SYNC:a"}
    else:
        assert result["status"] == "FAILED"
        assert result["result_code"] == ("permission_revoked" if denial == "permission" else "model_not_allowed")
        assert quota.reasons == {"STORAGE_UNCERTAIN:request-1"}
