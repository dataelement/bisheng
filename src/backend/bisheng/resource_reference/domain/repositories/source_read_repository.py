"""Exact-source read projections under privately issued SourceOwner authority.

The short bypass covers only explicit tenant/type/root/version predicates.
No managed cross-tenant ORM object enters the caller's identity map.
"""

from dataclasses import dataclass, fields

from sqlalchemy import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.resource_reference.application.contracts import ROOT_GUARD_VERSION
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


@dataclass(frozen=True, slots=True)
class SourceSetReadFact:
    tenant_id: int
    source_type: str
    source_id: str
    source_version: str
    record_kind: str
    source_revision: int
    extractor_version: str
    digest: str
    effective: bool
    ready: bool


@dataclass(frozen=True, slots=True)
class ReferenceReadRow:
    tenant_id: int
    source_type: str
    source_id: str
    source_version: str
    slot_key: str
    target_type: str
    target_id: str
    target_tenant_id: int | None
    target_space_id: str | None
    source_revision: int
    legacy_invalid_reason: str | None
    legacy_run_id: str | None
    legacy_evidence_key: str | None


@dataclass(frozen=True, slots=True)
class SourceIndexReadSnapshot:
    root: SourceSetReadFact | None
    source: SourceSetReadFact | None
    references: tuple[ReferenceReadRow, ...]


class SourceReadRepository:
    def __init__(self, verifier: SourceReadVerifier):
        if not isinstance(verifier, SourceReadVerifier):
            raise TypeError("scoped reads require the actual source authority")
        self.verifier = verifier

    @staticmethod
    def _statement(model, fact_type, key, version, for_update):
        statement = select(*(getattr(model, field.name) for field in fields(fact_type))).where(
            model.tenant_id == key.tenant_id,
            model.source_type == key.source_type.value,
            model.source_id == key.source_id,
            model.source_version == version,
        )
        if model is BusinessResourceReference:
            statement = statement.order_by(model.slot_key, model.target_type, model.target_id)
        return statement.with_for_update() if for_update else statement

    @staticmethod
    async def _rows(session, statement, fact_type):
        with session.no_autoflush, bypass_tenant_filter():
            result = await session.execute(statement)
            return tuple(fact_type(**row._mapping) for row in result)

    async def aread_source(self, session, scope, identity, *, for_update=False):
        snapshot = await self.verifier.aget_source_snapshot(session, scope, identity)
        key = snapshot.source_key
        root = await self._rows(
            session,
            self._statement(BusinessReferenceSet, SourceSetReadFact, key, ROOT_GUARD_VERSION, for_update),
            SourceSetReadFact,
        )
        source = await self._rows(
            session,
            self._statement(BusinessReferenceSet, SourceSetReadFact, key, key.source_version, for_update),
            SourceSetReadFact,
        )
        rows = await self._rows(
            session,
            self._statement(BusinessResourceReference, ReferenceReadRow, key, key.source_version, for_update),
            ReferenceReadRow,
        )
        await self.verifier.aget_source_snapshot(session, scope, identity)
        return SourceIndexReadSnapshot(root[0] if root else None, source[0] if source else None, rows)
