"""知识文档违规删除: 物理清理全部入口, 再按影响范围扣一次分."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bisheng.common.errcode.knowledge_space import (
    KnowledgeViolationDeleteForbiddenError,
    KnowledgeViolationDocumentBusyError,
    KnowledgeViolationDocumentIdentityMissingError,
    SpaceFileNotFoundError,
)
from bisheng.common.errcode.points import PointsRuleNotFoundError
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocumentLifecycleStatus
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_recycle_service import (
    KnowledgeDocumentRecycleService,
)
from bisheng.knowledge.domain.services.knowledge_violation_delete_policy import (
    deduct_block_reason,
    highest_scope_tier,
    is_personal_level,
    monthly_award_exempt,
    resolve_payee_id,
)
from bisheng.points.domain.constants.library_scope_score import (
    is_library_scope_rule,
    library_scope_score,
)
from bisheng.points.domain.constants.monthly_reward_rules import (
    MONTHLY_RULE_MATCHERS,
    MonthlyRuleMatcher,
    fixed_score,
)
from bisheng.points.domain.constants.rule_display_name import resolve_point_rule_display_name
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_auth import is_platform_super_admin
from bisheng.points.domain.services.points_pending_deduct_service import PointsPendingDeductService
from bisheng.points.domain.services.space_fga_roles import (
    SpaceFgaRolesError,
    read_space_owner_manager_ids,
)

logger = logging.getLogger(__name__)

_DISTRIBUTION_TYPES = {
    KnowledgeFileEntryType.MANAGER.value,
    KnowledgeFileEntryType.PUBLISH.value,
    KnowledgeFileEntryType.SHARE.value,
}
_BIZ_TYPE = "knowledge_document"


@dataclass
class ViolationLibrary:
    """预览里将删除的一个库入口."""

    space_id: int
    level: str
    name: str
    entry_type: str
    file_id: int


@dataclass
class ViolationPreview:
    """违规删除预览, 不写库."""

    file_id: int
    document_id: int
    scope_tier: str
    libraries: list[ViolationLibrary]
    payee_user_id: int | None
    can_deduct: bool
    reason: str | None
    rule_code: str | None
    score: int | None
    rules: list[dict]


@dataclass
class ViolationCommit:
    """违规删除确认结果."""

    deleted: bool
    document_id: int
    deducted: bool
    pending_deduct: bool
    reason: str | None
    scope_tier: str
    score: int | None
    rule_code: str | None
    target_user_id: int | None


def _violation_enabled() -> bool:
    """读取知识文档违规删除开关.

    Returns:
        配置缺失时为 True.
    """
    points = getattr(settings, "points", None)
    return bool(getattr(points, "knowledge_violation_delete_enabled", True))


def document_idempotency_key(document_id: int) -> str:
    """同一份知识文档只成功扣分一次的幂等键.

    Args:
        document_id: knowledge_document.id.

    Returns:
        不含规则编码的幂等键.
    """
    return f"deduct:knowledge_document:{int(document_id)}"


class KnowledgeViolationDeleteService:
    """编排违规删除. 回收先提交, 扣分失败进入补扣队列."""

    def __init__(self, pending: PointsPendingDeductService | None = None):
        self.pending = pending or PointsPendingDeductService()

    async def preview(self, *, operator, file_id: int, rule_code: str | None = None) -> ViolationPreview:
        """只读预览删除范围和扣分.

        Args:
            operator: 当前登录用户.
            file_id: 发起入口的文件 id. 必须落在非个人库.
            rule_code: 可选的 R4, R5 或 R6. 空则只返回各启用规则在当前档的分值.

        Returns:
            档位, 将删除的库, 以及是否会扣分.

        Raises:
            KnowledgeViolationDeleteForbiddenError: 无权, 功能关闭, 或从个人库发起.
            KnowledgeViolationDocumentIdentityMissingError: 没有文档身份.
            SpaceFileNotFoundError: 文件不存在或已经删除.
            PointsRuleNotFoundError: 指定的知识文档扣减规则未启用.
        """
        self._require_enabled()
        async with get_async_db_session() as session:
            loaded = await self._load(session, file_id, allow_recycled=False)
        return await self._build_preview(operator, loaded, rule_code)

    async def commit(
        self,
        *,
        operator,
        file_id: int,
        rule_code: str | None = None,
        remark: str | None = None,
    ) -> ViolationCommit:
        """物理清理全部入口, 需要时按确认时的金额扣一次.

        Args:
            operator: 当前登录用户.
            file_id: 发起入口的文件 id.
            rule_code: 空表示只删不扣.
            remark: 扣分备注, 最长 200.

        Returns:
            是否已删除, 是否已扣分, 是否进入补扣.

        Raises:
            KnowledgeViolationDeleteForbiddenError: 无权或功能关闭.
            KnowledgeViolationDocumentIdentityMissingError: 没有文档身份.
            KnowledgeViolationDocumentBusyError: 仍有准备中的发布或分享.
            SpaceFileNotFoundError: 文件不存在.
            PointsRuleNotFoundError: 规则未启用. 此时不删除.
        """
        self._require_enabled()
        code = (rule_code or "").strip().upper() or None
        async with get_async_db_session() as session:
            loaded = await self._load(session, file_id, allow_recycled=True)
            preview = await self._build_preview(operator, loaded, code)
            if code and preview.reason is None and preview.score is None:
                raise PointsRuleNotFoundError()
            document = await KnowledgeDocumentRepositoryImpl(session).find_by_id_for_update(loaded.document_id)
            if document is None:
                raise KnowledgeViolationDocumentIdentityMissingError()
            entries = await KnowledgeFileRepositoryImpl(session).find_distribution_entries_by_document_id(
                int(document.id),
                for_update=True,
            )
            entry_ids: list[int] = []
            if document.lifecycle_status != KnowledgeDocumentLifecycleStatus.DELETING.value:
                if any(entry.entry_status == KnowledgeFileEntryStatus.PREPARING.value for entry in entries):
                    raise KnowledgeViolationDocumentBusyError()
                entry_ids = await KnowledgeDocumentRecycleService(session).begin_hard_delete(document)
            await session.commit()
        if entry_ids:
            _enqueue_document_projection(loaded.tenant_id, entry_ids)
        deducted = False
        pending = False
        reason = preview.reason
        if reason is None and preview.score is not None and code:
            attempt = await self.pending.deduct_or_enqueue(
                tenant_id=loaded.tenant_id,
                user_id=int(preview.payee_user_id or 0),
                rule_code=code,
                biz_type=_BIZ_TYPE,
                biz_id=str(loaded.document_id),
                operator_id=int(getattr(operator, "user_id", 0) or 0),
                remark=remark,
                resolved_score=preview.score,
                scope_tier=preview.scope_tier,
                idempotency_key=document_idempotency_key(loaded.document_id),
            )
            deducted = attempt.applied
            pending = attempt.pending
            reason = "replayed" if attempt.replayed else attempt.reason
        return ViolationCommit(
            deleted=True,
            document_id=loaded.document_id,
            deducted=deducted,
            pending_deduct=pending,
            reason=reason,
            scope_tier=preview.scope_tier,
            score=preview.score,
            rule_code=code,
            target_user_id=preview.payee_user_id,
        )

    def _require_enabled(self) -> None:
        if not _violation_enabled():
            raise KnowledgeViolationDeleteForbiddenError()

    async def _load(self, session, file_id: int, *, allow_recycled: bool):
        files = KnowledgeFileRepositoryImpl(session)
        clicked = await files.find_by_id(int(file_id))
        if clicked is None:
            raise SpaceFileNotFoundError()
        document_id = int(clicked.reference_document_id or 0)
        if document_id <= 0:
            raise KnowledgeViolationDocumentIdentityMissingError()
        document = await KnowledgeDocumentRepositoryImpl(session).find_by_id(document_id)
        if document is None:
            raise KnowledgeViolationDocumentIdentityMissingError()
        # 已进回收站或已开始物理删除的文档, 确认接口仍要能幂等扣分.
        closed = document.lifecycle_status in {
            KnowledgeDocumentLifecycleStatus.RECYCLED.value,
            KnowledgeDocumentLifecycleStatus.DELETING.value,
        }
        if clicked.deleted_at is not None and not (allow_recycled and closed):
            raise SpaceFileNotFoundError()
        entries = await files.find_distribution_entries_by_document_id(document_id)
        return _Loaded(
            clicked=clicked,
            document_id=document_id,
            tenant_id=int(document.tenant_id or clicked.tenant_id or 1),
            recycled=closed,
            entries=entries,
        )

    async def _build_preview(self, operator, loaded, rule_code: str | None) -> ViolationPreview:
        levels = await self._space_levels({int(entry.knowledge_id) for entry in loaded.entries})
        clicked_level = levels.get(int(loaded.clicked.knowledge_id), KnowledgeSpaceLevelEnum.PERSONAL.value)
        if is_personal_level(clicked_level):
            raise KnowledgeViolationDeleteForbiddenError()
        scope_entries = _scope_entries(loaded.entries, recycled=loaded.recycled)
        scope_levels = {
            int(entry.knowledge_id): levels.get(int(entry.knowledge_id), "")
            for entry in scope_entries
            if not is_personal_level(levels.get(int(entry.knowledge_id)))
        }
        if not scope_levels:
            raise KnowledgeViolationDeleteForbiddenError()
        roles = await self._roles(set(scope_levels))
        operator_id = int(getattr(operator, "user_id", 0) or 0)
        # 直连 user 管理员之外, 按部门或用户组授予的 can_manage 也要能删.
        if not await _operator_may_violation_delete(operator, operator_id, set(scope_levels), roles):
            raise KnowledgeViolationDeleteForbiddenError()
        tier = highest_scope_tier(scope_levels.values())
        if tier is None:
            raise KnowledgeViolationDeleteForbiddenError()
        manager = self._manager_entry(loaded.entries)
        payee = resolve_payee_id(
            getattr(manager, "original_uploader_id", None) if manager else None,
            getattr(manager, "user_id", None) if manager else None,
        )
        matchers = await self._enabled_matchers(loaded.tenant_id)
        exempt = False
        if payee is not None:
            exempt = monthly_award_exempt(
                uploader_id=payee,
                space_levels=scope_levels,
                owners_by_space={space_id: owners for space_id, (owners, _) in roles.items()},
                managers_by_space={space_id: managers for space_id, (_, managers) in roles.items()},
                enabled_matchers=matchers,
            )
        code = (rule_code or "").strip().upper() or None
        rules = await self._tier_rules(loaded.tenant_id, tier)
        score = None
        if code:
            if not is_library_scope_rule(code):
                raise PointsRuleNotFoundError()
            matched = next((item for item in rules if item["rule_code"] == code), None)
            if matched is None:
                raise PointsRuleNotFoundError()
            score = int(matched["score"])
        reason = deduct_block_reason(
            rule_code=code,
            payee_id=payee,
            operator_id=operator_id,
            exempt=exempt,
        )
        libraries = [
            ViolationLibrary(
                space_id=int(entry.knowledge_id),
                level=str(levels.get(int(entry.knowledge_id), "")),
                name="",
                entry_type=str(entry.entry_type or ""),
                file_id=int(entry.id),
            )
            for entry in scope_entries
        ]
        return ViolationPreview(
            file_id=int(loaded.clicked.id),
            document_id=loaded.document_id,
            scope_tier=tier,
            libraries=libraries,
            payee_user_id=payee,
            can_deduct=reason is None and score is not None,
            reason=reason,
            rule_code=code,
            score=score,
            rules=rules,
        )

    async def _space_levels(self, space_ids: set[int]) -> dict[int, str]:
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao

        rows = await KnowledgeSpaceScopeDao.aget_by_space_ids(sorted(space_ids))
        found = {int(row.space_id): str(getattr(row.level, "value", row.level)) for row in rows}
        return {space_id: found.get(space_id, "personal") for space_id in space_ids}

    async def _roles(self, space_ids: set[int]) -> dict[int, tuple[set[int], set[int]]]:
        roles: dict[int, tuple[set[int], set[int]]] = {}
        try:
            for space_id in space_ids:
                owners, managers = await read_space_owner_manager_ids(space_id)
                roles[space_id] = (owners, managers)
        except SpaceFgaRolesError:
            logger.exception("knowledge.violation_delete.fga_unavailable")
            raise KnowledgeViolationDeleteForbiddenError() from None
        return roles

    async def _enabled_matchers(self, tenant_id: int) -> list[MonthlyRuleMatcher]:
        async with get_async_db_session() as session:
            rules = await PointsRepository(session).list_rules(
                tenant_id,
                rule_type="admin_reward",
                status="enabled",
            )
        matchers: list[MonthlyRuleMatcher] = []
        for rule in rules:
            matcher = MONTHLY_RULE_MATCHERS.get(rule.rule_code)
            if matcher is None or fixed_score(rule.score_expr) <= 0:
                continue
            matchers.append(matcher)
        return matchers

    async def _tier_rules(self, tenant_id: int, tier: str) -> list[dict]:
        async with get_async_db_session() as session:
            rules = await PointsRepository(session).list_rules(tenant_id, rule_type="deduct", status="enabled")
        rows = []
        for rule in rules:
            if not is_library_scope_rule(rule.rule_code):
                continue
            try:
                score = library_scope_score(rule.score_expr, tier)
            except ValueError:
                continue
            rows.append(
                {
                    "rule_code": rule.rule_code,
                    "name": resolve_point_rule_display_name(rule),
                    "score": score,
                }
            )
        return rows

    @staticmethod
    def _manager_entry(entries: list[KnowledgeFile]) -> KnowledgeFile | None:
        managers = [entry for entry in entries if entry.entry_type == KnowledgeFileEntryType.MANAGER.value]
        active = [entry for entry in managers if entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value]
        return (active or managers or [None])[0]


def _enqueue_document_projection(tenant_id: int, entry_ids: list[int]) -> None:
    """把已标记删除中的入口交给现有文档投影做物理清理.

    Args:
        tenant_id: 文档所属租户.
        entry_ids: 待清理的文件入口 id.
    """
    try:
        from bisheng.worker.knowledge.document_projection import enqueue_document_projection_entries

        enqueue_document_projection_entries(tenant_id=tenant_id, entry_ids=entry_ids)
    except Exception:
        logger.exception("violation delete projection dispatch failed tenant=%s entries=%s", tenant_id, entry_ids)


def _scope_entries(entries: list[KnowledgeFile], *, recycled: bool) -> list[KnowledgeFile]:
    """选出参与影响范围和删除清单的入口.

    Args:
        entries: 同一文档的全部分发入口.
        recycled: 文档已进回收站或已开始物理删除. 这时用打过删除时间的入口计算范围.

    Returns:
        回收前的有效入口, 或已经打上删除时间的入口.
    """
    chosen = []
    for entry in entries:
        if entry.entry_type not in _DISTRIBUTION_TYPES:
            continue
        if recycled:
            if entry.deleted_at is None:
                continue
        elif entry.entry_status != KnowledgeFileEntryStatus.ACTIVE.value:
            continue
        chosen.append(entry)
    return chosen


def _operator_can_manage(operator_id: int, roles: dict[int, tuple[set[int], set[int]]]) -> bool:
    """操作者是否出现在各库的直连 owner 或 manager 用户集合里.

    Args:
        operator_id: 操作者用户 id.
        roles: 空间 id 到 (所有者, 直连管理员).

    Returns:
        任一库的直连集合包含操作者时为 True.
    """
    for owners, managers in roles.values():
        if operator_id in owners or operator_id in managers:
            return True
    return False


async def _operator_may_violation_delete(
    operator,
    operator_id: int,
    space_ids: set[int],
    roles: dict[int, tuple[set[int], set[int]]],
) -> bool:
    """判断操作者能否违规删除这份文档.

    直连用户管理员走角色集合. 按部门或用户组授予的管理员没有 user 元组,
    改用知识空间 can_manage, 与成员管理同一套 ReBAC.

    Args:
        operator: 当前登录用户.
        operator_id: 操作者用户 id.
        space_ids: 文档所在的非个人库.
        roles: 各库直连 owner 与 manager.

    Returns:
        超管, 直连管理员, 或任一库 can_manage 时为 True.
    """
    if is_platform_super_admin(operator):
        return True
    if _operator_can_manage(operator_id, roles):
        return True
    if operator_id <= 0:
        return False
    from bisheng.permission.domain.services.permission_service import PermissionService

    for space_id in space_ids:
        allowed = await PermissionService.check(
            user_id=operator_id,
            relation="can_manage",
            object_type="knowledge_space",
            object_id=str(int(space_id)),
            login_user=operator,
        )
        if allowed:
            return True
    return False


@dataclass
class _Loaded:
    clicked: KnowledgeFile
    document_id: int
    tenant_id: int
    recycled: bool
    entries: list[KnowledgeFile]
