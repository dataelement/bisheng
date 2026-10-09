"""Real SQL/Redis coverage for direct edits to inherited model authorization."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
from bisheng.dsh.domain.services.admin_policy import DshAdminService
from test.dsh.test_automatic_quota_recovery import connect
from test.dsh.test_policy_repository import sql_store  # noqa: F401
from test.dsh.test_quota_admission import quota, running  # noqa: F401
from test.dsh.test_subject_policy import subject_store, update  # noqa: F401


@pytest.mark.parametrize("committed_recovery", [False, True])
async def test_mixed_grants_save_and_recover_original_operation(sql_store, quota, subject_store, committed_recovery):  # noqa: F811
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        update(repository, "DEPARTMENT", 10, 100)
        update(repository, "ROLE", 41, 300)

    @contextmanager
    def scope():
        with Session(subject_store) as session, session.begin():
            yield DshPolicyRepository(session)

    clock = datetime(2026, 9, 15)
    service = DshAdminService(
        repository_scope=scope,
        quota=quota,
        allocate=AsyncMock(),
        authorize=AsyncMock(return_value=True),
        validate_models=AsyncMock(return_value=True),
        now=lambda: clock,
    )
    connect(quota, subject_store)
    gate, month, models, blocks, *_ = quota.keys(running())
    # Existing usage survives protocol migration and operation recovery.
    await quota.redis.hset(models, "7", "42")
    await quota.redis.hset(month, "used", "942")
    await quota.redis.hdel(gate, "policy_revision_schema")
    await quota.prepare(2, 20)

    for version, (enabled, limit, effective) in enumerate(
        [(True, 0, 300), (False, 500, 300), (True, 500, 500), (True, 50, 300)]
    ):
        request = DshUserPolicyInput(
            operation_id=f"mixed-{version}",
            expected_version=version,
            enabled=enabled,
            monthly_token_limit=limit,
        )
        if committed_recovery:
            with scope() as repository:
                repository.register_update(
                    operation_id=request.operation_id,
                    user_id=20,
                    actor_user_id=90,
                    expected_version=version,
                    model_id=7,
                    monthly_token_limit=limit,
                    enabled=enabled,
                )
                claimed = repository.operations.claim(request.operation_id, now=clock, lease_seconds=30)
                repository.commit_update(request.operation_id, claimed.lease_generation, now=clock)
            # Reproduce a committed operation plus a legacy mixed-version cache.
            await quota.redis.hdel(gate, "policy_revision_schema")
            clock += timedelta(seconds=31)
            result = await service.resume(request.operation_id)
        else:
            result = await service.update_policy(user_id=20, actor_user_id=90, model_id=7, request=request)
        assert result["status"] == "SUCCEEDED", result["result_code"]
        assert (await service.resume(request.operation_id))["status"] == "SUCCEEDED"
        with scope() as repository:
            direct = repository.get_model(20, 7)
            assert direct.version == version + 1
            assert direct.pending_operation_id is None
            snapshot = DshSubjectPolicyRepository(repository.session).effective(20)
        assert snapshot.monthly_token_limit == effective
        assert await quota.redis.hget(gate, "limit:7") == str(effective)
        assert await quota.redis.hget(gate, "version:7") == str(snapshot.rows[0].version)
        assert await quota.redis.hget(gate, "version") == str(snapshot.version)
        assert await quota.redis.hget(models, "7") == "42"
        assert await quota.redis.hget(month, "used") == "942"
        assert not await quota.redis.smembers(blocks)
