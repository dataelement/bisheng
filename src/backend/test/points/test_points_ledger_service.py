"""积分账本核心规则测试。"""

from types import SimpleNamespace

from bisheng.points.domain.services.points_ledger_service import PointsLedgerService


class FakeRepository:
    """以最小内存状态模拟账本仓储。"""

    def __init__(self):
        self.account = SimpleNamespace(balance=0, version=0, lifetime_earned=0, lifetime_deducted=0)
        self.logs = {}
        self.today = 0

    async def lock_or_create_account(self, *_):
        return self.account

    async def get_log_by_idempotency(self, _, key):
        return self.logs.get(key)

    async def sum_earn_today(self, *_):
        if self.today:
            return self.today
        return sum(int(log.delta) for log in self.logs.values() if getattr(log, "direction", "earn") == "earn")

    async def append_log(self, log):
        log.id = len(self.logs) + 1
        self.logs[log.idempotency_key] = log
        return log

    async def add_outbox(self, *_):
        pass


async def test_award_skips_entire_delta_when_cap_remaining_is_insufficient():
    repo = FakeRepository()
    repo.today = 8
    result = await PointsLedgerService(repo).award(
        tenant_id=1, user_id=1, delta=3, title="测试", rule_code="G1", idempotency_key="a", daily_cap=10
    )
    assert result.skipped_cap and result.applied_delta == 0 and repo.account.balance == 0


async def test_serial_awards_in_same_session_stop_at_daily_cap():
    """同一账户连续入账时按已写入流水累计，第三笔 30 分应被 60 上限挡住。"""
    repo = FakeRepository()
    service = PointsLedgerService(repo)
    first = await service.award(
        tenant_id=1, user_id=1, delta=30, title="G1", rule_code="G1", idempotency_key="a", daily_cap=60
    )
    second = await service.award(
        tenant_id=1, user_id=1, delta=30, title="G1", rule_code="G1", idempotency_key="b", daily_cap=60
    )
    third = await service.award(
        tenant_id=1, user_id=1, delta=30, title="G1", rule_code="G1", idempotency_key="c", daily_cap=60
    )
    assert first.applied_delta == 30 and second.applied_delta == 30
    assert third.skipped_cap and repo.account.balance == 60


async def test_award_is_idempotent():
    repo = FakeRepository()
    service = PointsLedgerService(repo)
    first = await service.award(tenant_id=1, user_id=1, delta=3, title="测试", rule_code="G1", idempotency_key="a")
    replay = await service.award(tenant_id=1, user_id=1, delta=3, title="测试", rule_code="G1", idempotency_key="a")
    assert first.balance == replay.balance == 3 and replay.replayed


async def test_deduct_allows_negative_balance():
    repo = FakeRepository()
    result = await PointsLedgerService(repo).deduct(
        tenant_id=1, user_id=1, delta=-100, title="违规", rule_code="R1", idempotency_key="d", operator_id=2
    )
    assert result.balance == -100
