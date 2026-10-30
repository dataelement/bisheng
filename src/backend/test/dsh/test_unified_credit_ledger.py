import pytest
from sqlmodel import Session

from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import CreditRuleInput, ModelVisibilityInput, PolicySubject
from bisheng.dsh.infrastructure.quota_redis import QuotaRejected
from test.dsh.test_automatic_quota_recovery import connect, erase, persist
from test.dsh.test_quota_admission import quota as quota
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


async def test_chat_and_work_models_consume_one_balance(quota):
    # Existing 900 tokens on model 4; a different model can spend the final 100.
    admitted = await quota.check_and_start(running(model=5), monthly_token_limit=1000)
    settled = terminal(admitted, 100)
    await quota.record_usage(settled, 1)
    for model in (4, 5, 6):
        with pytest.raises(QuotaRejected, match="quota_exceeded"):
            await quota.check_and_start(running(model=model), monthly_token_limit=1000)
    snapshot = await quota.read_usage(2, 20, "2026-09")
    assert snapshot["used"] == 1000
    assert snapshot["models"] == {"4": 900, "5": 100}


async def test_quota_edit_uses_existing_spend_and_settlement_is_idempotent(quota):
    event = await quota.check_and_start(running(model=4), monthly_token_limit=1000)
    settled = terminal(event, 50)
    await quota.record_usage(settled, 1)
    await quota.record_usage(settled, 1)
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 950
    with pytest.raises(QuotaRejected, match="quota_exceeded"):
        await quota.check_and_start(running(model=5), monthly_token_limit=940)
    assert (await quota.check_and_start(running(model=5), monthly_token_limit=2000)).status == "RUNNING"


async def test_weighted_usage_exhausts_shared_balance_once(quota):
    event = running(model=5).model_copy(update={"credit_rate": 125})
    admitted = await quota.check_and_start(event, monthly_token_limit=1000)
    settled = terminal(admitted, 80)
    await quota.record_usage(settled, 1)
    await quota.record_usage(settled, 1)
    assert settled.total_tokens == 80 and settled.billed_tokens == 100
    snapshot = await quota.read_usage(2, 20, "2026-09")
    assert snapshot["used"] == 1000
    assert snapshot["models"] == {"4": 900, "5": 100}
    with pytest.raises(QuotaRejected, match="quota_exceeded"):
        await quota.check_and_start(running(model=4), monthly_token_limit=1000)


async def test_rate_is_immutable_during_settlement(quota):
    event = running().model_copy(update={"credit_rate": 125})
    admitted = await quota.check_and_start(event, monthly_token_limit=1000)
    with pytest.raises(QuotaRejected):
        await quota.record_usage(terminal(admitted, 1).model_copy(update={"credit_rate": 100}), 1)
    await quota.record_usage(terminal(admitted, 1), 1)
    assert (await quota.read_usage(2, 20, "2026-09"))["used"] == 902


async def test_weighted_usage_survives_full_redis_loss(quota, store):
    with Session(store) as session, session.begin():
        repo = UnifiedPolicyRepository(session)
        repo.save_visibility(7, 20, ModelVisibilityInput(version=0, everyone=True, credit_multiplier="1.25"))
        repo.save_rule(PolicySubject(kind="USER", id=20), 20, CreditRuleInput(version=0, monthly_credits="0.1"))
    event = terminal(running(model=7).model_copy(update={"credit_rate": 125}), 80)
    persist(store, [event])
    await erase(quota)
    connect(quota, store)
    result = await quota.read_usage(2, 20, "2026-09")
    assert result["used"] == 100
    assert result["remaining"] == 99_900
