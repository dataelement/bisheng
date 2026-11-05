"""Knowledge space/file current-read plans under exact SourceOwner authority."""

from dataclasses import dataclass

from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.reference_target_repository import original_for
from bisheng.resource_reference.application.contracts import DeletionEvidence, TargetKey, TargetType
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository


@dataclass(frozen=True, slots=True)
class KnowledgeReadObservation:
    key: TargetKey
    exists: bool
    target_tenant_id: int | None
    target_space_id: str | None
    original: object | None
    deletion: DeletionEvidence | None
    ancestor_deletion: DeletionEvidence | None


class KnowledgeSourceReadTargetRepository:
    def __init__(self, verifier):
        self.verifier = verifier
        self.sources = SourceReadRepository(verifier)

    @staticmethod
    async def _rows(session, statement):
        with session.no_autoflush, bypass_tenant_filter():
            return tuple(await session.execute(statement))

    async def _business(self, session, model, ids, tenant_id, *, lock):
        columns = (
            (model.id, model.tenant_id, model.type)
            if model is Knowledge
            else (model.id, model.tenant_id, model.knowledge_id)
        )
        statement = select(*columns).where(model.tenant_id == tenant_id, model.id.in_(sorted(ids))).order_by(model.id)
        rows = await self._rows(session, statement.with_for_update() if lock else statement) if ids else ()
        return {row.id: row for row in rows}

    async def alock_targets(self, session, scope, target_keys, *, identity, transient=False):
        snapshot = await self.verifier.aassert_target_keys(
            session, scope, identity, target_keys, allowed_types=(TargetType.KNOWLEDGE_SPACE, TargetType.KNOWLEDGE_FILE)
        )
        if transient:
            await self.verifier.aget_transient_snapshot(session, scope, identity)
            tenant_id, originals = snapshot.owner_tenant_id, ()
        else:
            await self.verifier.aget_source_snapshot(session, scope, identity)
            tenant_id = snapshot.source_key.tenant_id
            originals = (await self.sources.aread_source(session, scope, identity)).references
        keys = tuple(sorted(target_keys, key=lambda key: key.lock_order_key))
        originals = tuple(row for row in originals if TargetKey(row.target_type, row.target_id) in keys)
        if any(row.target_tenant_id not in (None, tenant_id) for row in originals):
            raise ResourceReferenceInvalidError(reason="knowledge_reference_target_unavailable")
        file_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_FILE}
        candidates = await self._business(session, KnowledgeFile, file_ids, tenant_id, lock=False)
        mapping = {row.id: row.knowledge_id for row in candidates.values()}
        space_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_SPACE}
        space_ids.update(mapping.values())
        space_ids.update(int(row.target_space_id) for row in originals if row.target_space_id is not None)
        spaces = await self._business(session, Knowledge, space_ids, tenant_id, lock=True)
        files = await self._business(session, KnowledgeFile, file_ids, tenant_id, lock=True)
        if {row.id: row.knowledge_id for row in files.values()} != mapping:
            raise KnowledgeOperationPlanConflictError(reason="reference_read_target_plan_changed")
        planned, tombstone_keys = [], set()
        for key in keys:
            original = original_for(originals, key)
            row = (spaces if key.target_type == TargetType.KNOWLEDGE_SPACE else files).get(int(key.target_id))
            space_id = (
                key.target_id
                if key.target_type == TargetType.KNOWLEDGE_SPACE
                else str(row.knowledge_id)
                if row
                else original.target_space_id
                if original
                else None
            )
            parent = spaces.get(int(space_id)) if space_id is not None else None
            if row is not None and (
                (key.target_type == TargetType.KNOWLEDGE_SPACE and row.type not in {0, 1, 3})
                or (key.target_type == TargetType.KNOWLEDGE_FILE and (parent is None or parent.type not in {0, 1, 3}))
            ):
                raise ResourceReferenceInvalidError(reason="knowledge_reference_target_unavailable")
            owner = row.tenant_id if row else original.target_tenant_id if original else None
            planned.append((key, row, original, owner, space_id))
            if owner is not None:
                tombstone_keys.add((key, owner))
                if key.target_type == TargetType.KNOWLEDGE_FILE and space_id is not None:
                    tombstone_keys.add((TargetKey("knowledge_space", space_id), owner))
        tombstones = {}
        model = ResourceReferenceTombstone
        for key, owner in sorted(tombstone_keys, key=lambda item: (*item[0].lock_order_key, item[1])):
            rows = await self._rows(
                session,
                select(model.operation_id, model.stage)
                .where(
                    model.tenant_id == owner,
                    model.target_tenant_id == owner,
                    model.target_type == key.target_type.value,
                    model.target_id == key.target_id,
                )
                .with_for_update(),
            )
            if rows:
                tombstones[key, owner] = DeletionEvidence(rows[0].operation_id, key, owner, rows[0].stage)
        await self.verifier.aassert_target_keys(
            session, scope, identity, target_keys, allowed_types=(TargetType.KNOWLEDGE_SPACE, TargetType.KNOWLEDGE_FILE)
        )
        return tuple(
            KnowledgeReadObservation(
                key,
                row is not None,
                owner,
                space_id,
                original,
                tombstones.get((key, owner)),
                tombstones.get((TargetKey("knowledge_space", space_id), owner))
                if key.target_type == TargetType.KNOWLEDGE_FILE and space_id is not None
                else None,
            )
            for key, row, original, owner, space_id in planned
        )
