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
from bisheng.resource_reference.application.contracts import DeletionEvidence, TargetType
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

    async def _models(self, session, ids, owners, *, lock):
        statement = (
            select(LLMModel.id, LLMModel.tenant_id, LLMModel.server_id)
            .where(
                LLMModel.tenant_id.in_(owners),
                LLMModel.id.in_(sorted(ids)),
            )
            .order_by(LLMModel.id)
        )
        rows = await self._rows(session, statement, lock=lock) if ids else ()
        return {row.id: row for row in rows}

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
        originals = tuple(
            row
            for row in originals
            if row.target_type == TargetType.MODEL.value and row.target_id in {key.target_id for key in keys}
        )
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
        server_rows = (
            await self._rows(
                session,
                select(LLMServer.id, LLMServer.tenant_id)
                .where(
                    LLMServer.id.in_(sorted(server_ids)),
                    LLMServer.tenant_id.in_(owners),
                )
                .order_by(LLMServer.id),
                lock=True,
            )
            if server_ids
            else ()
        )
        servers = {row.id: row for row in server_rows}
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
        result = []
        tombstone = ResourceReferenceTombstone
        for key in keys:
            row, original = models.get(int(key.target_id)), _original(originals, key)
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
            evidence = None
            if owner is not None:
                rows = await self._rows(
                    session,
                    select(tombstone.operation_id, tombstone.stage).where(
                        tombstone.tenant_id == owner,
                        tombstone.target_tenant_id == owner,
                        tombstone.target_type == TargetType.MODEL.value,
                        tombstone.target_id == key.target_id,
                    ),
                    lock=True,
                )
                if rows:
                    evidence = DeletionEvidence(rows[0].operation_id, key, owner, rows[0].stage)
            result.append(
                ModelReadObservation(
                    key, row is not None, owner, str(row.server_id) if row else None, original, evidence
                )
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
        statement = (
            select(LLMModel.id, LLMModel.tenant_id, LLMModel.server_id)
            .where(
                LLMModel.tenant_id.in_(owners),
                LLMModel.id.in_(sorted(ids)),
            )
            .order_by(LLMModel.id)
        )
        rows = self._rows_sync(session, statement, lock=lock) if ids else ()
        return {row.id: row for row in rows}

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
        originals = tuple(
            row
            for row in originals
            if row.target_type == TargetType.MODEL.value and row.target_id in {key.target_id for key in keys}
        )
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
        server_rows_sync = (
            self._rows_sync(
                session,
                select(LLMServer.id, LLMServer.tenant_id)
                .where(
                    LLMServer.id.in_(sorted(server_ids)),
                    LLMServer.tenant_id.in_(owners),
                )
                .order_by(LLMServer.id),
                lock=True,
            )
            if server_ids
            else ()
        )
        servers = {row.id: row for row in server_rows_sync}
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
        result = []
        tombstone = ResourceReferenceTombstone
        for key in keys:
            row, original = models.get(int(key.target_id)), _original(originals, key)
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
            evidence = None
            if owner is not None:
                rows = self._rows_sync(
                    session,
                    select(tombstone.operation_id, tombstone.stage).where(
                        tombstone.tenant_id == owner,
                        tombstone.target_tenant_id == owner,
                        tombstone.target_type == TargetType.MODEL.value,
                        tombstone.target_id == key.target_id,
                    ),
                    lock=True,
                )
                if rows:
                    evidence = DeletionEvidence(rows[0].operation_id, key, owner, rows[0].stage)
            result.append(
                ModelReadObservation(
                    key, row is not None, owner, str(row.server_id) if row else None, original, evidence
                )
            )
        self.verifier.assert_target_keys(session, scope, identity, target_keys, allowed_types=(TargetType.MODEL,))
        return ModelReadPlan(tenant_id, tuple(result), inherited_servers)
