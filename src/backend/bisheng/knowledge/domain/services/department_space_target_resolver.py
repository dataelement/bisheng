from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceAmbiguousError,
)
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScopeDao,
)


class DepartmentSpaceTargetKind(str, Enum):
    """Which knowledge-space type to pick from department_knowledge_space bindings."""

    DEPARTMENT = "department"
    CLINIC = "clinic"


class DepartmentSpaceTargetResolver:
    """Resolve one deterministic target space from a nearest-first department chain."""

    @classmethod
    async def resolve(
        cls,
        department_ids: Sequence[int],
        *,
        kind: DepartmentSpaceTargetKind = DepartmentSpaceTargetKind.DEPARTMENT,
        allow_legacy: bool = True,
    ) -> int | None:
        ordered_department_ids = list(dict.fromkeys(int(one) for one in department_ids))
        if not ordered_department_ids:
            return None

        bindings = await DepartmentKnowledgeSpaceDao.aget_by_department_ids(
            ordered_department_ids,
        )
        if not bindings:
            return None

        scope_rows = await KnowledgeSpaceScopeDao.aget_by_space_ids(
            sorted({int(binding.space_id) for binding in bindings}),
        )
        scope_map = {int(scope.space_id): scope for scope in scope_rows}
        bindings_by_department: dict[int, list] = {}
        for binding in bindings:
            bindings_by_department.setdefault(int(binding.department_id), []).append(binding)

        for department_id in ordered_department_ids:
            department_bindings = bindings_by_department.get(department_id, [])
            if not department_bindings:
                continue

            candidate_space_ids = sorted(
                {
                    int(binding.space_id)
                    for binding in department_bindings
                    if cls._matches_kind(
                        scope_map.get(int(binding.space_id)),
                        department_id=department_id,
                        kind=kind,
                    )
                }
            )
            if candidate_space_ids:
                return cls._require_single_candidate(
                    department_id,
                    candidate_space_ids,
                )

            if allow_legacy and kind == DepartmentSpaceTargetKind.DEPARTMENT:
                legacy_space_ids = sorted({int(binding.space_id) for binding in department_bindings})
                return cls._require_single_candidate(department_id, legacy_space_ids)

        return None

    @classmethod
    def _matches_kind(
        cls,
        scope,
        *,
        department_id: int,
        kind: DepartmentSpaceTargetKind,
    ) -> bool:
        if kind == DepartmentSpaceTargetKind.DEPARTMENT:
            return cls._is_department_scope(scope, department_id)
        return cls._is_clinic_scope(scope)

    @staticmethod
    def _is_department_scope(scope, department_id: int) -> bool:
        return (
            scope is not None
            and scope.level == KnowledgeSpaceLevelEnum.DEPARTMENT
            and scope.owner_type == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT
            and int(scope.owner_id) == department_id
        )

    @staticmethod
    def _is_clinic_scope(scope) -> bool:
        return (
            scope is not None
            and KnowledgeSpaceLevelEnum.is_team_level(scope.level)
            and scope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER
        )

    @staticmethod
    def _require_single_candidate(
        department_id: int,
        candidate_space_ids: list[int],
    ) -> int:
        if len(candidate_space_ids) == 1:
            return candidate_space_ids[0]
        raise DepartmentKnowledgeSpaceAmbiguousError(
            department_id=department_id,
            candidate_space_ids=candidate_space_ids,
        )
