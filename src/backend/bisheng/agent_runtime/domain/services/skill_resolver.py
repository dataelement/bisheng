"""Decide whether the skills configured on an agent can run (F078 design decision 5).

``materialize_session_skills`` only knows the tenant's *enabled* set, so a
disabled skill and a deleted skill look the same to it. The user-facing error
must say which one happened, so this check runs first and looks the skills up
by name without filtering on ``enabled``.
"""

from __future__ import annotations

from bisheng.common.errcode.linsight import AgentSkillDeletedError, AgentSkillDisabledError
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.repositories.implementations.skill_repository_impl import SkillRepositoryImpl
from bisheng.linsight.domain.repositories.interfaces.skill_repository import SkillRepository


async def resolve_skills(
    names: list[str] | None,
    repository: SkillRepository | None = None,
) -> list[LinsightSkill]:
    """Return the configured skills in configured order, or raise if one is unusable.

    ``None`` and ``[]`` both mean "no skills" and skip the lookup. The caller
    must have set the tenant context: the lookup is strictly tenant-scoped.
    """
    wanted = list(dict.fromkeys(name for name in (names or []) if name))
    if not wanted:
        return []

    repository = repository or SkillRepositoryImpl()
    rows = {row.name: row for row in await repository.list_by_names(wanted)}

    resolved: list[LinsightSkill] = []
    for name in wanted:
        row = rows.get(name)
        if row is None:
            raise AgentSkillDeletedError(skill_name=name)
        if not row.enabled:
            raise AgentSkillDisabledError(skill_name=name)
        resolved.append(row)
    return resolved
