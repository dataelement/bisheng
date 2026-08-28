"""Placement rules for migrating with a link left behind.

Leaving a link at the source is publishing: the file itself moves up a level
and a shortcut stays where people expect to find it. So the mode reuses the
ladder publishing already enforces instead of inventing a second one — two
ladders would eventually disagree, and the same move would be allowed through
one entry point and refused through the other.

The map is duplicated here rather than imported from the approval module: the
knowledge module must not depend on approval, and approval already depends on
knowledge. A test asserts the two stay identical, so a change to one that
forgets the other fails loudly rather than drifting.
"""

from __future__ import annotations

from collections.abc import Iterable

from bisheng.common.errcode.knowledge_migration import (
    MigrationPreserveLinkPublicSourceError,
    MigrationPreserveLinkSourceLevelMixedError,
    MigrationPreserveLinkTargetLevelError,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

PUBLIC_SOURCE_UNAVAILABLE_REASON = "公共知识库没有上一级，无法作为保留原位链接的来源"  # noqa: RUF001

PRESERVE_LINK_PARENT_LEVELS: dict[KnowledgeSpaceLevelEnum, set[KnowledgeSpaceLevelEnum]] = {
    KnowledgeSpaceLevelEnum.PERSONAL: {
        KnowledgeSpaceLevelEnum.TEAM,
        KnowledgeSpaceLevelEnum.TEAM_KS,
    },
    KnowledgeSpaceLevelEnum.TEAM: {
        KnowledgeSpaceLevelEnum.DEPARTMENT,
    },
    KnowledgeSpaceLevelEnum.TEAM_KS: {
        KnowledgeSpaceLevelEnum.DEPARTMENT,
    },
    KnowledgeSpaceLevelEnum.DEPARTMENT: {
        KnowledgeSpaceLevelEnum.PUBLIC,
    },
}


def normalize_level(level) -> KnowledgeSpaceLevelEnum:
    if isinstance(level, KnowledgeSpaceLevelEnum):
        return level
    return KnowledgeSpaceLevelEnum(str(level))


def parent_levels_for(level) -> set[KnowledgeSpaceLevelEnum]:
    """Levels a space at ``level`` may publish up into; empty when it is the top."""
    return PRESERVE_LINK_PARENT_LEVELS.get(normalize_level(level), set())


def validate_preserve_link_levels(
    *,
    source_levels: Iterable,
    target_level,
) -> KnowledgeSpaceLevelEnum:
    """Check the level ladder for a preserve-link batch; returns the source level.

    Raises a business error naming the specific problem rather than a generic
    "invalid request": the operator picked these spaces by hand and needs to
    know which constraint they hit.
    """
    normalized_sources = {normalize_level(item) for item in source_levels}
    if len(normalized_sources) != 1:
        raise MigrationPreserveLinkSourceLevelMixedError()

    source_level = next(iter(normalized_sources))
    allowed = parent_levels_for(source_level)
    if not allowed:
        raise MigrationPreserveLinkPublicSourceError()
    if normalize_level(target_level) not in allowed:
        raise MigrationPreserveLinkTargetLevelError()
    return source_level
