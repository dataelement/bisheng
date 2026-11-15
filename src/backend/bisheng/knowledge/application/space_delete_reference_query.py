"""Whole-space inbound facts, including saved direct references to its contents."""

from dataclasses import dataclass, field

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.knowledge.application.direct_delete_reference_query import (
    Counts,
    DirectDeleteReferenceQuery,
    _counts,
    _source_counts,
)
from bisheng.knowledge.domain.repositories.space_delete_scope_repository import SpaceDeleteScopeRepository
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteScope
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
)
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository


@dataclass(frozen=True, slots=True)
class SpaceReferenceFacts:
    scope: DeleteScope = field(repr=False)
    references: tuple = field(repr=False)
    sources: tuple[SourceKey, ...] = field(repr=False)
    source_counts: Counts = field(repr=False)
    slot_counts: Counts = field(repr=False)
    observed_source_tenant_ids: tuple[int, ...] = field(repr=False)
    coverage_epoch: int
    inventory_hash: str = field(repr=False)


class SpaceDeleteReferenceQuery(DirectDeleteReferenceQuery):
    def __init__(self, *, runtime, coverage_factory):
        super().__init__(
            runtime=runtime, coverage_factory=coverage_factory, scope_repository=SpaceDeleteScopeRepository()
        )

    async def acollect_space(self, session, *, space_id, operation_id=None):
        tenant, transaction = self._context(session, space_id, ())
        with session.no_autoflush:
            coverage = self.coverage_factory(session)
            if not isinstance(coverage, CoverageRepository):
                raise ReferenceCoverageNotReadyError(reason="space_reference_coverage_unconfigured")
            before = await coverage.arequire_global_ready()
            await coverage.arequire_ready(tenant_id=tenant)
            self._current(session, transaction, tenant)
            scope = await self.scope.aread_space_scope(session, space_id=space_id)
            self._current(session, transaction, tenant)
            root = TargetKey(TargetType.KNOWLEDGE_SPACE, str(space_id))
            receipts = await self.runtime.verifier.averify_owner_targets(session, (root,))
            self._valid(receipts, tenant, space_id, operation_id)
            owner_scope = self.runtime.repository.target_owner_scope(session, receipts)
            # Children are verified once as a union, never once per inbound row.
            children = tuple(TargetKey(TargetType.KNOWLEDGE_FILE, row.id) for row in scope.resources)
            if children:
                self._valid(
                    await self.runtime.verifier.averify_owner_targets(session, children), tenant, space_id, operation_id
                )
            references, sources, seen, units, targets = [], {}, set(), {}, {}
            physical = {str(row.id) for row in scope.resources}
            slots = dict.fromkeys(SourceType, 0)
            async for page in self.runtime.repository.aiter_inbound_for_owner_pages(
                session, owner_scope, include_space_contents=True
            ):
                self._current(session, transaction, tenant)
                for row in page:
                    raw = row.target_type, row.target_id
                    if raw != (root.target_type.value, root.target_id) and (
                        row.target_type != TargetType.KNOWLEDGE_FILE.value or row.target_space_id != str(space_id)
                    ):
                        raise ReferenceCoverageNotReadyError(reason="space_reference_inbound_target_invalid")
                    if (
                        row.target_type == TargetType.KNOWLEDGE_FILE.value
                        and row.target_id not in physical
                        and row.legacy_invalid_reason is None
                    ):
                        raise ReferenceCoverageNotReadyError(reason="space_reference_target_missing_without_evidence")
                    units[raw], targets[raw] = 0, TargetKey(*raw)
                    fact = self._slot(row, units, targets, sources, seen, tenant_id=tenant, space_id=space_id)
                    references.append(fact)
                    slots[fact.source.source_type] += 1
            observed = tuple(sorted({key.tenant_id for key in sources}))
            await coverage.arequire_global_ready(
                observed_source_tenant_ids=observed,
                expected_epoch=before.coverage_epoch,
                expected_inventory_hash=before.tenant_inventory_hash,
            )
            await coverage.arequire_ready(tenant_id=tenant)
            self._current(session, transaction, tenant)
            return SpaceReferenceFacts(
                scope,
                tuple(references),
                tuple(
                    sorted(
                        sources,
                        key=lambda key: (key.tenant_id, key.source_type.value, key.source_id, key.source_version),
                    )
                ),
                _source_counts(sources),
                _counts(slots),
                observed,
                before.coverage_epoch,
                before.tenant_inventory_hash,
            )

    @staticmethod
    def _valid(receipts, tenant, space_id, operation_id=None):
        if any(
            not DirectDeleteReferenceQuery._available(receipt.target, operation_id)
            or receipt.target.target_tenant_id != tenant
            or receipt.target.target_space_id != str(space_id)
            for receipt in receipts
        ):
            raise ResourceReferenceInvalidError(reason="space_reference_target_unavailable")
