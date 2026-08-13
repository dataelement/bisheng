"""违规删除后的稳定幂等扣分与补扣队列。

主路径：先删内容，再尝试扣分；扣分失败写入 ``point_pending_deduct``，
由 Beat 重试。幂等键 ``deduct:{rule}:{biz_type}:{biz_id}`` 保证不双扣。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from bisheng.common.errcode.points import PointsInvalidAdjustError, PointsRuleNotFoundError
from bisheng.core.database import get_async_db_session
from bisheng.points.domain.models import PointPendingDeduct
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.points.domain.services.points_notify_service import PointsNotifyService

logger = logging.getLogger(__name__)

MAX_RETRIES = 10


@dataclass(frozen=True)
class DeductAttemptResult:
    """单次扣分尝试结果。"""

    applied: bool
    pending: bool
    replayed: bool = False
    reason: str | None = None


def stable_deduct_idempotency_key(rule_code: str, biz_type: str, biz_id: str) -> str:
    """内容级稳定幂等键：同一违规内容只扣一次。"""
    return f"deduct:{rule_code.strip().upper()}:{biz_type}:{biz_id}"


class PointsPendingDeductService:
    """封装「立即扣分或入补扣队列」与定时 drain。"""

    def __init__(self, notify: PointsNotifyService | None = None):
        self.notify = notify or PointsNotifyService()

    async def deduct_or_enqueue(
        self,
        *,
        tenant_id: int,
        user_id: int,
        rule_code: str,
        biz_type: str,
        biz_id: str,
        operator_id: int,
        remark: str | None = None,
    ) -> DeductAttemptResult:
        """尝试按 R* 扣分；失败则写入补扣队列（删除已成功时的兜底）。"""
        code = rule_code.strip().upper()
        key = stable_deduct_idempotency_key(code, biz_type, biz_id)
        try:
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                ledger = PointsLedgerService(repo)
                rule = await repo.get_rule(tenant_id, code)
                if rule is None or rule.rule_type != "deduct" or rule.status != "enabled":
                    raise PointsRuleNotFoundError()
                score = abs(int((rule.score_expr or {}).get("score", 0)))
                if score == 0:
                    raise PointsInvalidAdjustError(msg="扣减规则分值为 0")
                result = await ledger.deduct(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    delta=-score,
                    rule_code=rule.rule_code,
                    title=rule.name or rule.rule_code,
                    idempotency_key=key,
                    operator_id=operator_id,
                    remark=remark,
                    biz_type=biz_type,
                    biz_id=biz_id,
                )
                await session.commit()
            if result.replayed:
                return DeductAttemptResult(applied=True, pending=False, replayed=True)
            if result.log_id is None:
                await self._enqueue(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    rule_code=code,
                    biz_type=biz_type,
                    biz_id=biz_id,
                    idempotency_key=key,
                    operator_id=operator_id,
                    remark=remark,
                    last_error="ledger_returned_no_log",
                )
                return DeductAttemptResult(applied=False, pending=True, reason="ledger_empty")
            try:
                await self.notify.notify(
                    user_id=user_id,
                    template_code="deduct_admin",
                    delta=score,
                    reason=format_deduct_notify_reason(rule_name=rule.name, remark=remark),
                )
            except Exception:
                logger.exception("points.pending_deduct.notify_failed user_id=%s key=%s", user_id, key)
            return DeductAttemptResult(applied=True, pending=False)
        except Exception as exc:
            logger.exception(
                "points.pending_deduct.immediate_failed key=%s user_id=%s",
                key,
                user_id,
            )
            await self._enqueue(
                tenant_id=tenant_id,
                user_id=user_id,
                rule_code=code,
                biz_type=biz_type,
                biz_id=biz_id,
                idempotency_key=key,
                operator_id=operator_id,
                remark=remark,
                last_error=str(exc)[:1000],
            )
            return DeductAttemptResult(applied=False, pending=True, reason=type(exc).__name__)

    async def drain(self, *, limit: int = 100) -> dict:
        """重试到期补扣；成功标 done，超限标 dead。"""
        from bisheng.core.context.tenant import bypass_tenant_filter

        processed = done = failed = dead = 0
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                rows = await repo.list_due_pending_deducts(limit=limit)
                for row in rows:
                    processed += 1
                    outcome = await self._process_one(repo, row)
                    if outcome == "done":
                        done += 1
                    elif outcome == "dead":
                        dead += 1
                    else:
                        failed += 1
                await session.commit()
        result = {"processed": processed, "done": done, "failed": failed, "dead": dead}
        logger.info("points.pending_deduct.drain_done %s", result)
        return result

    async def _enqueue(
        self,
        *,
        tenant_id: int,
        user_id: int,
        rule_code: str,
        biz_type: str,
        biz_id: str,
        idempotency_key: str,
        operator_id: int,
        remark: str | None,
        last_error: str | None,
    ) -> None:
        """写入补扣行；已存在则仅更新 last_error。"""
        try:
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                existing = await repo.get_pending_deduct_by_key(tenant_id, idempotency_key)
                if existing is not None:
                    if existing.status == "done":
                        await session.commit()
                        return
                    existing.last_error = last_error
                    existing.status = "pending"
                    existing.next_retry_at = datetime.utcnow() + timedelta(seconds=30)
                    await repo.save_pending_deduct(existing)
                else:
                    await repo.upsert_pending_deduct(
                        PointPendingDeduct(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            rule_code=rule_code,
                            biz_type=biz_type,
                            biz_id=biz_id,
                            idempotency_key=idempotency_key,
                            operator_id=operator_id,
                            remark=remark,
                            status="pending",
                            last_error=last_error,
                            next_retry_at=datetime.utcnow() + timedelta(seconds=30),
                        )
                    )
                await session.commit()
        except Exception:
            logger.exception("points.pending_deduct.enqueue_failed key=%s", idempotency_key)

    async def _process_one(self, repo: PointsRepository, row: PointPendingDeduct) -> str:
        """处理单条补扣。"""
        ledger = PointsLedgerService(repo)
        try:
            rule = await repo.get_rule(int(row.tenant_id), row.rule_code)
            if rule is None or rule.rule_type != "deduct" or rule.status != "enabled":
                raise PointsRuleNotFoundError()
            score = abs(int((rule.score_expr or {}).get("score", 0)))
            if score == 0:
                raise PointsInvalidAdjustError(msg="扣减规则分值为 0")
            result = await ledger.deduct(
                tenant_id=int(row.tenant_id),
                user_id=int(row.user_id),
                delta=-score,
                rule_code=rule.rule_code,
                title=rule.name or rule.rule_code,
                idempotency_key=row.idempotency_key,
                operator_id=int(row.operator_id or 0),
                remark=row.remark,
                biz_type=row.biz_type,
                biz_id=row.biz_id,
            )
            row.status = "done"
            row.last_error = None
            row.next_retry_at = None
            await repo.save_pending_deduct(row)
            if not result.replayed and result.log_id is not None:
                try:
                    await self.notify.notify(
                        user_id=int(row.user_id),
                        template_code="deduct_admin",
                        delta=score,
                        reason=format_deduct_notify_reason(rule_name=rule.name, remark=row.remark),
                    )
                except Exception:
                    logger.exception(
                        "points.pending_deduct.drain_notify_failed id=%s",
                        row.id,
                    )
            return "done"
        except Exception as exc:
            row.retry_count = int(row.retry_count or 0) + 1
            row.last_error = str(exc)[:1000]
            if row.retry_count >= MAX_RETRIES:
                row.status = "dead"
                row.next_retry_at = None
                await repo.save_pending_deduct(row)
                logger.error(
                    "points.pending_deduct.dead id=%s key=%s err=%s",
                    row.id,
                    row.idempotency_key,
                    exc,
                )
                return "dead"
            backoff = min(3600, 30 * (2 ** max(row.retry_count - 1, 0)))
            row.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff)
            await repo.save_pending_deduct(row)
            logger.warning(
                "points.pending_deduct.retry id=%s retry=%s err=%s",
                row.id,
                row.retry_count,
                exc,
            )
            return "failed"
