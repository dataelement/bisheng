"""Uncached catalog columns and one ordered physical lock plan.

The caller owns the Session and transaction. Root reads are exact projections;
no ORM entity, provider credential, tenant-context rewrite or DAO is involved.
"""

from dataclasses import dataclass

from sqlalchemy import or_, select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.reference_target_repository import DEFAULT_SCHEMAS, ModelReferenceTargetRepository


@dataclass(frozen=True, slots=True)
class CatalogServer:
    id: int
    tenant_id: int
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class CatalogModel:
    id: int
    tenant_id: int
    server_id: int
    model_name: str
    model_type: str
    online: bool


@dataclass(frozen=True, slots=True)
class CatalogTenant:
    id: int
    parent_tenant_id: int | None
    share_default_to_children: int


@dataclass(frozen=True, slots=True)
class CatalogConfig:
    tenant_id: int
    key: str
    value: str | None


@dataclass(frozen=True, slots=True)
class NameCatalog:
    tenant_id: int
    topology: tuple[CatalogTenant, ...]
    configs: tuple[CatalogConfig, ...]
    servers: tuple[CatalogServer, ...]
    models: tuple[CatalogModel, ...]
    visible_server_ids: frozenset[int]
    inherited_model_ids: frozenset[int]


class ModelNameResolutionRepository:
    @staticmethod
    def _tenant(tenant_id):
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or _resolve_tenant_id() != tenant_id
            or is_tenant_filter_bypassed()
        ):
            raise ResourceReferenceInvalidError(reason="model_name_tenant_mismatch")

    @staticmethod
    async def _rows(session, statement, cls, *, lock=False):
        with session.no_autoflush, bypass_tenant_filter():
            result = await session.execute(statement.with_for_update() if lock else statement)
            return tuple(cls(*row) for row in result)

    async def _topology(self, session, tenant_id, *, lock=False):
        return await self._rows(
            session,
            select(
                Tenant.id,
                Tenant.parent_tenant_id,
                Tenant.share_default_to_children,
            )
            .where(Tenant.id.in_(sorted({ROOT_TENANT_ID, tenant_id})))
            .order_by(Tenant.id),
            CatalogTenant,
            lock=lock,
        )

    async def _configs(self, session, tenant_id, *, lock=False):
        return await self._rows(
            session,
            select(
                TenantSystemModelConfig.tenant_id,
                TenantSystemModelConfig.key,
                TenantSystemModelConfig.value,
            )
            .where(
                TenantSystemModelConfig.tenant_id.in_(sorted({ROOT_TENANT_ID, tenant_id})),
                TenantSystemModelConfig.key.in_(tuple(DEFAULT_SCHEMAS)),
            )
            .order_by(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key),
            CatalogConfig,
            lock=lock,
        )

    async def _models(self, session, tenant_id, ids, server_ids, *, lock=False):
        if not ids and not server_ids:
            return ()
        return await self._rows(
            session,
            select(
                LLMModel.id,
                LLMModel.tenant_id,
                LLMModel.server_id,
                LLMModel.model_name,
                LLMModel.model_type,
                LLMModel.online,
            )
            .where(
                LLMModel.tenant_id.in_(sorted({ROOT_TENANT_ID, tenant_id})),
                or_(LLMModel.id.in_(sorted(ids)), LLMModel.server_id.in_(sorted(server_ids))),
            )
            .order_by(LLMModel.id),
            CatalogModel,
            lock=lock,
        )

    async def _servers(self, session, tenant_id, root_ids, *, lock=False):
        return await self._rows(
            session,
            select(
                LLMServer.id,
                LLMServer.tenant_id,
                LLMServer.name,
                LLMServer.type,
            )
            .where(
                or_(
                    LLMServer.tenant_id == tenant_id,
                    (LLMServer.tenant_id == ROOT_TENANT_ID) & LLMServer.id.in_(sorted(root_ids)),
                )
            )
            .order_by(LLMServer.id),
            CatalogServer,
            lock=lock,
        )

    async def _catalog(self, session, tenant_id, shared_ids, frozen_models, *, lock=False):
        self._tenant(tenant_id)
        topology = await self._topology(session, tenant_id)
        configs = await self._configs(session, tenant_id)
        topo = {row.id: row for row in topology}
        inherited = ModelReferenceTargetRepository._inherited_ids(topo, configs, tenant_id)
        frozen_ids = {item.model_id for item in frozen_models}
        dependencies = await self._models(session, tenant_id, inherited | frozen_ids, ())
        dependency_by_id = {row.id: row for row in dependencies}
        for item in frozen_models:
            row = dependency_by_id.get(item.model_id)
            if row is None or row.server_id != item.server_id:
                raise ResourceReferenceInvalidError(reason="model_name_frozen_identity_unavailable")
        inherited_servers = {
            row.server_id for row in dependencies if row.id in inherited and row.tenant_id == ROOT_TENANT_ID
        }
        child = tenant_id != ROOT_TENANT_ID and ModelReferenceTargetRepository._child(topo, tenant_id)
        root_visible = set(shared_ids) | inherited_servers if child else set()
        frozen_servers = {
            row.server_id for row in dependencies if row.id in frozen_ids and row.tenant_id == ROOT_TENANT_ID
        }
        servers = await self._servers(session, tenant_id, root_visible | frozen_servers, lock=lock)
        visible = frozenset(row.id for row in servers if row.tenant_id == tenant_id or row.id in root_visible)
        models = await self._models(session, tenant_id, inherited | frozen_ids, visible, lock=lock)
        if lock:
            locked_topology = await self._topology(session, tenant_id, lock=True)
            locked_configs = await self._configs(session, tenant_id, lock=True)
            if locked_topology != topology or locked_configs != configs:
                raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        server_by_id = {row.id: row for row in servers}
        for row in models:
            server = server_by_id.get(row.server_id)
            if server is None or server.tenant_id != row.tenant_id:
                raise ResourceReferenceInvalidError(reason="model_name_provider_owner_mismatch")
        return NameCatalog(tenant_id, topology, configs, servers, models, visible, inherited)

    async def aprepare_catalog(self, session, tenant_id, shared_ids, frozen_models):
        candidate = await self._catalog(session, tenant_id, shared_ids, frozen_models)
        try:
            locked = await self._catalog(session, tenant_id, shared_ids, frozen_models, lock=True)
        except ResourceReferenceInvalidError as error:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed") from error
        if candidate != locked:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        return locked

    async def arevalidate_catalog(self, session, expected, shared_ids, frozen_models):
        self._tenant(expected.tenant_id)
        # The first locking catalog scan covers the complete own-server and
        # visible-server model ranges. Revalidation never locks newly found
        # identities: mismatch requires the caller to roll back the transaction.
        try:
            current = await self._catalog(session, expected.tenant_id, shared_ids, frozen_models)
        except ResourceReferenceInvalidError as error:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed") from error
        if current != expected:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        server_ids = {row.id for row in expected.servers}
        model_ids = {row.id for row in expected.models}
        if server_ids:
            servers = await self._rows(
                session,
                select(
                    LLMServer.id,
                    LLMServer.tenant_id,
                    LLMServer.name,
                    LLMServer.type,
                )
                .where(LLMServer.id.in_(sorted(server_ids)))
                .order_by(LLMServer.id),
                CatalogServer,
                lock=True,
            )
            if servers != expected.servers:
                raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        models = await self._models(session, expected.tenant_id, model_ids, (), lock=True)
        if models != expected.models:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        topology = await self._topology(session, expected.tenant_id, lock=True)
        configs = await self._configs(session, expected.tenant_id, lock=True)
        if topology != expected.topology or configs != expected.configs:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        return current
