"""Five-key original defaults in the caller's native SQL transaction."""

import json
from dataclasses import dataclass

from sqlalchemy import delete, select, update

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.services.default_reference_extractor import MODEL_DEFAULT_SCHEMAS
from bisheng.resource_reference.application.contracts import SourceKey, SourceType
from bisheng.resource_reference.application.source_contracts import canonical_payload_json


@dataclass(frozen=True, slots=True)
class ModelDefaultDisclosureRecord:
    id: int
    tenant_id: int
    key: str


@dataclass(frozen=True, slots=True)
class ModelDefaultRecord:
    id: int
    tenant_id: int
    key: str
    value: str | None

    @property
    def source_key(self):
        return SourceKey(self.tenant_id, SourceType.MODEL_DEFAULT, self.key, "current")

    @property
    def payload_json(self):
        try:
            return canonical_payload_json(json.loads(self.value)) if self.value else "{}"
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid") from error


@dataclass(frozen=True, slots=True)
class ResolvedModelDefault:
    request_tenant_id: int
    key: str
    own: ModelDefaultRecord | None
    source: ModelDefaultRecord | None
    inherited_from_root: bool
    fallback_blocked: bool

    @property
    def payload_json(self):
        return self.source.payload_json if self.source is not None else "{}"


class ModelDefaultRepository:
    async def alist_disclosure_rows(self, session, *, keys: tuple[str, ...]):
        tenant = _resolve_tenant_id()
        if (
            type(keys) is not tuple
            or len(keys) > 200
            or any(type(key) is not str or key not in MODEL_DEFAULT_SCHEMAS for key in keys)
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or not session.in_transaction()
        ):
            raise ReferenceCoverageNotReadyError(reason="default_disclosure_scope_invalid")
        if not keys:
            return ()
        model = TenantSystemModelConfig
        statement = select(model.id, model.tenant_id, model.key).where(
            model.tenant_id == tenant, model.key.in_(tuple(dict.fromkeys(keys)))
        )
        with session.no_autoflush, strict_tenant_filter():
            rows = tuple(ModelDefaultDisclosureRecord(*row) for row in (await session.execute(statement)))
        if len({row.key for row in rows}) != len(rows):
            raise ReferenceCoverageNotReadyError(reason="default_disclosure_duplicate_source")
        return rows

    @staticmethod
    def _context(key):
        tenant_id = _resolve_tenant_id()
        if (
            key not in MODEL_DEFAULT_SCHEMAS
            or type(tenant_id) is not int
            or tenant_id <= 0
            or is_tenant_filter_bypassed()
        ):
            raise ResourceReferenceInvalidError(reason="model_default_context_required")
        return tenant_id

    @staticmethod
    def _statement(key, *, root=False, lock=False):
        model = TenantSystemModelConfig
        statement = select(model.id, model.tenant_id, model.key, model.value).where(model.key == key)
        if root:
            statement = statement.where(model.tenant_id == ROOT_TENANT_ID)
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _topology(tenant_id, *, lock):
        statement = (
            select(Tenant.id, Tenant.parent_tenant_id, Tenant.share_default_to_children)
            .where(Tenant.id.in_(sorted({ROOT_TENANT_ID, tenant_id})))
            .order_by(Tenant.id)
        )
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _record(rows):
        return ModelDefaultRecord(*rows[0]) if rows else None

    @staticmethod
    def _read(session, statement, cross):
        with session.no_autoflush, bypass_tenant_filter() if cross else strict_tenant_filter():
            return tuple(session.execute(statement))

    @staticmethod
    async def _aread(session, statement, cross):
        with session.no_autoflush, bypass_tenant_filter() if cross else strict_tenant_filter():
            return tuple(await session.execute(statement))

    def _drive(self, session, plan):
        value = None
        while True:
            try:
                statement, cross = plan.send(value)
            except StopIteration as done:
                return done.value
            value = self._read(session, statement, cross)

    async def _adrive(self, session, plan):
        value = None
        while True:
            try:
                statement, cross = plan.send(value)
            except StopIteration as done:
                return done.value
            value = await self._aread(session, statement, cross)

    def get_own(self, session, key, *, for_update=False):
        self._context(key)
        return self._record(self._read(session, self._statement(key, lock=for_update), False))

    async def aget_own(self, session, key, *, for_update=False):
        self._context(key)
        return self._record(await self._aread(session, self._statement(key, lock=for_update), False))

    def _resolve(self, key, *, lock):
        tenant_id = self._context(key)
        topology = yield self._topology(tenant_id, lock=lock), True
        own = self._record((yield self._statement(key, lock=lock), False))
        if own is not None and own.value:
            return ResolvedModelDefault(tenant_id, key, own, own, False, False)
        if tenant_id == ROOT_TENANT_ID:
            return ResolvedModelDefault(tenant_id, key, own, None, False, False)
        root = self._record((yield self._statement(key, root=True, lock=lock), True))
        if root is None or not root.value:
            return ResolvedModelDefault(tenant_id, key, own, None, False, False)
        by_id = {row.id: row for row in topology}
        root_tenant, child = by_id.get(ROOT_TENANT_ID), by_id.get(tenant_id)
        inherited = bool(
            root_tenant and child and child.parent_tenant_id == ROOT_TENANT_ID and root_tenant.share_default_to_children
        )
        return ResolvedModelDefault(tenant_id, key, own, root if inherited else None, inherited, not inherited)

    def resolve(self, session, key, *, for_update=False):
        return self._drive(session, self._resolve(key, lock=for_update))

    async def aresolve(self, session, key, *, for_update=False):
        return await self._adrive(session, self._resolve(key, lock=for_update))

    def _lock(self, key):
        tenant_id = self._context(key)
        rows = yield self._topology(tenant_id, lock=True), True
        if tenant_id not in {row.id for row in rows}:
            raise ResourceReferenceInvalidError(reason="model_default_owner_missing")
        return self._record((yield self._statement(key, lock=True), False))

    def lock_root(self, session, key):
        return self._drive(session, self._lock(key))

    async def alock_root(self, session, key):
        return await self._adrive(session, self._lock(key))

    @staticmethod
    def _payload(value):
        try:
            return canonical_payload_json(json.loads(value))
        except (TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="model_default_configuration_invalid") from error

    @staticmethod
    def _where(tenant_id, key, row_id):
        model = TenantSystemModelConfig
        return model.id == row_id, model.tenant_id == tenant_id, model.key == key

    def put(self, session, key, value):
        tenant_id, value = self._context(key), self._payload(value)
        own = self.get_own(session, key, for_update=True)
        if own is None:
            row = TenantSystemModelConfig(tenant_id=tenant_id, key=key, value=value)
            session.add(row)
            session.flush()
            return ModelDefaultRecord(row.id, tenant_id, key, value)
        result = session.execute(
            update(TenantSystemModelConfig).where(*self._where(tenant_id, key, own.id)).values(value=value)
        )
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="model_default_changed")
        return ModelDefaultRecord(own.id, tenant_id, key, value)

    async def aput(self, session, key, value):
        tenant_id, value = self._context(key), self._payload(value)
        own = await self.aget_own(session, key, for_update=True)
        if own is None:
            row = TenantSystemModelConfig(tenant_id=tenant_id, key=key, value=value)
            session.add(row)
            await session.flush()
            return ModelDefaultRecord(row.id, tenant_id, key, value)
        result = await session.execute(
            update(TenantSystemModelConfig).where(*self._where(tenant_id, key, own.id)).values(value=value)
        )
        if result.rowcount != 1:
            raise KnowledgeOperationPlanConflictError(reason="model_default_changed")
        return ModelDefaultRecord(own.id, tenant_id, key, value)

    def delete_override(self, session, key):
        tenant_id = self._context(key)
        if tenant_id == ROOT_TENANT_ID:
            raise ResourceReferenceInvalidError(reason="model_default_root_cannot_inherit")
        own = self.get_own(session, key, for_update=True)
        if own is not None:
            session.execute(delete(TenantSystemModelConfig).where(*self._where(tenant_id, key, own.id)))

    async def adelete_override(self, session, key):
        tenant_id = self._context(key)
        if tenant_id == ROOT_TENANT_ID:
            raise ResourceReferenceInvalidError(reason="model_default_root_cannot_inherit")
        own = await self.aget_own(session, key, for_update=True)
        if own is not None:
            await session.execute(delete(TenantSystemModelConfig).where(*self._where(tenant_id, key, own.id)))
