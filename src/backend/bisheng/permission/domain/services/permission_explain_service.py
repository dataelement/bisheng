"""Minimal non-authoritative F048 permission explanation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from bisheng.permission.domain.services.grant_source_service import (
    GrantSnapshot,
    GrantSourceRecord,
)


@dataclass(frozen=True, slots=True)
class InheritedGrantSet:
    resource_type: str
    resource_id: str
    grants: tuple[GrantSnapshot, ...]


@dataclass(frozen=True, slots=True)
class PermissionExplainContext:
    tenant_id: int
    resource_type: str
    resource_id: str
    resource_version: int
    mode: str
    parent_type: str | None
    parent_id: str | None
    local_grants: tuple[GrantSnapshot, ...]
    inherited: InheritedGrantSet | None
    actor_projected_subjects: frozenset[str]
    can_manage_roster: bool


@dataclass(frozen=True, slots=True)
class PermissionSourceExplanation:
    source_id: int
    source_version: int
    subject_type: str
    subject_id: str
    userset_relation: str | None
    include_children: bool
    source_type: str
    model_key: str
    model_level: int | None
    scope: str
    inherited_from: str | None
    protected: bool
    editable: bool


@dataclass(frozen=True, slots=True)
class PermissionExplanation:
    mode: str
    parent_type: str | None
    parent_id: str | None
    resource_version: int
    action_codes: tuple[str, ...]
    sources: tuple[PermissionSourceExplanation, ...]
    roster_complete: bool


class PermissionExplainEventPort(Protocol):
    async def emit(self, name: str, fields: dict) -> None: ...


class _NullEvents:
    async def emit(self, name: str, fields: dict) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _EffectiveSource:
    explanation: PermissionSourceExplanation
    source: GrantSourceRecord
    action_codes: tuple[str, ...]


class PermissionExplainService:
    """Describe permission facts without making or enriching a decision."""

    def __init__(
        self,
        *,
        events: PermissionExplainEventPort | None = None,
    ) -> None:
        self._events = events or _NullEvents()

    async def explain(
        self,
        context: PermissionExplainContext,
    ) -> PermissionExplanation:
        effective = self._effective_sources(context)
        actor_rows = tuple(row for row in effective if row.source.projected_subject in context.actor_projected_subjects)
        visible_rows = effective if context.can_manage_roster else actor_rows
        action_codes = tuple(sorted({action for row in actor_rows for action in row.action_codes}))
        explanation = PermissionExplanation(
            mode=context.mode,
            parent_type=context.parent_type,
            parent_id=context.parent_id,
            resource_version=context.resource_version,
            action_codes=action_codes,
            sources=tuple(row.explanation for row in visible_rows),
            roster_complete=context.can_manage_roster,
        )
        await self._emit(context, explanation)
        return explanation

    def _effective_sources(
        self,
        context: PermissionExplainContext,
    ) -> tuple[_EffectiveSource, ...]:
        rows: list[_EffectiveSource] = []
        mode = context.mode.upper()
        for grant in context.local_grants:
            if not grant.active or not grant.model.active:
                continue
            for source in grant.sources:
                if not source.active:
                    continue
                if not source.protected and mode != "CUSTOM":
                    continue
                rows.append(
                    self._row(
                        context,
                        grant,
                        source,
                        scope="LOCAL",
                        inherited_from=None,
                    )
                )

        if mode == "INHERIT" and context.inherited is not None:
            inherited_from = f"{context.inherited.resource_type}:{context.inherited.resource_id}"
            for grant in context.inherited.grants:
                if not grant.active or not grant.model.active:
                    continue
                rows.extend(
                    self._row(
                        context,
                        grant,
                        source,
                        scope="INHERITED",
                        inherited_from=inherited_from,
                    )
                    for source in grant.sources
                    if source.active
                )
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    0 if row.explanation.scope == "LOCAL" else 1,
                    row.explanation.source_id,
                    row.explanation.model_key,
                ),
            )
        )

    @staticmethod
    def _row(
        context: PermissionExplainContext,
        grant: GrantSnapshot,
        source: GrantSourceRecord,
        *,
        scope: str,
        inherited_from: str | None,
    ) -> _EffectiveSource:
        return _EffectiveSource(
            explanation=PermissionSourceExplanation(
                source_id=source.source_id,
                source_version=source.version,
                subject_type=source.subject_type,
                subject_id=source.subject_id,
                userset_relation=source.userset_relation,
                include_children=source.include_children,
                source_type=source.source_type,
                model_key=grant.model.model_key,
                model_level=grant.model.derived_level,
                scope=scope,
                inherited_from=inherited_from,
                protected=source.protected,
                editable=(
                    context.can_manage_roster
                    and scope == "LOCAL"
                    and context.mode.upper() == "CUSTOM"
                    and not source.protected
                ),
            ),
            source=source,
            action_codes=grant.model.action_codes,
        )

    async def _emit(
        self,
        context: PermissionExplainContext,
        explanation: PermissionExplanation,
    ) -> None:
        try:
            await self._events.emit(
                "permission_roster_explain",
                {
                    "mode": context.mode,
                    "resource_type": context.resource_type,
                    "roster_complete": explanation.roster_complete,
                    "source_count": len(explanation.sources),
                    "tenant_id": context.tenant_id,
                },
            )
        except Exception:
            # Display and observability failures never alter permission facts.
            logger.exception("Failed to emit the F048 permission explanation event")
            return
