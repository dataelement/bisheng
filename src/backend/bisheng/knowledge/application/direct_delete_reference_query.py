"""Collect detached SQL deletion-reference facts without granting any action.

The caller supplies a clean, short native transaction. Selected-resource
qualification belongs before it; source disclosure belongs after SQL closes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteScope, DeleteSelection
from bisheng.resource_reference.application.contracts import (
    ReferenceState,
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
    TransactionIdentity,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

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
    def __init__(
        self,
        *,
        runtime: ReferenceBindingRuntime,
        coverage_factory: Callable[[AsyncSession], CoverageRepository],
        scope_repository: KnowledgeSpaceDeleteRepository | None = None,
    ):
        if (
            not isinstance(runtime, ReferenceBindingRuntime)
            or not isinstance(runtime.repository, ReferenceRepository)
            or not isinstance(runtime.verifier, ReferenceTargetVerifier)
            or runtime.repository.verifier is not runtime.verifier
            or not callable(coverage_factory)
        ):
            raise TypeError("direct deletion facts require an actual same-issuer runtime and coverage factory")
        if scope_repository is not None and not isinstance(scope_repository, KnowledgeSpaceDeleteRepository):
            raise TypeError("direct deletion facts require the actual physical scope repository")
        self.runtime, self.coverage_factory = runtime, coverage_factory
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
    def _current(session, transaction, tenant):
        try:
            transaction.assert_current(session)
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="delete_reference_context_changed") from error
        current = get_current_tenant_id()
        if type(current) is not int or current != tenant or is_tenant_filter_bypassed():
            raise ResourceReferenceInvalidError(reason="delete_reference_context_changed")

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

    @staticmethod
    def _slot(row, units, targets, sources, seen, *, tenant_id, space_id):
        raw = row.target_type, row.target_id
        legacy = row.legacy_invalid_reason == "target_missing" and all(
            type(value) is str and value for value in (row.legacy_run_id, row.legacy_evidence_key)
        )
        legacy_fields = (row.legacy_invalid_reason, row.legacy_run_id, row.legacy_evidence_key)
        if (
            raw not in units
            or (not legacy and any(value is not None for value in legacy_fields))
            or (not legacy and (row.target_tenant_id != tenant_id or row.target_space_id != str(space_id)))
            or type(row.id) is not int
            or row.id <= 0
            or row.id in seen
            or type(row.source_revision) is not int
            or row.source_revision < 0
            or not isinstance(row.slot_key, str)
            or not 0 < len(row.slot_key) <= 192
        ):
            raise ReferenceCoverageNotReadyError(reason="delete_reference_inbound_invalid")
        try:
            key = SourceKey(row.tenant_id, row.source_type, row.source_id, row.source_version)
        except (TypeError, ValueError) as error:
            raise ReferenceCoverageNotReadyError(reason="delete_reference_inbound_invalid") from error
        source = sources.setdefault(key, key)
        seen.add(row.id)
        return DeleteReferenceSlotFact(row.id, units[raw], source, row.slot_key, targets[raw], row.source_revision)

    async def acollect(
        self, session: AsyncSession, *, space_id: int, selections: tuple[DeleteSelection, ...]
    ) -> DeleteReferenceFacts:
        tenant, transaction = self._context(session, space_id, selections)
        with session.no_autoflush:
            coverage = self.coverage_factory(session)
            if not isinstance(coverage, CoverageRepository):
                raise ReferenceCoverageNotReadyError(reason="delete_reference_coverage_unconfigured")
            before = await coverage.arequire_global_ready()
            await coverage.arequire_ready(tenant_id=tenant)
            self._current(session, transaction, tenant)
            scope = await self.scope.aread_delete_scope(
                session, space_id=space_id, selections=selections, for_update=False
            )
            self._current(session, transaction, tenant)
            units, target_by_raw, targets = self._targets(scope)
            references, sources, seen = [], {}, set()
            unit_sources = [set() for _ in scope.units]
            unit_slots = [dict.fromkeys(SourceType, 0) for _ in scope.units]
            total_slots = dict.fromkeys(SourceType, 0)
            if targets:
                receipts = await self.runtime.verifier.averify_owner_targets(session, targets)
                if (
                    len(receipts) != len(targets)
                    or {receipt.target.key for receipt in receipts} != set(targets)
                    or any(
                        receipt.target.state != ReferenceState.VALID
                        or receipt.target.target_tenant_id != tenant
                        or receipt.target.target_space_id != str(space_id)
                        for receipt in receipts
                    )
                ):
                    raise ResourceReferenceInvalidError(reason="delete_reference_target_unavailable")
                owner_scope = self.runtime.repository.target_owner_scope(session, receipts)
                async for page in self.runtime.repository.aiter_inbound_for_owner_pages(session, owner_scope):
                    for row in page:
                        fact = self._slot(row, units, target_by_raw, sources, seen, tenant_id=tenant, space_id=space_id)
                        references.append(fact)
                        unit_sources[fact.unit_index].add(fact.source)
                        unit_slots[fact.unit_index][fact.source.source_type] += 1
                        total_slots[fact.source.source_type] += 1
            observed = tuple(sorted({key.tenant_id for key in sources}))
            await coverage.arequire_global_ready(
                observed_source_tenant_ids=observed,
                expected_epoch=before.coverage_epoch,
                expected_inventory_hash=before.tenant_inventory_hash,
            )
            await coverage.arequire_ready(tenant_id=tenant)
            self._current(session, transaction, tenant)
            ordered_sources = tuple(
                sorted(
                    sources, key=lambda key: (key.tenant_id, key.source_type.value, key.source_id, key.source_version)
                )
            )
            return DeleteReferenceFacts(
                scope,
                tuple(references),
                ordered_sources,
                _source_counts(ordered_sources),
                _counts(total_slots),
                tuple(_source_counts(values) for values in unit_sources),
                tuple(_counts(values) for values in unit_slots),
                observed,
                before.coverage_epoch,
                before.tenant_inventory_hash,
            )
