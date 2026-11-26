"""Collect detached SQL deletion-reference facts without granting any action.

The caller supplies a clean, short native transaction. Selected-resource
qualification belongs before it; source disclosure belongs after SQL closes.
"""

from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
)
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteScope, DeleteSelection
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
    TransactionIdentity,
)
from bisheng.resource_reference.domain.repositories.reference_hint_repository import ReferenceHintRepository

Counts = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DeleteReferenceSlotFact:
    reference_id: int = field(repr=False)
    unit_index: int = field(repr=False)
    source: SourceKey = field(repr=False)
    slot_key: str = field(repr=False)
    target: TargetKey = field(repr=False)
    source_revision: int = field(repr=False)


@dataclass(frozen=True, slots=True)
class DeleteReferenceFacts:
    scope: DeleteScope = field(repr=False)
    references: tuple[DeleteReferenceSlotFact, ...] = field(repr=False)
    sources: tuple[SourceKey, ...] = field(repr=False)
    source_counts: Counts = field(repr=False)
    slot_counts: Counts = field(repr=False)
    unit_source_counts: tuple[Counts, ...] = field(repr=False)
    unit_slot_counts: tuple[Counts, ...] = field(repr=False)
    observed_source_tenant_ids: tuple[int, ...] = field(repr=False)
    coverage_epoch: int
    inventory_hash: str = field(repr=False)


def _counts(values) -> Counts:
    return tuple((kind.value, values.get(kind, 0)) for kind in SourceType)


def _source_counts(sources) -> Counts:
    values = dict.fromkeys(SourceType, 0)
    for source in sources:
        values[source.source_type] += 1
    return _counts(values)


class DirectDeleteReferenceQuery:
    def __init__(self, *, runtime=None, coverage_factory=None, scope_repository=None):
        self.scope = scope_repository if scope_repository is not None else KnowledgeSpaceDeleteRepository()

    @staticmethod
    def _context(session, space_id, selections):
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or type(space_id) is not int
            or space_id <= 0
            or type(selections) is not tuple
            or any(type(value) is not DeleteSelection for value in selections)
        ):
            raise ValueError("direct deletion facts require a native caller transaction and typed concrete selection")
        native = session.sync_session
        if native.new or native.dirty or native.deleted:
            raise ValueError("direct deletion facts require a clean caller session")
        return tenant, TransactionIdentity.capture(session)

    @staticmethod
    def _targets(scope):
        units = {}
        for index, unit in enumerate(scope.units):
            for ident in unit.resource_ids:
                raw = TargetType.KNOWLEDGE_FILE.value, str(ident)
                if raw in units:
                    raise KnowledgeOperationPlanConflictError(reason="delete_reference_unit_overlap")
                units[raw] = index
        keys = {raw: TargetKey(*raw) for raw in units}
        return units, keys, tuple(sorted(keys.values(), key=lambda key: key.lock_order_key))

    async def acollect(self, session, *, space_id, selections, operation_id=None):
        self._context(session, space_id, selections)
        scope = await self.scope.aread_delete_scope(session, space_id=space_id, selections=selections, for_update=False)
        units, _targets, keys = self._targets(scope)
        rows = await ReferenceHintRepository().aread(session, keys)
        return self.facts(scope, rows, units)

    @staticmethod
    def facts(scope, rows, units):
        references, sources = [], set()
        unit_sources = [set() for _ in scope.units]
        unit_slots = [dict.fromkeys(SourceType, 0) for _ in scope.units]
        slots = dict.fromkeys(SourceType, 0)
        for row in rows:
            try:
                source = SourceKey(row.tenant_id, row.source_type, row.source_id, row.source_version)
                target = TargetKey(row.target_type, row.target_id)
            except (TypeError, ValueError) as error:
                raise ReferenceCoverageNotReadyError(reason="malformed_reference_hint") from error
            index = units.get((row.target_type, row.target_id), 0)
            references.append(DeleteReferenceSlotFact(row.id, index, source, row.slot_key, target, row.source_revision))
            sources.add(source)
            slots[source.source_type] += 1
            if unit_sources:
                unit_sources[index].add(source)
                unit_slots[index][source.source_type] += 1
        return DeleteReferenceFacts(
            scope,
            tuple(references),
            tuple(
                sorted(
                    sources, key=lambda key: (key.tenant_id, key.source_type.value, key.source_id, key.source_version)
                )
            ),
            _source_counts(sources),
            _counts(slots),
            tuple(_source_counts(values) for values in unit_sources),
            tuple(_counts(values) for values in unit_slots),
            tuple(sorted({key.tenant_id for key in sources})),
            0,
            "",
        )
