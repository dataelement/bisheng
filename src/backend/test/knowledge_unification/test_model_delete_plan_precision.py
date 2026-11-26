"""MySQL DATETIME(0) storage must not invalidate the original confirmation.

The actual MySQL counterexample is separately recorded by the native driver
probe. This SQLite storage trigger reproduces that database precision boundary
without changing a plan's verification oracle or requiring a service in CI.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanExpiredError
from test.knowledge_unification import test_model_delete_plan_repo as native

plan_tenant = native.plan_tenant
plans = native.plans
repository = native.repository
clock = native.clock


@pytest.mark.parametrize("microsecond", [1, 123456, 999999])
async def test_real_second_precision_storage_reloads_with_exact_signature_and_300_second_ttl(
    plans, repository, clock, microsecond
):
    clock[0] = datetime(2026, 11, 9, 10, 0, 0, microsecond)
    await plans.execute(text("""
        CREATE TRIGGER native_datetime_zero_precision AFTER INSERT ON knowledge_operation_plan
        BEGIN
          UPDATE knowledge_operation_plan
          SET expires_at = substr(NEW.expires_at, 1, 19)
          WHERE id = NEW.id;
        END
    """))
    confirmation = await native.create(repository, plans, clock)
    await plans.commit()
    plans.expunge_all()
    restored = await native.load(repository, plans, confirmation)
    assert restored.expires_at.microsecond == 0
    assert restored.expires_at - clock[0].replace(microsecond=0) == timedelta(seconds=300)
    clock[0] = clock[0].replace(microsecond=0) + timedelta(seconds=299)
    await native.load(repository, plans, confirmation)
    clock[0] += timedelta(seconds=1)
    with pytest.raises(KnowledgeOperationPlanExpiredError):
        await native.load(repository, plans, confirmation)
