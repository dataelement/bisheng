"""积分规则与说明文案服务。"""

from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.points import PointsRuleConflictError, PointsRuleNotFoundError
from bisheng.points.domain.constants.beneficiary import allowed_beneficiaries
from bisheng.points.domain.constants.optional_fixed_score_rules import validate_deferred_config_rule_can_enable
from bisheng.points.domain.constants.tier_rule_score_expr import validate_g3_tier_score_expr
from bisheng.points.domain.models import PointRule
from bisheng.points.domain.schemas.points_schema import (
    PointCopiesUpdateRequest,
    PointCopyItem,
    PointRuleRequest,
    PointRuleResponse,
)
from bisheng.points.domain.services.points_auth import require_platform_admin


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
        """校验规则 score_expr 结构（当前仅 G3 阶梯）。"""
        code = (rule_code or "").strip().upper()
        if code != "G3":
            return
        err = validate_g3_tier_score_expr(score_expr)
        if err:
            raise PointsRuleConflictError(msg=err)

    async def create_rule(self, tenant_id: int, user: UserPayload, body: PointRuleRequest) -> PointRuleResponse:
        """创建规则；rule_code 租户内唯一。"""
        require_platform_admin(user)
        if not body.rule_code or not body.rule_type or not body.name:
            raise PointsRuleConflictError(msg="创建规则缺少必填字段")
        code = body.rule_code.strip().upper()
        if await self.repository.get_rule(tenant_id, code):
            raise PointsRuleConflictError(msg=f"规则编码 {code} 已存在")
        self.validate_beneficiary(code, body.rule_type, body.beneficiary)
        self.validate_score_expr(code, body.score_expr)
        rule = PointRule(
            tenant_id=tenant_id,
            rule_code=code,
            rule_type=body.rule_type,
            name=body.name,
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
        fields = body.model_fields_set
        if "name" in fields and body.name is not None:
            rule.name = body.name
        if "score_expr" in fields and body.score_expr is not None:
            self.validate_score_expr(rule.rule_code, body.score_expr)
            rule.score_expr = body.score_expr
            flag_modified(rule, "score_expr")
        if "daily_cap" in fields:
            rule.daily_cap = body.daily_cap
        if "status" in fields and body.status is not None:
            if body.status not in ("enabled", "disabled"):
                raise PointsRuleConflictError(msg="规则状态仅允许 enabled/disabled")
            rule.status = body.status
        if "remark" in fields:
            rule.remark = body.remark
        if "sort_order" in fields and body.sort_order is not None:
            rule.sort_order = body.sort_order
        if "beneficiary" in fields:
            self.validate_beneficiary(rule.rule_code, rule.rule_type, body.beneficiary)
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
            raise PointsRuleConflictError(msg=enable_err)
        saved = await self.repository.save_rule(rule)
        await self.session.commit()
        return self._to_dto(saved)

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
