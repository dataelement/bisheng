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
from bisheng.points.domain.constants.notify_templates import format_deduct_notify_reason
from bisheng.points.domain.constants.rule_display_name import resolve_point_rule_display_name
from bisheng.points.domain.models import PointPendingDeduct
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.points.domain.services.points_notify_service import (
    PointsNotifyService,
    build_points_notify_service,
)

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

    def _has_usable_notify(self) -> bool:
        """已注入 MessageService 或单测 mock 时可直接发；裸服务必须走工厂。"""
        if self.notify is None:
            return False
        if not isinstance(self.notify, PointsNotifyService):
            return True
        return self.notify.message_service is not None

    async def _notify_admin_deduct(
        self,
        *,
        user_id: int,
        delta: int,
        rule_name: str | None,
        remark: str | None,
        log_key: str,
    ) -> None:
        """账本提交后发扣分站内信；失败只记日志，不回滚积分。"""
        reason = format_deduct_notify_reason(rule_name=rule_name, remark=remark)
        try:
            if self._has_usable_notify():
                await self.notify.notify(
                    user_id=user_id,
                    template_code="deduct_admin",
                    delta=delta,
                    reason=reason,
                )
                return
            async with get_async_db_session() as session:
                notify = await build_points_notify_service(session)
                await notify.notify(
                    user_id=user_id,
                    template_code="deduct_admin",
                    delta=delta,
                    reason=reason,
                )
                await session.commit()
        except Exception:
            logger.exception("points.pending_deduct.notify_failed user_id=%s key=%s", user_id, log_key)

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
        resolved_score: int | None = None,
        scope_tier: str | None = None,
        idempotency_key: str | None = None,
    ) -> DeductAttemptResult:
        """尝试按规则扣分; 失败则写入补扣队列 (删除已成功时的兜底).

        Args:
            tenant_id: 租户.
            user_id: 被扣人.
            rule_code: 扣减规则编码.
            biz_type: 业务类型.
            biz_id: 业务主键.
            operator_id: 操作者.
            remark: 备注.
            resolved_score: 知识文档确认时已经算出的扣分绝对值. 空则读规则的单一 score.
            scope_tier: 知识文档档位. 专家问答不传.
            idempotency_key: 调用方指定的幂等键. 空则按规则和业务主键生成.

        Returns:
            是否入账, 是否进入补扣, 以及原因.
        """
        code = rule_code.strip().upper()
        key = idempotency_key or stable_deduct_idempotency_key(code, biz_type, biz_id)
        try:
            async with get_async_db_session() as session:
                repo = PointsRepository(session)
                ledger = PointsLedgerService(repo)
                rule = await repo.get_rule(tenant_id, code)
                if rule is None or rule.rule_type != "deduct" or rule.status != "enabled":
                    raise PointsRuleNotFoundError()
                if resolved_score is not None:
                    score = abs(int(resolved_score))
                else:
                    score = abs(int((rule.score_expr or {}).get("score", 0)))
                if score == 0:
                    raise PointsInvalidAdjustError(msg="扣减规则分值为 0")
                rule_name = resolve_point_rule_display_name(rule)
                result = await ledger.deduct(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    delta=-score,
                    rule_code=rule.rule_code,
                    title=rule_name,
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
                    scope_tier=scope_tier,
                    score_snapshot=score,
                )
                return DeductAttemptResult(applied=False, pending=True, reason="ledger_empty")
            await self._notify_admin_deduct(
                user_id=user_id,
                delta=score,
                rule_name=rule_name,
                remark=remark,
                log_key=key,
            )
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
                scope_tier=scope_tier,
                score_snapshot=resolved_score,
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
        scope_tier: str | None = None,
        score_snapshot: int | None = None,
    ) -> None:
        """写入补扣行; 已存在则只更新错误, 不覆盖已记下的金额快照.

        Args:
            tenant_id: 租户.
            user_id: 被扣人.
            rule_code: 扣减规则编码.
            biz_type: 业务类型.
            biz_id: 业务主键.
            idempotency_key: 与正式流水相同的幂等键.
            operator_id: 操作者.
            remark: 备注.
            last_error: 本次失败原因.
            scope_tier: 知识文档档位.
            score_snapshot: 确认时的扣分绝对值.
        """
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
                            scope_tier=scope_tier,
                            score_snapshot=score_snapshot,
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
            if row.score_snapshot is not None:
                score = abs(int(row.score_snapshot))
            else:
                score = abs(int((rule.score_expr or {}).get("score", 0)))
            if score == 0:
                raise PointsInvalidAdjustError(msg="扣减规则分值为 0")
            result = await ledger.deduct(
                tenant_id=int(row.tenant_id),
                user_id=int(row.user_id),
                delta=-score,
                rule_code=rule.rule_code,
                title=resolve_point_rule_display_name(rule),
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
                await self._notify_admin_deduct(
                    user_id=int(row.user_id),
                    delta=score,
                    rule_name=resolve_point_rule_display_name(rule),
                    remark=row.remark,
                    log_key=row.idempotency_key,
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
