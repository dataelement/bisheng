"""Independent model-row ownership, revocation and exact quota counters."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.policy import DshPolicyRepository
from bisheng.dsh.domain.schemas.contracts import DshUserPolicyInput
from test.dsh.test_policy_service import service_factory, sql_store  # noqa: F401
from test.dsh.test_quota_admission import quota as real_quota  # noqa: F401
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal


def policy_request(operation, version, limit, enabled=True):
    return DshUserPolicyInput(
        operation_id=operation, expected_version=version, monthly_token_limit=limit, enabled=enabled
    )


async def test_distinct_model_updates_do_not_conflict_or_replace_each_other(service_factory, real_quota):  # noqa: F811
    service, _, _ = service_factory(quota=real_quota)
    service.validate_models = AsyncMock(return_value=True)
    with service.repository_scope() as repository:
        for model in (4, 5):
            repository.session.add(
                DshUserPolicy(
                    user_id=20,
                    model_id=model,
                    monthly_token_limit=1000,
                    enabled=1,
                    version=1,
                    quota_sync_state="READY",
                    updated_by=90,
                )
            )
    outcomes = await asyncio.gather(
        *[
            service.update_policy(
                user_id=20, actor_user_id=90, model_id=model, request=policy_request(f"model-{model}", 1, limit)
            )
            for model, limit in [(4, 1200), (5, 50)]
        ]
    )
    assert [outcome["status"] for outcome in outcomes] == ["SUCCEEDED", "SUCCEEDED"]
    with service.repository_scope() as repository:
        rows = repository.rows(20)
        assert [(row.model_id, row.monthly_token_limit, row.version) for row in rows] == [(4, 1200, 2), (5, 50, 2)]
    gate = real_quota.keys(running())[0]
    assert await real_quota.redis.hmget(gate, "version:4", "version:5", "limit:4", "limit:5") == [
        "2",
        "2",
        "1200",
        "50",
    ]
    request = running(4).model_copy(update={"policy_version": 2})
    await real_quota.check_and_start(request)
    await service.update_policy(
        user_id=20, actor_user_id=90, model_id=4, request=policy_request("revoke-4", 2, 0, enabled=False)
    )
    await real_quota.record_usage(terminal(request, amount=200), 1)
    usage = await real_quota.read_usage(2, 20, "2026-09")
    assert usage["models"] == {"4": 1100, "5": 0}
    assert usage["model_limits"] == {"5": 50}
    await real_quota.check_and_start(running(5).model_copy(update={"policy_version": 2}))
    # The revoked row keeps its monotonic version, so a pre-revocation retry cannot regrant it.
    with service.repository_scope() as repository:
        row = repository.get_model(20, 4)
        assert (row.enabled, row.version) == (0, 3)


async def test_a_sync_block_for_one_model_does_not_block_another(real_quota):  # noqa: F811
    await real_quota.block_policy(
        2, 20, model_id=4, operation_id="four", lease_generation=1, epoch=1, expected_version=1
    )
    await real_quota.check_and_start(running(5))
    from bisheng.dsh.infrastructure.quota_redis import QuotaRejected

    with pytest.raises(QuotaRejected, match="blocked"):
        await real_quota.check_and_start(running(4))


def test_two_models_have_independent_sql_intents_and_database_uniqueness(sql_store):  # noqa: F811
    from bisheng.common.errcode.dsh import DshOperationInProgressError

    with Session(sql_store) as session, session.begin():
        repository = DshPolicyRepository(session)
        for model in (4, 5):
            repository.register_update(
                operation_id=f"grant-{model}",
                user_id=20,
                actor_user_id=90,
                expected_version=0,
                model_id=model,
                monthly_token_limit=100,
                enabled=True,
            )
        assert len(repository.rows(20)) == 2
        with pytest.raises(DshOperationInProgressError):
            repository.register_update(
                operation_id="another-4",
                user_id=20,
                actor_user_id=90,
                expected_version=0,
                model_id=4,
                monthly_token_limit=200,
                enabled=True,
            )


def test_mysql_model_lookup_uses_covering_index(sql_store):  # noqa: F811
    from sqlalchemy import select

    if sql_store.dialect.name != "mysql":
        pytest.skip("MySQL optimizer evidence requires the isolated MySQL store")
    with sql_store.begin() as connection:
        connection.execute(
            DshUserPolicy.__table__.insert(),
            [
                {
                    "tenant_id": 2,
                    "user_id": user,
                    "model_id": 7 if user % 100 == 0 else 8,
                    "enabled": 1,
                    "monthly_token_limit": 100,
                    "updated_by": 90,
                }
                for user in range(1000, 2000)
            ],
        )
        query = (
            select(DshUserPolicy.user_id)
            .where(
                DshUserPolicy.tenant_id == 2,
                DshUserPolicy.model_id == 7,
                DshUserPolicy.enabled == 1,
                DshUserPolicy.user_id > 0,
            )
            .order_by(DshUserPolicy.user_id)
            .limit(20)
        )
        compiled = str(query.compile(dialect=sql_store.dialect, compile_kwargs={"literal_binds": True}))
        plan = connection.exec_driver_sql("EXPLAIN " + compiled).mappings().one()
        assert plan["key"] == "ix_dsh_policy_model_users"
        assert "Using index" in plan["Extra"]
        assert list(connection.execute(query).scalars()) == list(range(1000, 2000, 100))
