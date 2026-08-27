"""业务侧自动发分门面：解析规则、豁免与受益人后调用账本。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from bisheng.points.domain.constants.rule_display_name import resolve_point_rule_display_name
from bisheng.points.domain.constants.space_level_rules import earn_rule_for_space_level
from bisheng.points.domain.services.points_ledger_service import LedgerResult, PointsLedgerService

logger = logging.getLogger(__name__)

IsSuperAdminFn = Callable[[int], Awaitable[bool]]


@dataclass(frozen=True)
class SpaceFileReadyEvent:
    """文件成功进入目标空间（直传或发布审批通过）后的发分上下文。"""

    tenant_id: int
    space_id: int
    space_level: str
    file_id: int
    uploader_id: int
    publisher_id: int | None = None
    is_favorite_space: bool = False
    # 目标库 OpenFGA owner∪manager（含创建人兜底）；P7=B 只看受益人是否在此集合。
    space_manager_ids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class DocumentSharedEvent:
    """库间 SHARE 审批通过后的发分上下文（G7）。"""

    tenant_id: int
    share_entry_id: int
    uploader_id: int
    sharer_id: int
    # 源库与目标库的 OpenFGA owner∪manager 并集（含创建人兜底）。
    related_manager_ids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class FavoriteChangedEvent:
    """文档收藏人数变化后的 G3 阶梯发分上下文。"""

    tenant_id: int
    file_id: int
    uploader_id: int
    unique_favoriter_count: int
    space_manager_ids: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AnswerAdoptedEvent:
    """问答答案被采纳后的 G4 发分上下文。

    同题同回答者只发一次（幂等键含 question_id + answerer_id）。
    """

    tenant_id: int
    question_id: int
    answer_id: int
    answerer_id: int


@dataclass
class AwardOutcome:
    """门面调用结果；主业务只关心是否抛异常（不应抛）。"""

    skipped: bool = True
    reason: str | None = None
    result: LedgerResult | None = None
    # 入账成功后供 hooks 发站内信；skip / 重放时保持空。
    notify_user_id: int | None = None
    rule_code: str | None = None
    rule_name: str | None = None
    notify_extra: dict | None = None

    @property
    def should_notify(self) -> bool:
        """是否应在账本 commit 后发送积分变动站内信。"""
        if self.skipped or self.notify_user_id is None or self.result is None:
            return False
        if self.result.replayed or self.result.skipped_cap:
            return False
        return int(self.result.applied_delta) > 0

    @staticmethod
    def success(
        *,
        result: LedgerResult,
        user_id: int,
        rule_code: str,
        rule_name: str | None,
        notify_extra: dict | None = None,
    ) -> AwardOutcome:
        """构造可通知的成功入账结果。"""
        return AwardOutcome(
            skipped=False,
            result=result,
            notify_user_id=int(user_id),
            rule_code=rule_code,
            rule_name=rule_name or rule_code,
            notify_extra=notify_extra,
        )


class PointsAwardFacade:
    """供 knowledge / approval / qa_expert 调用的薄门面。

    任何内部失败只记日志，不向外抛出，避免拖垮主业务（AC-11）。
    """

    def __init__(
        self,
        repository,
        ledger: PointsLedgerService,
        *,
        enabled: bool | None = None,
        is_platform_super_admin: IsSuperAdminFn | None = None,
    ):
        self.repository = repository
        self.ledger = ledger
        self._enabled_override = enabled
        self._is_platform_super_admin = is_platform_super_admin or _always_false

    def _is_enabled(self) -> bool:
        """读取 points.enabled；构造时可注入覆盖值便于单测。"""
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        try:
            # 运行时配置入口在 ConfigService，而非 settings.Settings 模块级单例。
            from bisheng.common.services.config_service import settings

            return bool(getattr(getattr(settings, "points", None), "enabled", False))
        except Exception:
            return False

    async def on_space_file_ready(self, event: SpaceFileReadyEvent) -> AwardOutcome:
        """入库类自动发分（G1/G2/G5/G6）。"""
        return await self._safe("on_space_file_ready", self._award_space_file, event)

    async def on_document_shared(self, event: DocumentSharedEvent) -> AwardOutcome:
        """库间分享发分（G7）；外链分享不得调用本方法。"""
        return await self._safe("on_document_shared", self._award_document_shared, event)

    async def on_favorite_changed(self, event: FavoriteChangedEvent) -> AwardOutcome:
        """收藏阶梯补差价（G3）。"""
        return await self._safe("on_favorite_changed", self._award_favorite_tier, event)

    async def on_answer_adopted(self, event: AnswerAdoptedEvent) -> AwardOutcome:
        """问答采纳发分（G4）。"""
        return await self._safe("on_answer_adopted", self._award_answer_adopted, event)

    async def _safe(self, op: str, fn, event) -> AwardOutcome:
        """统一吞异常，保证主路径成功。"""
        try:
            if not self._is_enabled():
                return AwardOutcome(skipped=True, reason="points_disabled")
            return await fn(event)
        except Exception:
            logger.exception("points.award.rejected op=%s event=%s", op, event)
            return AwardOutcome(skipped=True, reason="error")

    async def _award_space_file(self, event: SpaceFileReadyEvent) -> AwardOutcome:
        if event.is_favorite_space:
            return AwardOutcome(skipped=True, reason="favorite_space")
        rule_code = earn_rule_for_space_level(event.space_level)
        if rule_code is None:
            return AwardOutcome(skipped=True, reason="personal_or_unmapped_level")
        rule = await self.repository.get_rule(event.tenant_id, rule_code)
        if not rule or rule.status != "enabled" or rule.rule_type != "earn":
            logger.info("points.award.rejected reason=rule_disabled code=%s", rule_code)
            return AwardOutcome(skipped=True, reason="rule_disabled")
        payee, role = self._resolve_beneficiary(
            rule.beneficiary,
            uploader_id=event.uploader_id,
            publisher_id=event.publisher_id,
        )
        if payee is None:
            return AwardOutcome(skipped=True, reason="beneficiary_unresolved")
        skip = await self._should_skip_payee(payee, event.space_manager_ids)
        if skip:
            return AwardOutcome(skipped=True, reason=skip)
        score = _fixed_score(rule.score_expr)
        if score <= 0:
            return AwardOutcome(skipped=True, reason="invalid_score")
        key = f"earn:{rule_code}:{event.file_id}:{event.space_id}"
        result = await self.ledger.award(
            tenant_id=event.tenant_id,
            user_id=payee,
            delta=score,
            title=resolve_point_rule_display_name(rule),
            rule_code=rule_code,
            idempotency_key=key,
            daily_cap=rule.daily_cap,
            biz_type="space_file",
            biz_id=str(event.file_id),
            beneficiary_role=role,
        )
        if result.skipped_cap:
            logger.info("points.award.rejected reason=daily_cap code=%s key=%s", rule_code, key)
            return AwardOutcome(skipped=True, reason="daily_cap", result=result)
        return AwardOutcome.success(
            result=result,
            user_id=payee,
            rule_code=rule_code,
            rule_name=resolve_point_rule_display_name(rule),
        )

    async def _award_document_shared(self, event: DocumentSharedEvent) -> AwardOutcome:
        rule = await self.repository.get_rule(event.tenant_id, "G7")
        if not rule or rule.status != "enabled" or rule.rule_type != "earn":
            return AwardOutcome(skipped=True, reason="rule_disabled")
        payee, role = self._resolve_beneficiary(
            rule.beneficiary,
            uploader_id=event.uploader_id,
            sharer_id=event.sharer_id,
        )
        if payee is None:
            return AwardOutcome(skipped=True, reason="beneficiary_unresolved")
        skip = await self._should_skip_payee(payee, event.related_manager_ids)
        if skip:
            return AwardOutcome(skipped=True, reason=skip)
        score = _fixed_score(rule.score_expr)
        if score <= 0:
            return AwardOutcome(skipped=True, reason="invalid_score")
        key = f"earn:G7:{event.share_entry_id}"
        result = await self.ledger.award(
            tenant_id=event.tenant_id,
            user_id=payee,
            delta=score,
            title=resolve_point_rule_display_name(rule),
            rule_code="G7",
            idempotency_key=key,
            daily_cap=rule.daily_cap,
            biz_type="share_entry",
            biz_id=str(event.share_entry_id),
            beneficiary_role=role,
        )
        if result.skipped_cap:
            return AwardOutcome(skipped=True, reason="daily_cap", result=result)
        return AwardOutcome.success(
            result=result,
            user_id=payee,
            rule_code="G7",
            rule_name=resolve_point_rule_display_name(rule),
        )

    async def _award_favorite_tier(self, event: FavoriteChangedEvent) -> AwardOutcome:
        rule = await self.repository.get_rule(event.tenant_id, "G3")
        if not rule or rule.status != "enabled" or rule.rule_type != "earn":
            return AwardOutcome(skipped=True, reason="rule_disabled")
        payee = event.uploader_id
        skip = await self._should_skip_payee(payee, event.space_manager_ids)
        if skip:
            return AwardOutcome(skipped=True, reason=skip)
        s_target, highest_tier = _tier_target(rule.score_expr, event.unique_favoriter_count)
        # 先锁账户再读档位，避免并发收藏按过期进度各自补差价而超发。
        await self.repository.lock_or_create_account(event.tenant_id, payee)
        prior = await self.repository.get_favorite_tier_award(event.tenant_id, event.file_id, for_update=True)
        s_done = int(prior.points_granted_total) if prior else 0
        if s_target <= s_done:
            return AwardOutcome(skipped=True, reason="tier_already_granted")
        delta = s_target - s_done
        key = f"earn:G3:{event.file_id}:{s_target}"
        result = await self.ledger.award(
            tenant_id=event.tenant_id,
            user_id=payee,
            delta=delta,
            title=resolve_point_rule_display_name(rule),
            rule_code="G3",
            idempotency_key=key,
            daily_cap=rule.daily_cap,
            biz_type="favorite_tier",
            biz_id=str(event.file_id),
            beneficiary_role="uploader",
        )
        if result.skipped_cap:
            return AwardOutcome(skipped=True, reason="daily_cap", result=result)
        if result.applied_delta > 0 or result.replayed:
            await self.repository.upsert_favorite_tier_award(
                event.tenant_id,
                event.file_id,
                highest_tier=highest_tier,
                points_granted_total=s_target,
            )
        return AwardOutcome.success(
            result=result,
            user_id=payee,
            rule_code="G3",
            rule_name=resolve_point_rule_display_name(rule),
            notify_extra={"favorite_count": int(event.unique_favoriter_count)},
        )

    async def _award_answer_adopted(self, event: AnswerAdoptedEvent) -> AwardOutcome:
        rule = await self.repository.get_rule(event.tenant_id, "G4")
        if not rule or rule.status != "enabled" or rule.rule_type != "earn":
            return AwardOutcome(skipped=True, reason="rule_disabled")
        payee = event.answerer_id
        if await self._is_platform_super_admin(payee):
            return AwardOutcome(skipped=True, reason="super_admin")
        score = _fixed_score(rule.score_expr)
        if score <= 0:
            return AwardOutcome(skipped=True, reason="invalid_score")
        # 同题同回答者只入账一次；同题他人采纳仍各自计分。
        key = f"earn:G4:{event.question_id}:{payee}"
        result = await self.ledger.award(
            tenant_id=event.tenant_id,
            user_id=payee,
            delta=score,
            title=resolve_point_rule_display_name(rule),
            rule_code="G4",
            idempotency_key=key,
            daily_cap=rule.daily_cap,
            biz_type="question",
            biz_id=str(event.question_id),
            beneficiary_role="answerer",
        )
        if result.skipped_cap:
            return AwardOutcome(skipped=True, reason="daily_cap", result=result)
        if result.replayed:
            return AwardOutcome(skipped=True, reason="already_awarded_for_question", result=result)
        return AwardOutcome.success(
            result=result,
            user_id=payee,
            rule_code="G4",
            rule_name=resolve_point_rule_display_name(rule),
        )

    async def _should_skip_payee(self, payee: int, manager_ids: frozenset[int]) -> str | None:
        """P7=B：受益人是相关库 OpenFGA owner/manager（或创建人兜底），或平台超管 → skip。"""
        if payee in manager_ids:
            return "space_manager_payee"
        if await self._is_platform_super_admin(payee):
            return "super_admin"
        return None

    @staticmethod
    def _resolve_beneficiary(
        beneficiary: str | None,
        *,
        uploader_id: int | None = None,
        publisher_id: int | None = None,
        sharer_id: int | None = None,
        answerer_id: int | None = None,
    ) -> tuple[int | None, str | None]:
        """按规则 beneficiary 解析唯一入账用户。

        发布人不得回退成上传人：缺 publisher_id 时由调用方按「直传人=发布人」显式传入。
        """
        role = (beneficiary or "").strip()
        mapping = {
            "uploader": uploader_id,
            "publisher": publisher_id,
            "sharer": sharer_id,
            "answerer": answerer_id,
        }
        user_id = mapping.get(role)
        if user_id is None:
            return None, None
        return int(user_id), role


def _fixed_score(score_expr: dict[str, Any] | None) -> int:
    """读取 fixed 模式分值。"""
    expr = score_expr or {}
    if expr.get("mode") != "fixed":
        return 0
    try:
        return int(expr.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _tier_target(score_expr: dict[str, Any] | None, unique_count: int) -> tuple[int, int]:
    """按去重收藏人数计算应得累计分与最高阈值档。"""
    expr = score_expr or {}
    tiers = list(expr.get("tiers") or [])
    tiers.sort(key=lambda item: int(item.get("threshold") or 0))
    s_target = 0
    highest_tier = 0
    for item in tiers:
        threshold = int(item.get("threshold") or 0)
        if unique_count >= threshold:
            s_target = int(item.get("score") or 0)
            highest_tier = threshold
    lifetime = expr.get("lifetime_cap")
    if lifetime is not None:
        s_target = min(s_target, int(lifetime))
    return s_target, highest_tier


async def _always_false(_: int) -> bool:
    return False
