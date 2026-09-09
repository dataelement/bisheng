"""积分账本服务：同事务维护余额缓存和不可变流水。"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from bisheng.common.errcode.points import PointsInvalidAdjustError
from bisheng.points.domain.models import UserPointLog

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class LedgerResult:
    """记账结果；跳过日上限时 log_id 为空。"""

    applied_delta: int
    balance: int
    log_id: int | None = None
    replayed: bool = False
    skipped_cap: bool = False


class PointsLedgerService:
    """执行账户锁定、幂等、日上限和流水追加。"""

    def __init__(self, repository, notify_service=None):
        self.repository = repository
        self.notify_service = notify_service

    async def award(
        self,
        *,
        tenant_id: int,
        user_id: int,
        delta: int,
        title: str,
        rule_code: str,
        idempotency_key: str,
        daily_cap: int | None = None,
        source: str = "auto",
        **kwargs,
    ) -> LedgerResult:
        """自动发分；剩余额度不足整笔时跳过，不做部分截断。"""
        if delta <= 0:
            raise PointsInvalidAdjustError(msg="发放积分必须为正数")
        return await self._write(
            tenant_id=tenant_id,
            user_id=user_id,
            delta=delta,
            title=title,
            rule_code=rule_code,
            idempotency_key=idempotency_key,
            daily_cap=daily_cap,
            source=source,
            **kwargs,
        )

    async def adjust(
        self,
        *,
        tenant_id: int,
        user_id: int,
        delta: int,
        title: str = "管理员调整积分",
        idempotency_key: str,
        operator_id: int,
        remark: str,
        **kwargs,
    ) -> LedgerResult:
        """管理员自由调分；余额允许变为负数。"""
        if not isinstance(delta, int) or delta == 0 or abs(delta) > 10000 or not 5 <= len(remark.strip()) <= 100:
            raise PointsInvalidAdjustError()
        return await self._write(
            tenant_id=tenant_id,
            user_id=user_id,
            delta=delta,
            title=title,
            rule_code="MANUAL",
            idempotency_key=idempotency_key,
            source="manual_adjust",
            operator_id=operator_id,
            remark=remark,
            **kwargs,
        )

    async def deduct(
        self,
        *,
        tenant_id: int,
        user_id: int,
        delta: int,
        title: str,
        rule_code: str,
        idempotency_key: str,
        operator_id: int,
        remark: str | None = None,
        **kwargs,
    ) -> LedgerResult:
        """按 R 规则扣分；负余额是合法业务状态。"""
        if delta >= 0:
            raise PointsInvalidAdjustError(msg="扣减积分必须为负数")
        return await self._write(
            tenant_id=tenant_id,
            user_id=user_id,
            delta=delta,
            title=title,
            rule_code=rule_code,
            idempotency_key=idempotency_key,
            source="manual_deduct",
            operator_id=operator_id,
            remark=remark,
            **kwargs,
        )

    async def _write(
        self,
        *,
        tenant_id: int,
        user_id: int,
        delta: int,
        title: str,
        rule_code: str,
        idempotency_key: str,
        source: str,
        daily_cap: int | None = None,
        operator_id: int | None = None,
        remark: str | None = None,
        biz_type: str | None = None,
        biz_id: str | None = None,
        beneficiary_role: str | None = None,
    ) -> LedgerResult:
        """在调用方事务内写入一笔账本记录并建立 outbox。"""
        # 先锁账户再读限额/流水：同用户并发任务在行锁上排队，后到者看到已提交的当日合计。
        account = await self.repository.lock_or_create_account(tenant_id, user_id)
        existing = await self.repository.get_log_by_idempotency(tenant_id, idempotency_key)
        if existing:
            return LedgerResult(existing.delta, existing.balance_after, existing.id, replayed=True)
        if delta > 0 and daily_cap is not None:
            now = datetime.now(SHANGHAI)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
            earned = await self.repository.sum_earn_today(tenant_id, user_id, rule_code, day_start)
            # 产品约定：不足本次 delta 时整笔跳过，避免用户因并发得到部分奖励。
            if daily_cap - earned < delta:
                return LedgerResult(0, account.balance, skipped_cap=True)
        balance = account.balance + delta
        account.balance = balance
        account.version += 1
        # MySQL 严格模式下 ORM 传 None 不会回落到 server_default，需显式写入业务时间。
        occurred_at = datetime.now(SHANGHAI).replace(tzinfo=None)
        if delta > 0:
            account.lifetime_earned += delta
            # 仅获得刷新；扣分不改，供首页榜同分「最后一次获得更早优先」。
            account.last_earned_at = occurred_at
        else:
            account.lifetime_deducted += -delta
        log = await self.repository.append_log(
            UserPointLog(
                tenant_id=tenant_id,
                user_id=user_id,
                delta=delta,
                balance_after=balance,
                direction="earn" if delta > 0 else "deduct",
                rule_code=rule_code,
                title=title,
                source=source,
                biz_type=biz_type,
                biz_id=biz_id,
                idempotency_key=idempotency_key,
                operator_id=operator_id,
                remark=remark,
                score_snapshot=abs(delta),
                beneficiary_role=beneficiary_role,
                occurred_at=occurred_at,
            )
        )
        await self.repository.add_outbox(tenant_id, int(log.id), {"user_id": user_id, "delta": delta, "log_id": log.id})
        return LedgerResult(delta, balance, log.id)
