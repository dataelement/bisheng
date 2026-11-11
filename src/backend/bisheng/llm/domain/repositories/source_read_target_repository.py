"""Model/server current-read plans use the authorized source's real tenant."""

from dataclasses import dataclass

from sqlalchemy import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.reference_target_repository import (
    DEFAULT_SCHEMAS,
    ModelReferenceTargetRepository,
    _original,
)
from bisheng.resource_reference.application.contracts import DeletionEvidence, TargetKey, TargetType
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository


@dataclass(frozen=True, slots=True)
class ModelReadObservation:
    key: object
    exists: bool
    target_tenant_id: int | None
    model_server_id: str | None
    original: object | None
    deletion: DeletionEvidence | None


@dataclass(frozen=True, slots=True)
class ModelReadPlan:
    tenant_id: int
    observations: tuple[ModelReadObservation, ...]
    inherited_server_ids: frozenset[int]


class ModelSourceReadTargetRepository:
    def __init__(self, verifier):
        self.verifier = verifier
        self.sources = SourceReadRepository(verifier)

    @staticmethod
    async def _rows(session, statement, *, lock=False):
        with session.no_autoflush, bypass_tenant_filter():
            return tuple(await session.execute(statement.with_for_update() if lock else statement))

    @staticmethod
    def _business_statements(model, ids, owners):
        columns = (model.id, model.tenant_id, model.server_id) if model is LLMModel else (model.id, model.tenant_id)
        ordered = sorted(ids)
        for start in range(0, len(ordered), 200):
            yield (
                select(*columns)
                .where(model.tenant_id.in_(owners), model.id.in_(ordered[start : start + 200]))
                .order_by(model.id)
            )

    async def _models(self, session, ids, owners, *, lock):
        found = {}
        for statement in self._business_statements(LLMModel, ids, owners):
            found.update((row.id, row) for row in await self._rows(session, statement, lock=lock))
        return found

    @staticmethod
    def _originals_by_key(originals, keys):
        selected = {(key.target_type.value, key.target_id) for key in keys}
        found = {}
        for original in originals:
            raw_key = original.target_type, original.target_id
            if raw_key in selected:
                found.setdefault(raw_key, []).append(original)
        return found

    @staticmethod
    def _tombstone_statements(entries):
        model = ResourceReferenceTombstone
        for statement in ModelReferenceTargetRepository._tombstone_statements(entries):
            yield statement.with_only_columns(
                model.operation_id,
                model.stage,
                model.target_type,
                model.target_id,
                model.target_tenant_id,
                model.tenant_id,
            )

    @staticmethod
    def _add_tombstones(rows, expected, found):
        for row in rows:
            try:
                entry = TargetKey(row.target_type, row.target_id), row.target_tenant_id
            except (TypeError, ValueError) as error:
                raise ResourceReferenceInvalidError(reason="model_reference_tombstone_result_invalid") from error
            if (
                entry not in expected
                or entry in found
                or row.target_id != entry[0].target_id
                or row.tenant_id != entry[1]
            ):
                raise ResourceReferenceInvalidError(reason="model_reference_tombstone_result_invalid")
            found[entry] = DeletionEvidence(row.operation_id, entry[0], entry[1], row.stage)

    async def _topology(self, session, tenant_id, *, lock):
        rows = await self._rows(
            session,
            select(Tenant.id, Tenant.parent_tenant_id, Tenant.share_default_to_children)
            .where(
                Tenant.id.in_(sorted({ROOT_TENANT_ID, tenant_id})),
            )
            .order_by(Tenant.id),
            lock=lock,
        )
        return {row.id: row for row in rows}

    async def _configs(self, session, tenant_id, *, lock):
        return await self._rows(
            session,
            select(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key, TenantSystemModelConfig.value)
            .where(
                TenantSystemModelConfig.tenant_id.in_(sorted({ROOT_TENANT_ID, tenant_id})),
                TenantSystemModelConfig.key.in_(tuple(DEFAULT_SCHEMAS)),
            )
            .order_by(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key),
            lock=lock,
        )

    async def alock_targets(self, session, scope, target_keys, *, identity, transient=False):
        snapshot = await self.verifier.aassert_target_keys(
            session, scope, identity, target_keys, allowed_types=(TargetType.MODEL,)
        )
        if transient:
            await self.verifier.aget_transient_snapshot(session, scope, identity)
            tenant_id, originals = snapshot.owner_tenant_id, ()
        else:
            await self.verifier.aget_source_snapshot(session, scope, identity)
            tenant_id = snapshot.source_key.tenant_id
            originals = (await self.sources.aread_source(session, scope, identity)).references
        keys = tuple(sorted(target_keys, key=lambda key: key.lock_order_key))
        originals_by_key = self._originals_by_key(originals, keys)
        originals = tuple(row for bucket in originals_by_key.values() for row in bucket)
        owners = tuple(sorted({tenant_id, ROOT_TENANT_ID}))
        if any(row.target_tenant_id not in (*owners, None) or row.target_space_id is not None for row in originals):
            raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
        ids = {int(key.target_id) for key in keys}
        candidates = await self._models(session, ids, owners, lock=False)
        sharing = any(row.tenant_id != tenant_id for row in candidates.values())
        topology = await self._topology(session, tenant_id, lock=False) if sharing else {}
        configs = await self._configs(session, tenant_id, lock=False) if sharing else ()
        inherited_ids = ModelReferenceTargetRepository._inherited_ids(topology, configs, tenant_id)
        all_ids = ids | inherited_ids
        candidates = await self._models(session, all_ids, owners, lock=False)
        mapping = {row.id: row.server_id for row in candidates.values()}
        server_ids = set(mapping.values())
        servers = {}
        for statement in self._business_statements(LLMServer, server_ids, owners):
            servers.update((row.id, row) for row in await self._rows(session, statement, lock=True))
        models = await self._models(session, all_ids, owners, lock=True)
        if {row.id: row.server_id for row in models.values()} != mapping:
            raise KnowledgeOperationPlanConflictError(reason="reference_read_target_plan_changed")
        if sharing:
            topology = await self._topology(session, tenant_id, lock=True)
            configs = await self._configs(session, tenant_id, lock=True)
            if ModelReferenceTargetRepository._inherited_ids(topology, configs, tenant_id) != inherited_ids:
                raise KnowledgeOperationPlanConflictError(reason="reference_read_target_plan_changed")
        inherited_servers = frozenset(
            row.server_id
            for row in models.values()
            if row.id in inherited_ids
            and row.tenant_id == ROOT_TENANT_ID
            and row.server_id in servers
            and servers[row.server_id].tenant_id == ROOT_TENANT_ID
        )
        planned = []
        for key in keys:
            row, original = (
                models.get(int(key.target_id)),
                _original(originals_by_key.get((key.target_type.value, key.target_id), ()), key),
            )
            server = servers.get(row.server_id) if row else None
            if row is not None and (
                server is None
                or server.tenant_id != row.tenant_id
                or (
                    row.tenant_id != tenant_id
                    and (
                        row.tenant_id != ROOT_TENANT_ID
                        or not ModelReferenceTargetRepository._child(topology, tenant_id)
                    )
                )
            ):
                raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
            owner = row.tenant_id if row else original.target_tenant_id if original else None
            planned.append((key, row, original, owner))
        entries = {(key, owner) for key, _, _, owner in planned if owner is not None}
        tombstones = {}
        for statement in self._tombstone_statements(entries):
            self._add_tombstones(await self._rows(session, statement), entries, tombstones)
        result = tuple(
            ModelReadObservation(
                key,
                row is not None,
                owner,
                str(row.server_id) if row else None,
                original,
                tombstones.get((key, owner)),
            )
            for key, row, original, owner in planned
        )
        await self.verifier.aassert_target_keys(
            session, scope, identity, target_keys, allowed_types=(TargetType.MODEL,)
        )
        return ModelReadPlan(tenant_id, tuple(result), inherited_servers)

    @staticmethod
    def _rows_sync(session, statement, *, lock=False):
        with session.no_autoflush, bypass_tenant_filter():
            return tuple(session.execute(statement.with_for_update() if lock else statement))

    def _models_sync(self, session, ids, owners, *, lock):
        found = {}
        for statement in self._business_statements(LLMModel, ids, owners):
            found.update((row.id, row) for row in self._rows_sync(session, statement, lock=lock))
        return found

    def _topology_sync(self, session, tenant_id, *, lock):
        rows = self._rows_sync(
            session,
            select(Tenant.id, Tenant.parent_tenant_id, Tenant.share_default_to_children)
            .where(
                Tenant.id.in_(sorted({ROOT_TENANT_ID, tenant_id})),
            )
            .order_by(Tenant.id),
            lock=lock,
        )
        return {row.id: row for row in rows}

    def _configs_sync(self, session, tenant_id, *, lock):
        return self._rows_sync(
            session,
            select(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key, TenantSystemModelConfig.value)
            .where(
                TenantSystemModelConfig.tenant_id.in_(sorted({ROOT_TENANT_ID, tenant_id})),
                TenantSystemModelConfig.key.in_(tuple(DEFAULT_SCHEMAS)),
            )
            .order_by(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key),
            lock=lock,
        )

    def lock_targets(self, session, scope, target_keys, *, identity):
        snapshot = self.verifier.assert_target_keys(
            session, scope, identity, target_keys, allowed_types=(TargetType.MODEL,)
        )
        self.verifier.get_source_snapshot(session, scope, identity)
        tenant_id = snapshot.source_key.tenant_id
        originals = self.sources.read_source(session, scope, identity).references
        keys = tuple(sorted(target_keys, key=lambda key: key.lock_order_key))
        originals_by_key = self._originals_by_key(originals, keys)
        originals = tuple(row for bucket in originals_by_key.values() for row in bucket)
        owners = tuple(sorted({tenant_id, ROOT_TENANT_ID}))
        if any(row.target_tenant_id not in (*owners, None) or row.target_space_id is not None for row in originals):
            raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
        ids = {int(key.target_id) for key in keys}
        candidates = self._models_sync(session, ids, owners, lock=False)
        sharing = any(row.tenant_id != tenant_id for row in candidates.values())
        topology = self._topology_sync(session, tenant_id, lock=False) if sharing else {}
        configs = self._configs_sync(session, tenant_id, lock=False) if sharing else ()
        inherited_ids = ModelReferenceTargetRepository._inherited_ids(topology, configs, tenant_id)
        all_ids = ids | inherited_ids
        candidates = self._models_sync(session, all_ids, owners, lock=False)
        mapping = {row.id: row.server_id for row in candidates.values()}
        server_ids = set(mapping.values())
        servers = {}
        for statement in self._business_statements(LLMServer, server_ids, owners):
            servers.update((row.id, row) for row in self._rows_sync(session, statement, lock=True))
        models = self._models_sync(session, all_ids, owners, lock=True)
        if {row.id: row.server_id for row in models.values()} != mapping:
            raise KnowledgeOperationPlanConflictError(reason="reference_read_target_plan_changed")
        if sharing:
            topology = self._topology_sync(session, tenant_id, lock=True)
            configs = self._configs_sync(session, tenant_id, lock=True)
            if ModelReferenceTargetRepository._inherited_ids(topology, configs, tenant_id) != inherited_ids:
                raise KnowledgeOperationPlanConflictError(reason="reference_read_target_plan_changed")
        inherited_servers = frozenset(
            row.server_id
            for row in models.values()
            if row.id in inherited_ids
            and row.tenant_id == ROOT_TENANT_ID
            and row.server_id in servers
            and servers[row.server_id].tenant_id == ROOT_TENANT_ID
        )
        planned = []
        for key in keys:
            row, original = (
                models.get(int(key.target_id)),
                _original(originals_by_key.get((key.target_type.value, key.target_id), ()), key),
            )
            server = servers.get(row.server_id) if row else None
            if row is not None and (
                server is None
                or server.tenant_id != row.tenant_id
                or (
                    row.tenant_id != tenant_id
                    and (
                        row.tenant_id != ROOT_TENANT_ID
                        or not ModelReferenceTargetRepository._child(topology, tenant_id)
                    )
                )
            ):
                raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
            owner = row.tenant_id if row else original.target_tenant_id if original else None
            planned.append((key, row, original, owner))
        entries = {(key, owner) for key, _, _, owner in planned if owner is not None}
        tombstones = {}
        for statement in self._tombstone_statements(entries):
            self._add_tombstones(self._rows_sync(session, statement), entries, tombstones)
        result = tuple(
            ModelReadObservation(
                key,
                row is not None,
                owner,
                str(row.server_id) if row else None,
                original,
                tombstones.get((key, owner)),
            )
            for key, row, original, owner in planned
        )
        self.verifier.assert_target_keys(session, scope, identity, target_keys, allowed_types=(TargetType.MODEL,))
        return ModelReadPlan(tenant_id, tuple(result), inherited_servers)
