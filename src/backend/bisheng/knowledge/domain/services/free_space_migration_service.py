from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Literal, Optional

from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
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
            return None
        for dept_id in await cls._department_id_chain(int(primary.department_id)):
            space_id = await DepartmentKnowledgeSpaceDao.aget_space_id_by_department_id(dept_id)
            if space_id is not None:
                return int(space_id)
        return None

    @classmethod
    async def pre_delete_guard(cls, space) -> "MigrationDecision":
        """删除前置判定：迁移中/科室库禁止删除/非 team 直接删/自由 team 库判迁移目标与向量模型。"""
        if space.state == KnowledgeState.COPYING.value:
            return MigrationDecision("block", reason="migrating")
        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space.id)
        if binding is not None:
            return MigrationDecision("block", reason="department_space_forbidden")
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space.id)
        level = getattr(scope, "level", None)
        if level != KnowledgeSpaceLevelEnum.TEAM.value and level != KnowledgeSpaceLevelEnum.TEAM:
            return MigrationDecision("normal_delete")
        target_id = await cls.resolve_target_department_space(space.user_id)
        if target_id is None:
            return MigrationDecision("block", reason="target_not_found")
        target = await KnowledgeDao.aquery_by_id(target_id)
        if target is None or target.model != space.model:
            return MigrationDecision("block", reason="embedding_mismatch")
        return MigrationDecision("migrate", target_space_id=target_id)
