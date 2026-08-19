from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, delete, false, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeLockScope,
    KnowledgeSpaceFileChangeRequest,
)

RESOURCE_LOCK_BLOCKING_EXECUTION_STATES = frozenset(
    {
        KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
        KnowledgeSpaceFileChangeExecutionState.QUEUED,
        KnowledgeSpaceFileChangeExecutionState.APPLYING,
        KnowledgeSpaceFileChangeExecutionState.FAILED,
        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
    }
)


@dataclass(frozen=True, slots=True)
class FootprintEntry:
    """Normalized relational lock input; action snapshots are never queried."""

    space_id: int
    resource_type: str
    resource_id: int | None = None
    path_root: str | None = None
    lock_scope: str = KnowledgeSpaceFileChangeLockScope.EXACT


@dataclass(frozen=True, slots=True)
class MutationReadProjection:
    request_id: int
    action: str
    phase: str
    source_space_id: int
    target_space_id: int
    manifest: dict


@dataclass(frozen=True, slots=True)
class ResourceMutationMatch:
    request: KnowledgeSpaceFileChangeRequest
    path_root: str | None
    lock_scope: str


class KnowledgeSpaceFileChangeFootprintRepository:
    """Persists and compares normalized resource/path footprints."""

    LIKE_ESCAPE = "\\"
    VALID_LOCK_SCOPES = frozenset(
        {
            KnowledgeSpaceFileChangeLockScope.EXACT,
            KnowledgeSpaceFileChangeLockScope.SUBTREE,
            KnowledgeSpaceFileChangeLockScope.DESTINATION,
        }
    )

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def normalize_path_root(path_root: str | None) -> str | None:
        if path_root is None:
            return None
        parts = [part for part in str(path_root).strip().split("/") if part]
        if not parts:
            return "/"
        return f"/{'/'.join(parts)}/"

    @classmethod
    def normalize_entry(cls, footprint: FootprintEntry) -> FootprintEntry:
        lock_scope = str(footprint.lock_scope)
        if lock_scope not in cls.VALID_LOCK_SCOPES:
            raise ValueError(f"unsupported footprint lock scope: {lock_scope}")
        return FootprintEntry(
            space_id=int(footprint.space_id),
            resource_type=str(footprint.resource_type),
            resource_id=int(footprint.resource_id) if footprint.resource_id is not None else None,
            path_root=cls.normalize_path_root(footprint.path_root),
            lock_scope=lock_scope,
        )

    @classmethod
    def normalize_entries(cls, footprints: Sequence[FootprintEntry]) -> list[FootprintEntry]:
        unique: dict[tuple[int, str, int | None, str | None, str], FootprintEntry] = {}
        for footprint in footprints:
            normalized = cls.normalize_entry(footprint)
            key = (
                normalized.space_id,
                normalized.resource_type,
                normalized.resource_id,
                normalized.path_root,
                normalized.lock_scope,
            )
            unique[key] = normalized
        return list(unique.values())

    @classmethod
    def escape_like(cls, value: str) -> str:
        return value.replace(cls.LIKE_ESCAPE, cls.LIKE_ESCAPE * 2).replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def ancestor_paths(cls, path_root: str) -> list[str]:
        normalized = cls.normalize_path_root(path_root)
        if normalized == "/":
            return ["/"]
        assert normalized is not None
        parts = [part for part in normalized.split("/") if part]
        return ["/", *(f"/{'/'.join(parts[:index])}/" for index in range(1, len(parts) + 1))]

    @classmethod
    def _resource_overlap_condition(cls, footprint: FootprintEntry):
        if footprint.resource_id is None:
            return None
        same_resource = and_(
            KnowledgeSpaceFileChangeFootprint.resource_type == footprint.resource_type,
            KnowledgeSpaceFileChangeFootprint.resource_id == footprint.resource_id,
        )
        if footprint.lock_scope == KnowledgeSpaceFileChangeLockScope.DESTINATION:
            # Destination markers describe where a mutation will land, not a
            # mutation of the directory itself. Two moves into the same parent
            # may proceed independently; a real EXACT/SUBTREE change to that
            # parent still conflicts with the marker.
            return and_(
                same_resource,
                KnowledgeSpaceFileChangeFootprint.lock_scope != KnowledgeSpaceFileChangeLockScope.DESTINATION,
            )
        return same_resource

    @classmethod
    def _path_overlap_condition(cls, footprint: FootprintEntry):
        """Build the directional lock-scope truth table for one candidate.

        Existing \\ candidate | EXACT | SUBTREE | DESTINATION
        ----------------------|-------|---------|------------
        EXACT                 | no    | inside  | no
        SUBTREE               | covers| overlap | covers
        DESTINATION           | no    | inside  | no

        Resource identity is handled separately. In particular, EXACT ancestor
        markers and DESTINATION markers never conflict with their own kind merely
        because they share a parent path.
        """
        if footprint.path_root is None:
            return None

        existing_scope = KnowledgeSpaceFileChangeFootprint.lock_scope
        existing_path = KnowledgeSpaceFileChangeFootprint.path_root
        ancestors = cls.ancestor_paths(footprint.path_root)
        existing_inside_candidate = existing_path.like(
            f"{cls.escape_like(footprint.path_root)}%",
            escape=cls.LIKE_ESCAPE,
        )

        if footprint.lock_scope == KnowledgeSpaceFileChangeLockScope.EXACT:
            return and_(
                existing_scope == KnowledgeSpaceFileChangeLockScope.SUBTREE,
                existing_path.in_(ancestors),
            )
        if footprint.lock_scope == KnowledgeSpaceFileChangeLockScope.SUBTREE:
            return or_(
                and_(
                    existing_scope == KnowledgeSpaceFileChangeLockScope.SUBTREE,
                    or_(
                        existing_path.in_(ancestors),
                        existing_inside_candidate,
                    ),
                ),
                and_(
                    existing_scope.in_(
                        (
                            KnowledgeSpaceFileChangeLockScope.EXACT,
                            KnowledgeSpaceFileChangeLockScope.DESTINATION,
                        )
                    ),
                    existing_inside_candidate,
                ),
            )
        if footprint.lock_scope == KnowledgeSpaceFileChangeLockScope.DESTINATION:
            return and_(
                existing_scope == KnowledgeSpaceFileChangeLockScope.SUBTREE,
                existing_path.in_(ancestors),
            )
        raise ValueError(f"unsupported footprint lock scope: {footprint.lock_scope}")

    async def add_many(
        self,
        *,
        tenant_id: int,
        request_id: int,
        footprints: Sequence[FootprintEntry],
    ) -> list[KnowledgeSpaceFileChangeFootprint]:
        rows = [
            KnowledgeSpaceFileChangeFootprint(
                tenant_id=int(tenant_id),
                request_id=int(request_id),
                space_id=footprint.space_id,
                resource_type=footprint.resource_type,
                resource_id=footprint.resource_id,
                path_root=footprint.path_root,
                lock_scope=footprint.lock_scope,
            )
            for footprint in self.normalize_entries(footprints)
        ]
        self.session.add_all(rows)
        await self.session.flush()
        return rows

    @classmethod
    def _overlap_conditions(cls, footprints: Sequence[FootprintEntry]):
        conditions = []
        for footprint in cls.normalize_entries(footprints):
            entry_conditions = [
                condition
                for condition in (
                    cls._resource_overlap_condition(footprint),
                    cls._path_overlap_condition(footprint),
                )
                if condition is not None
            ]
            if entry_conditions:
                conditions.append(
                    (KnowledgeSpaceFileChangeFootprint.space_id == footprint.space_id) & or_(*entry_conditions)
                )
        return conditions

    @classmethod
    def build_blocking_conflict_statement(
        cls,
        *,
        tenant_id: int,
        footprints: Sequence[FootprintEntry],
    ):
        tenant_id = int(tenant_id)
        overlap_conditions = cls._overlap_conditions(footprints)
        statement = (
            select(KnowledgeSpaceFileChangeRequest.id)
            .join(
                KnowledgeSpaceFileChangeFootprint,
                KnowledgeSpaceFileChangeFootprint.request_id == KnowledgeSpaceFileChangeRequest.id,
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeFootprint.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.approval_instance_id.is_not(None),
                KnowledgeSpaceFileChangeRequest.execution_state.in_(RESOURCE_LOCK_BLOCKING_EXECUTION_STATES),
                or_(*overlap_conditions) if overlap_conditions else false(),
            )
            .distinct()
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
        )
        return statement

    async def find_blocking_request_ids(
        self,
        *,
        tenant_id: int,
        footprints: Sequence[FootprintEntry],
    ) -> list[int]:
        if not footprints:
            return []
        statement = self.build_blocking_conflict_statement(
            tenant_id=tenant_id,
            footprints=footprints,
        )
        return [int(request_id) for request_id in (await self.session.exec(statement)).all()]

    async def list_active_resource_matches(
        self,
        *,
        tenant_id: int,
        space_id: int,
        resources: Sequence[FootprintEntry],
    ) -> list[ResourceMutationMatch]:
        """Batch-load active formal-resource mutations for one visible page.

        Only the request's authoritative source root footprint participates in
        display projection. Destination and target-ancestor conflict markers
        must never make an unrelated target folder look pending.
        """

        tenant_id = int(tenant_id)
        space_id = int(space_id)
        overlap_conditions = self._overlap_conditions(resources)
        if not overlap_conditions:
            return []
        statement = (
            select(
                KnowledgeSpaceFileChangeRequest,
                KnowledgeSpaceFileChangeFootprint,
            )
            .join(
                KnowledgeSpaceFileChangeFootprint,
                and_(
                    KnowledgeSpaceFileChangeFootprint.tenant_id == tenant_id,
                    KnowledgeSpaceFileChangeFootprint.request_id == KnowledgeSpaceFileChangeRequest.id,
                    KnowledgeSpaceFileChangeFootprint.space_id == KnowledgeSpaceFileChangeRequest.space_id,
                    KnowledgeSpaceFileChangeFootprint.resource_type == KnowledgeSpaceFileChangeRequest.resource_type,
                    KnowledgeSpaceFileChangeFootprint.resource_id == KnowledgeSpaceFileChangeRequest.resource_id,
                    KnowledgeSpaceFileChangeFootprint.lock_scope.in_(
                        (
                            KnowledgeSpaceFileChangeLockScope.EXACT,
                            KnowledgeSpaceFileChangeLockScope.SUBTREE,
                        )
                    ),
                ),
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                KnowledgeSpaceFileChangeRequest.space_id == space_id,
                KnowledgeSpaceFileChangeRequest.action.in_(
                    (
                        KnowledgeSpaceFileChangeAction.RENAME,
                        KnowledgeSpaceFileChangeAction.MOVE,
                        KnowledgeSpaceFileChangeAction.DELETE,
                    )
                ),
                KnowledgeSpaceFileChangeRequest.execution_state.in_(RESOURCE_LOCK_BLOCKING_EXECUTION_STATES),
                or_(*overlap_conditions),
            )
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
        )
        return [
            ResourceMutationMatch(
                request=request,
                path_root=footprint.path_root,
                lock_scope=str(footprint.lock_scope),
            )
            for request, footprint in (await self.session.exec(statement)).all()
        ]

    async def list_by_request_id(
        self,
        *,
        tenant_id: int,
        request_id: int,
    ) -> list[KnowledgeSpaceFileChangeFootprint]:
        statement = (
            select(KnowledgeSpaceFileChangeFootprint)
            .where(
                KnowledgeSpaceFileChangeFootprint.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeFootprint.request_id == int(request_id),
            )
            .order_by(KnowledgeSpaceFileChangeFootprint.id.asc())
        )
        return list((await self.session.exec(statement)).all())

    async def list_by_request_ids(
        self,
        *,
        tenant_id: int,
        request_ids: Sequence[int],
        space_ids: Sequence[int],
    ) -> list[KnowledgeSpaceFileChangeFootprint]:
        """Batch-load cutover footprints without relying on tenant auto-filter."""
        normalized_request_ids = sorted({int(request_id) for request_id in request_ids})
        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        if not normalized_request_ids or not normalized_space_ids:
            return []
        statement = (
            select(KnowledgeSpaceFileChangeFootprint)
            .where(
                KnowledgeSpaceFileChangeFootprint.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeFootprint.request_id.in_(normalized_request_ids),
                KnowledgeSpaceFileChangeFootprint.space_id.in_(normalized_space_ids),
            )
            .order_by(
                KnowledgeSpaceFileChangeFootprint.request_id.asc(),
                KnowledgeSpaceFileChangeFootprint.id.asc(),
            )
        )
        return list((await self.session.exec(statement)).all())

    async def list_active_delete_resource_ids(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        resource_types: Sequence[str],
        cutover_checkpoint_key: str,
    ) -> set[int]:
        """Read only active post-cutover residue through indexed footprints.

        APPLIED alone is historical forever. Requiring an existing footprint
        makes this query bounded by outstanding physical purge work; the final
        purge transaction retires those rows after every external step is
        authoritatively acknowledged.
        """

        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        normalized_resource_types = sorted({str(resource_type) for resource_type in resource_types})
        if not normalized_space_ids or not normalized_resource_types:
            return set()
        statement = (
            select(
                KnowledgeSpaceFileChangeFootprint.resource_id,
                KnowledgeSpaceFileChangeRequest.execution_checkpoint,
            )
            .join(
                KnowledgeSpaceFileChangeRequest,
                KnowledgeSpaceFileChangeRequest.id == KnowledgeSpaceFileChangeFootprint.request_id,
            )
            .where(
                KnowledgeSpaceFileChangeFootprint.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeFootprint.space_id.in_(normalized_space_ids),
                KnowledgeSpaceFileChangeFootprint.resource_type.in_(normalized_resource_types),
                KnowledgeSpaceFileChangeFootprint.resource_id.is_not(None),
                KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeRequest.action == KnowledgeSpaceFileChangeAction.DELETE,
                KnowledgeSpaceFileChangeRequest.execution_state.in_(
                    (
                        KnowledgeSpaceFileChangeExecutionState.APPLYING,
                        KnowledgeSpaceFileChangeExecutionState.FAILED,
                        # Backward-compatible recovery for requests committed
                        # by the pre-AC-24 state machine.
                        KnowledgeSpaceFileChangeExecutionState.APPLIED,
                    )
                ),
            )
            .order_by(
                KnowledgeSpaceFileChangeFootprint.resource_id.asc(),
                KnowledgeSpaceFileChangeRequest.id.asc(),
            )
        )
        return {
            int(resource_id)
            for resource_id, checkpoint in (await self.session.exec(statement)).all()
            if resource_id is not None
            and isinstance(checkpoint, dict)
            and checkpoint.get(str(cutover_checkpoint_key)) is True
        }

    async def list_active_mutation_projections(
        self,
        *,
        tenant_id: int,
        space_ids: Sequence[int],
        transition_active_key: str,
        transition_phase_key: str,
    ) -> list[MutationReadProjection]:
        """Load active rename/move transitions without querying JSON fields."""

        normalized_space_ids = sorted({int(space_id) for space_id in space_ids})
        if not normalized_space_ids:
            return []
        statement = (
            select(KnowledgeSpaceFileChangeRequest)
            .join(
                KnowledgeSpaceFileChangeFootprint,
                KnowledgeSpaceFileChangeFootprint.request_id == KnowledgeSpaceFileChangeRequest.id,
            )
            .where(
                KnowledgeSpaceFileChangeRequest.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeRequest.action.in_(
                    (
                        KnowledgeSpaceFileChangeAction.RENAME,
                        KnowledgeSpaceFileChangeAction.MOVE,
                    )
                ),
                KnowledgeSpaceFileChangeRequest.execution_state.in_(
                    (
                        KnowledgeSpaceFileChangeExecutionState.APPLYING,
                        KnowledgeSpaceFileChangeExecutionState.APPLIED,
                        KnowledgeSpaceFileChangeExecutionState.FAILED,
                        KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
                    )
                ),
                KnowledgeSpaceFileChangeFootprint.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeFootprint.space_id.in_(normalized_space_ids),
            )
            .distinct()
            .order_by(KnowledgeSpaceFileChangeRequest.id.asc())
        )
        requests = list((await self.session.exec(statement)).all())
        projections: list[MutationReadProjection] = []
        for request in requests:
            checkpoint = request.execution_checkpoint
            if not isinstance(checkpoint, dict) or checkpoint.get(str(transition_active_key)) is not True:
                continue
            manifest = checkpoint.get("mutation_manifest")
            if not isinstance(manifest, dict):
                continue
            source_space_id = int(manifest.get("source_space_id") or request.space_id)
            target_space_id = int(manifest.get("target_space_id") or source_space_id)
            projections.append(
                MutationReadProjection(
                    request_id=int(request.id),
                    action=str(request.action),
                    phase=str(checkpoint.get(str(transition_phase_key)) or "old_view"),
                    source_space_id=source_space_id,
                    target_space_id=target_space_id,
                    manifest=manifest,
                )
            )
        return projections

    async def retire_delete_guard(self, *, tenant_id: int, request_id: int) -> None:
        """Remove active residue truth after all purge steps succeed."""

        await self.session.exec(
            delete(KnowledgeSpaceFileChangeFootprint).where(
                KnowledgeSpaceFileChangeFootprint.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeFootprint.request_id == int(request_id),
            )
        )
        await self.session.flush()

    async def retire_mutation_projection(self, *, tenant_id: int, request_id: int) -> None:
        """Retire the relational OLD/NEW view index after verified cleanup.

        The request and immutable manifest remain as audit history.  Projection
        reads deliberately join through these rows so deleting them in the same
        transaction that clears ``mutation_transition_active`` prevents every
        future children/search read from scanning historical APPLIED mutations.
        """

        await self.session.exec(
            delete(KnowledgeSpaceFileChangeFootprint).where(
                KnowledgeSpaceFileChangeFootprint.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeFootprint.request_id == int(request_id),
            )
        )
        await self.session.flush()
