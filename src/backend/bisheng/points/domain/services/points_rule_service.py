# ruff: noqa: RUF002, RUF003
"""积分规则与说明文案服务。"""

from __future__ import annotations

import copy
import logging

from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm.attributes import flag_modified

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.points import PointsRuleAuditError, PointsRuleConflictError, PointsRuleNotFoundError
from bisheng.database.models.audit_log import AuditLog
from bisheng.points.domain.constants.beneficiary import allowed_beneficiaries
from bisheng.points.domain.constants.library_scope_score import (
    is_library_scope_rule,
    validate_library_scope_score_expr,
)
from bisheng.points.domain.constants.optional_fixed_score_rules import validate_deferred_config_rule_can_enable
from bisheng.points.domain.constants.rule_display_name import resolve_point_rule_display_name
from bisheng.points.domain.constants.seed_rules import seed_default_name
from bisheng.points.domain.constants.tier_rule_score_expr import validate_g3_tier_score_expr
from bisheng.points.domain.models import PointRule
from bisheng.points.domain.schemas.points_schema import (
    PointCopiesUpdateRequest,
    PointCopyItem,
    PointRuleRequest,
    PointRuleResponse,
)
from bisheng.points.domain.services.points_auth import require_platform_admin

logger = logging.getLogger(__name__)

_AUDIT_ACTION = "points.rule.update"


def _canon(value):
    """Canonicalize JSON so key order alone is not a change."""
    if isinstance(value, dict):
        return {key: _canon(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canon(item) for item in value]
    return value


def _norm_remark(value: str | None) -> str | None:
    """Treat blank remarks as no remark."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _snapshot_rule(rule) -> dict:
    """Fields that decide whether a rule save is a real change."""
    return {
        "display_name": str(getattr(rule, "display_name", "") or "").strip(),
        "score_expr": _canon(getattr(rule, "score_expr", None) or {}),
        "daily_cap": getattr(rule, "daily_cap", None),
        "status": getattr(rule, "status", None),
        "remark": _norm_remark(getattr(rule, "remark", None)),
        "sort_order": int(getattr(rule, "sort_order", 0) or 0),
        "beneficiary": getattr(rule, "beneficiary", None),
    }


def _raw_rule_fields(rule) -> dict:
    """Original values restored when the save is a no-op or the audit commit fails."""
    return {
        "display_name": rule.display_name,
        "score_expr": copy.deepcopy(rule.score_expr),
        "daily_cap": rule.daily_cap,
        "status": rule.status,
        "remark": rule.remark,
        "sort_order": rule.sort_order,
        "beneficiary": rule.beneficiary,
    }


def _flag_score_expr(rule) -> None:
    """Mark JSON dirty on a mapped rule. Test doubles have no SQLAlchemy state."""
    if not hasattr(rule, "_sa_instance_state"):
        return
    try:
        flag_modified(rule, "score_expr")
    except NoInspectionAvailable:
        return


def _restore_rule_fields(rule, raw: dict) -> None:
    """Put the in-memory rule back to the values loaded before this save."""
    for key, value in raw.items():
        setattr(rule, key, value)
    _flag_score_expr(rule)


def _score_change(before: dict, after: dict) -> dict | None:
    """One score change. A fixed-mode integer change is field score; anything else is score_expr."""
    if before == after:
        return None
    if before.get("mode") == "fixed" and after.get("mode") == "fixed":
        before_rest = {key: value for key, value in before.items() if key != "score"}
        after_rest = {key: value for key, value in after.items() if key != "score"}
        if before_rest == after_rest:
            return {
                "field": "score",
                "before": int(before.get("score") or 0),
                "after": int(after.get("score") or 0),
            }
    return {"field": "score_expr", "before": before, "after": after}


def _rule_changes(before: dict, after: dict) -> list[dict]:
    """Changed fields only."""
    changes: list[dict] = []
    if before["display_name"] != after["display_name"]:
        changes.append({"field": "display_name", "before": before["display_name"], "after": after["display_name"]})
    score_change = _score_change(before["score_expr"], after["score_expr"])
    if score_change is not None:
        changes.append(score_change)
    for field in ("remark", "status", "daily_cap", "beneficiary", "sort_order"):
        if before[field] != after[field]:
            changes.append({"field": field, "before": before[field], "after": after[field]})
    return changes


class PointsRuleService:
    """校验规则受益人，保证历史流水不因规则变更被重写。"""

    def __init__(self, session, repository):
        self.session = session
        self.repository = repository

    @staticmethod
    def validate_beneficiary(rule_code: str, rule_type: str, beneficiary: str | None) -> None:
        """校验 earn 规则的受益人是否与编码白名单相符。"""
        allowed = allowed_beneficiaries(rule_code)
        if rule_type == "earn" and (not beneficiary or beneficiary not in allowed):
            raise PointsRuleConflictError(msg="该规则不允许指定的积分受益人")

    @staticmethod
    def require_enabled_deduct(rule) -> None:
        """扣减前确保规则存在、已启用且类型为 deduct。"""
        if not rule or rule.rule_type != "deduct" or rule.status != "enabled":
            raise PointsRuleNotFoundError()

    def _to_dto(self, rule: PointRule) -> PointRuleResponse:
        """规则 ORM → 响应 DTO。"""
        return PointRuleResponse(
            id=int(rule.id),
            rule_code=rule.rule_code,
            rule_type=rule.rule_type,
            name=rule.name,
            display_name=resolve_point_rule_display_name(rule),
            score_expr=rule.score_expr or {},
            daily_cap=rule.daily_cap,
            beneficiary=rule.beneficiary,
            beneficiary_options=list(allowed_beneficiaries(rule.rule_code)),
            status=rule.status,
            remark=rule.remark,
            sort_order=int(rule.sort_order or 0),
        )

    async def list_rules(
        self,
        tenant_id: int,
        user: UserPayload,
        *,
        rule_type: str | None = None,
        status: str | None = None,
    ) -> list[PointRuleResponse]:
        """管理端规则列表。"""
        require_platform_admin(user)
        rows = await self.repository.list_rules(tenant_id, rule_type=rule_type, status=status)
        return [self._to_dto(r) for r in rows]

    @staticmethod
    def validate_score_expr(rule_code: str, score_expr: dict | None) -> None:
        """校验规则 score_expr 结构. G3 校验阶梯, G8 校验采纳和采纳并更新两档分值."""
        code = (rule_code or "").strip().upper()
        if code == "G3":
            err = validate_g3_tier_score_expr(score_expr)
            if err:
                raise PointsRuleConflictError(msg=err)
            return
        if is_library_scope_rule(code):
            err = validate_library_scope_score_expr(score_expr)
            if err:
                raise PointsRuleConflictError(msg=err)
            return
        if code != "G8":
            return
        expr = score_expr or {}
        if str(expr.get("mode") or "") != "file_correction":
            raise PointsRuleConflictError(msg="文档纠错规则须分别配置采纳和采纳并更新分值")
        for key in ("adopt_score", "update_score"):
            raw = expr.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                raise PointsRuleConflictError(msg="文档纠错的两档分值须为正整数")

    async def create_rule(self, tenant_id: int, user: UserPayload, body: PointRuleRequest) -> PointRuleResponse:
        """创建规则；rule_code 租户内唯一。"""
        require_platform_admin(user)
        if not body.rule_code or not body.rule_type:
            raise PointsRuleConflictError(msg="创建规则缺少必填字段")
        code = body.rule_code.strip().upper()
        default_name = seed_default_name(code) or (body.name or "").strip()
        display_name = (body.display_name or body.name or default_name or "").strip()
        if not default_name or not display_name:
            raise PointsRuleConflictError(msg="创建规则缺少必填字段")
        if await self.repository.get_rule(tenant_id, code):
            raise PointsRuleConflictError(msg=f"规则编码 {code} 已存在")
        self.validate_beneficiary(code, body.rule_type, body.beneficiary)
        self.validate_score_expr(code, body.score_expr)
        rule = PointRule(
            tenant_id=tenant_id,
            rule_code=code,
            rule_type=body.rule_type,
            name=default_name,
            display_name=display_name,
            score_expr=body.score_expr or {},
            daily_cap=body.daily_cap,
            beneficiary=body.beneficiary,
            status=body.status or "enabled",
            remark=body.remark,
            sort_order=body.sort_order or 0,
        )
        saved = await self.repository.save_rule(rule)
        await self.session.commit()
        return self._to_dto(saved)

    async def update_rule(
        self,
        tenant_id: int,
        user: UserPayload,
        rule_id: int,
        body: PointRuleRequest,
    ) -> PointRuleResponse:
        """更新可变字段；不提供物理删除，仅可改状态与配置。"""
        require_platform_admin(user)
        rule = await self.repository.get_rule_by_id(rule_id)
        if rule is None or int(rule.tenant_id) != tenant_id:
            raise PointsRuleNotFoundError()
        before_raw = _raw_rule_fields(rule)
        before = _snapshot_rule(rule)
        fields = body.model_fields_set
        if "display_name" in fields and body.display_name is not None:
            display_name = body.display_name.strip()
            if not display_name:
                _restore_rule_fields(rule, before_raw)
                raise PointsRuleConflictError(msg="积分项展示名称不能为空")
            rule.display_name = display_name
        elif "name" in fields and body.name is not None:
            # 兼容旧客户端：name 字段视为展示名写入。
            display_name = body.name.strip()
            if not display_name:
                _restore_rule_fields(rule, before_raw)
                raise PointsRuleConflictError(msg="积分项展示名称不能为空")
            rule.display_name = display_name
        if "score_expr" in fields and body.score_expr is not None:
            try:
                self.validate_score_expr(rule.rule_code, body.score_expr)
            except PointsRuleConflictError:
                _restore_rule_fields(rule, before_raw)
                raise
            rule.score_expr = body.score_expr
            _flag_score_expr(rule)
        if "daily_cap" in fields:
            rule.daily_cap = body.daily_cap
        if "status" in fields and body.status is not None:
            if body.status not in ("enabled", "disabled"):
                _restore_rule_fields(rule, before_raw)
                raise PointsRuleConflictError(msg="规则状态仅允许 enabled/disabled")
            rule.status = body.status
        if "remark" in fields:
            rule.remark = body.remark
        if "sort_order" in fields and body.sort_order is not None:
            rule.sort_order = body.sort_order
        if "beneficiary" in fields:
            try:
                self.validate_beneficiary(rule.rule_code, rule.rule_type, body.beneficiary)
            except PointsRuleConflictError:
                _restore_rule_fields(rule, before_raw)
                raise
            rule.beneficiary = body.beneficiary
        target_status = rule.status
        effective_expr = rule.score_expr or {}
        effective_cap = rule.daily_cap
        enable_err = validate_deferred_config_rule_can_enable(
            rule.rule_code,
            score_expr=effective_expr,
            daily_cap=effective_cap,
            status=target_status,
        )
        if enable_err:
            _restore_rule_fields(rule, before_raw)
            raise PointsRuleConflictError(msg=enable_err)
        changes = _rule_changes(before, _snapshot_rule(rule))
        if not changes:
            _restore_rule_fields(rule, before_raw)
            return self._to_dto(rule)
        try:
            saved = await self.repository.save_rule(rule)
            self.session.add(self._rule_audit(rule, user, changes))
            await self.session.commit()
        except Exception:
            logger.exception(
                "points.rule.update_failed operator_id=%s tenant_id=%s rule_id=%s rule_code=%s",
                getattr(user, "user_id", None),
                tenant_id,
                rule_id,
                rule.rule_code,
            )
            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "points.rule.update_rollback_failed operator_id=%s rule_id=%s",
                    getattr(user, "user_id", None),
                    rule_id,
                )
            _restore_rule_fields(rule, before_raw)
            raise PointsRuleAuditError() from None
        logger.info(
            "points.rule.updated operator_id=%s tenant_id=%s rule_id=%s rule_code=%s rule_type=%s changes=%s",
            getattr(user, "user_id", None),
            tenant_id,
            rule.id,
            rule.rule_code,
            rule.rule_type,
            changes,
        )
        return self._to_dto(saved)

    @staticmethod
    def _rule_audit(rule, user, changes: list[dict]) -> AuditLog:
        """构造与本次规则保存同事务提交的操作日志。不使用会单独提交的 ainsert_v2。"""
        name = getattr(user, "user_name", None)
        return AuditLog(
            operator_id=int(user.user_id),
            operator_name=str(name) if name else None,
            tenant_id=int(rule.tenant_id),
            operator_tenant_id=int(rule.tenant_id),
            action=_AUDIT_ACTION,
            target_type="point_rule",
            target_id=str(rule.id),
            object_name=rule.rule_code,
            audit_metadata={
                "rule_code": rule.rule_code,
                "rule_type": rule.rule_type,
                "changes": changes,
            },
        )

    async def list_copies(self, tenant_id: int, user: UserPayload) -> list[PointCopyItem]:
        """管理端说明文案列表。"""
        require_platform_admin(user)
        rows = await self.repository.list_copies(tenant_id)
        return [PointCopyItem(copy_key=r.copy_key, content=r.content, sort_order=int(r.sort_order or 0)) for r in rows]

    async def update_copies(
        self, tenant_id: int, user: UserPayload, body: PointCopiesUpdateRequest
    ) -> list[PointCopyItem]:
        """Replace-set upsert for copy rows; keys omitted from the payload are deleted."""
        require_platform_admin(user)
        rows = await self.repository.upsert_copies(
            tenant_id,
            [item.model_dump() for item in body.items],
        )
        await self.session.commit()
        return [PointCopyItem(copy_key=r.copy_key, content=r.content, sort_order=int(r.sort_order or 0)) for r in rows]

    async def public_rules(self, tenant_id: int) -> dict:
        """前台规则弹窗：启用的 earn/deduct + 文案；不暴露月奖 M*。"""
        rules = await self.repository.list_rules(tenant_id, status="enabled")
        earn = [self._to_dto(r) for r in rules if r.rule_type == "earn"]
        deduct = [self._to_dto(r) for r in rules if r.rule_type == "deduct"]
        copies = [
            PointCopyItem(copy_key=r.copy_key, content=r.content, sort_order=int(r.sort_order or 0))
            for r in await self.repository.list_copies(tenant_id)
        ]
        return {
            "earn_rules": [r.model_dump() for r in earn],
            "deduct_rules": [r.model_dump() for r in deduct],
            "copies": [c.model_dump() for c in copies],
        }
