from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Literal, Optional

from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceAmbiguousError,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.services.department_space_target_resolver import (
    DepartmentSpaceTargetResolver,
)

_logger = logging.getLogger(__name__)


@dataclass
class MigrationDecision:
    action: Literal["normal_delete", "migrate", "block"]
    target_space_id: Optional[int] = None
    reason: str = ""


class FreeSpaceMigrationService:
    """自由知识库删除时的迁移目标查找与删除前置判定。"""

    @staticmethod
    def _parse_path_ids(path: Optional[str]) -> List[int]:
        """把物化路径 '/1/2/3/' 解析成 [1, 2, 3]（从根到叶）。"""
        if not path:
            return []
        ids: List[int] = []
        for part in path.split("/"):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        return ids

    @classmethod
    async def _department_id_chain(cls, primary_department_id: int) -> List[int]:
        """返回 [主部门, 父, 祖父, ... 根]（自近到远，含自身）。"""
        dept = await DepartmentDao.aget_by_id(primary_department_id)
        if dept is None:
            return [primary_department_id]
        path_ids = cls._parse_path_ids(getattr(dept, "path", None))
        if primary_department_id not in path_ids:
            path_ids.append(primary_department_id)
        # path 是 根→叶；反转成 叶→根（自近到远）
        return list(reversed(path_ids))

    @classmethod
    async def resolve_target_department_space(cls, creator_user_id: int) -> Optional[int]:
        """创建者主部门→沿 path 向上找最近的已绑定科室库 space_id；找不到返回 None。"""
        primary = await UserDepartmentDao.aget_user_primary_department(creator_user_id)
        if primary is None or getattr(primary, "department_id", None) is None:
            _logger.info("resolve_target creator=%s → 无主部门", creator_user_id)
            return None
        chain = await cls._department_id_chain(int(primary.department_id))
        space_id = await DepartmentSpaceTargetResolver.resolve(chain)
        if space_id is not None:
            _logger.info(
                "resolve_target creator=%s chain(近→远)=%s → space=%s",
                creator_user_id,
                chain,
                space_id,
            )
            return int(space_id)
        _logger.info(
            "resolve_target creator=%s chain(近→远)=%s → 沿途无已绑定科室库",
            creator_user_id, chain,
        )
        return None

    @classmethod
    async def pre_delete_guard(cls, space) -> "MigrationDecision":
        """删除前置判定：迁移中阻断；科室库和非 team 库直接删除；自由 team 库判迁移目标与向量模型。"""
        space_id = getattr(space, "id", None)
        if space.state == KnowledgeState.COPYING.value:
            _logger.info("pre_delete_guard space=%s → block(migrating 迁移中)", space_id)
            return MigrationDecision("block", reason="migrating")
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space.id)
        if binding is not None:
            _logger.info(
                "pre_delete_guard space=%s → normal_delete(科室库允许删除，绑定随知识库级联清理)",
                space_id,
            )
            return MigrationDecision("normal_delete")
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space.id)
        level = getattr(scope, "level", None)
        if not KnowledgeSpaceLevelEnum.is_team_level(level):
            _logger.info("pre_delete_guard space=%s level=%s → normal_delete(非自由 team 库，直接删)", space_id, level)
            return MigrationDecision("normal_delete")
        try:
            target_id = await cls.resolve_target_department_space(space.user_id)
        except DepartmentKnowledgeSpaceAmbiguousError:
            _logger.warning(
                "pre_delete_guard space=%s → block(ambiguous_target 多个目标知识库)",
                space_id,
            )
            return MigrationDecision("block", reason="ambiguous_target")
        if target_id is None:
            _logger.info(
                "pre_delete_guard space=%s creator=%s → block(target_not_found 无法迁移，找不到目标科室库)",
                space_id, getattr(space, "user_id", None),
            )
            return MigrationDecision("block", reason="target_not_found")
        target = await KnowledgeDao.aquery_by_id(target_id)
        if target is None or target.model != space.model:
            _logger.info(
                "pre_delete_guard space=%s target=%s → block(embedding_mismatch 向量模型不一致) "
                "source_model=%s target_model=%s",
                space_id, target_id, getattr(space, "model", None),
                getattr(target, "model", None) if target is not None else None,
            )
            return MigrationDecision("block", reason="embedding_mismatch")
        _logger.info("pre_delete_guard space=%s → migrate(迁移到科室库) target=%s", space_id, target_id)
        return MigrationDecision("migrate", target_space_id=target_id)
