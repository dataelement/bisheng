"""Bounded original SQL facts for the explicit F118 operational inventory.

These rows grant no Source/target authority or Coverage readiness. The caller
owns the native transaction, consumes all pages and freezes closed artifacts;
raw configurations remain in memory and must never be serialized as artifacts.
"""

import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Generic, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.database.models.flow import Flow, FlowType
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_name_resolution_repository import CatalogModel, CatalogServer
from bisheng.llm.domain.services.default_reference_extractor import MODEL_DEFAULT_SCHEMAS

T = TypeVar("T")


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"unification_inventory_{reason}")


@dataclass(frozen=True, slots=True)
class InventoryPage(Generic[T]):
    items: tuple[T, ...]
    next_after: int | str | None


@dataclass(frozen=True, slots=True)
class TenantRow:
    id: int
    parent_tenant_id: int | None
    status: str
    share_default_to_children: int


@dataclass(frozen=True, slots=True)
class WorkflowRootRow:
    id: str
    tenant_id: int
    user_id: int | None
    flow_type: int
    status: int | None
    is_delete: int
    update_time: datetime | None
    data_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class WorkflowVersionRow:
    id: int
    flow_id: str
    tenant_id: int
    flow_type: int | None
    is_current: int | None
    is_delete: int | None
    update_time: datetime | None
    data_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AppRootRow:
    id: str
    tenant_id: int
    owner_user_id: int
    state: str
    current_version_id: str | None
    pending_version_id: str | None
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class AppVersionRow:
    id: str
    app_id: str
    tenant_id: int
    version_no: int
    kind: str
    terminal_state: str | None
    update_time: datetime | None
    capabilities_json: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssistantRow:
    id: str
    tenant_id: int
    user_id: int
    status: int
    is_delete: int
    update_time: datetime | None
    model_name: str


@dataclass(frozen=True, slots=True)
class AssistantLinkRow:
    id: int
    assistant_id: str
    tenant_id: int
    knowledge_id: int | None
    tool_id: int | None
    flow_id: str | None
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class ChannelRow:
    id: str
    tenant_id: int
    user_id: int
    is_released: bool
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class ChannelSyncRow:
    id: str
    channel_id: str
    tenant_id: int
    sub_channel_name: str | None
    knowledge_space_id: str
    folder_id: str | None
    is_enabled: bool
    user_id: int
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeRow:
    id: int
    tenant_id: int
    type: int
    name: str
    user_id: int | None
    state: int | None
    is_released: bool
    auth_type: str
    is_shared: bool
    model: str | None
    model_transition_json: str | None = field(repr=False)
    model_config_revision: int
    index_generation: str | None
    index_name: str | None
    collection_name: str | None
    processing_config_version: int
    metadata_schema_revision: int
    migration_origin: str | None
    update_time: datetime | None


@dataclass(frozen=True, slots=True)
class DefaultRow:
    id: int
    tenant_id: int
    key: str
    value: str | None = field(repr=False)
    update_time: datetime | None


def _scope(session):
    tenant = get_current_tenant_id()
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or type(tenant) is not int
        or tenant <= 0
        or is_tenant_filter_bypassed()
    ):
        _blocked("native_transaction_scope_required")
    return tenant


def _text(value):
    return isinstance(value, str) and bool(value) and len(value) <= 64 and "\x00" not in value


def _pagination(after_id, limit, kind):
    if type(limit) is not int or not 1 <= limit <= 200:
        _blocked("invalid_limit")
    if after_id is not None and (
        (kind is int and (type(after_id) is not int or after_id <= 0)) or (kind is str and not _text(after_id))
    ):
        _blocked("invalid_cursor")


def _parent_ids(values):
    if type(values) is not tuple or any(not _text(value) for value in values):
        _blocked("invalid_parent_batch")
    result = tuple(sorted(set(values)))
    if len(result) > 200:
        _blocked("invalid_parent_batch")
    return result


def _columns(model, row_type, overrides=None):
    overrides = overrides or {}
    return tuple(
        (overrides[item.name] if item.name in overrides else getattr(model, item.name)).label(item.name)
        for item in fields(row_type)
    )


def _row(row_type, row):
    values = {item.name: row[item.name] for item in fields(row_type)}
    try:
        for name, value in values.items():
            if name.endswith("_json") and not (name == "model_transition_json" and value is None):
                values[name] = json.dumps(
                    value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                )
        if "auth_type" in values:
            values["auth_type"] = getattr(values["auth_type"], "value", values["auth_type"])
    except (TypeError, ValueError) as error:
        raise KnowledgeOperationPlanConflictError(reason="unification_inventory_invalid_json") from error
    return row_type(**values)


class UnificationInventoryRepository:
    @staticmethod
    async def _read(session, statement):
        _scope(session)
        with session.no_autoflush, strict_tenant_filter():
            return tuple((await session.execute(statement)).mappings())

    async def _page(self, session, model, row_type, after_id, limit, kind, *, statement=None, check=None):
        tenant = _scope(session)
        _pagination(after_id, limit, kind)
        query = select(*_columns(model, row_type)) if statement is None else statement
        if after_id is not None:
            query = query.where(model.id > after_id)
        rows = await self._read(session, query.order_by(model.id).limit(limit + 1))
        for row in rows:
            if "tenant_id" in row and row["tenant_id"] != tenant:
                _blocked("tenant_mismatch")
            if check is not None:
                check(row)
        return InventoryPage(
            tuple(_row(row_type, row) for row in rows[:limit]),
            rows[limit - 1]["id"] if len(rows) > limit else None,
        )

    async def alist_tenants(self, session, *, after_id=None, limit=200) -> InventoryPage[TenantRow]:
        return await self._page(session, Tenant, TenantRow, after_id, limit, int)

    async def alist_workflow_roots(self, session, *, after_id=None, limit=200) -> InventoryPage[WorkflowRootRow]:
        query = select(*_columns(Flow, WorkflowRootRow, {"data_json": Flow.data})).where(
            Flow.flow_type == FlowType.WORKFLOW.value
        )
        return await self._page(session, Flow, WorkflowRootRow, after_id, limit, str, statement=query)

    async def alist_workflow_versions(self, session, *, after_id=None, limit=200) -> InventoryPage[WorkflowVersionRow]:
        parent = Flow.__table__.alias("inventory_workflow_parent")
        query = select(
            *_columns(FlowVersion, WorkflowVersionRow, {"data_json": FlowVersion.data}),
            parent.c.id.label("parent_id"),
            parent.c.tenant_id.label("parent_tenant"),
            parent.c.flow_type.label("parent_type"),
        ).outerjoin(parent, parent.c.id == FlowVersion.flow_id)

        def check(row):
            if (
                row["parent_id"] is None
                or row["parent_tenant"] != row["tenant_id"]
                or row["parent_type"] != FlowType.WORKFLOW.value
                or row["flow_type"] not in (None, FlowType.WORKFLOW.value)
            ):
                _blocked("workflow_parent_invalid")

        return await self._page(
            session, FlowVersion, WorkflowVersionRow, after_id, limit, int, statement=query, check=check
        )

    async def alist_app_roots(self, session, *, after_id=None, limit=200) -> InventoryPage[AppRootRow]:
        return await self._page(session, App, AppRootRow, after_id, limit, str)

    async def alist_app_versions(self, session, *, after_id=None, limit=200) -> InventoryPage[AppVersionRow]:
        query = select(
            *_columns(
                AppVersion,
                AppVersionRow,
                {
                    "tenant_id": App.tenant_id,
                    "capabilities_json": AppVersion.capabilities,
                },
            )
        ).join(App, App.id == AppVersion.app_id)
        return await self._page(session, AppVersion, AppVersionRow, after_id, limit, str, statement=query)

    async def alist_assistants(self, session, *, after_id=None, limit=200) -> InventoryPage[AssistantRow]:
        return await self._page(session, Assistant, AssistantRow, after_id, limit, str)

    async def _parents(self, session, model, ids):
        rows = await self._read(session, select(model.id, model.tenant_id).where(model.id.in_(ids)).limit(201))
        if {row["id"] for row in rows} != set(ids) or any(row["tenant_id"] != _scope(session) for row in rows):
            _blocked("parent_batch_incomplete")

    async def alist_assistant_links(
        self, session, *, assistant_ids, after_id=None, limit=200
    ) -> InventoryPage[AssistantLinkRow]:
        _scope(session)
        _pagination(after_id, limit, int)
        ids = _parent_ids(assistant_ids)
        if not ids:
            return InventoryPage((), None)
        await self._parents(session, Assistant, ids)
        query = select(*_columns(AssistantLink, AssistantLinkRow)).where(AssistantLink.assistant_id.in_(ids))
        return await self._page(session, AssistantLink, AssistantLinkRow, after_id, limit, int, statement=query)

    async def alist_channels(self, session, *, after_id=None, limit=200) -> InventoryPage[ChannelRow]:
        return await self._page(session, Channel, ChannelRow, after_id, limit, str)

    async def alist_channel_syncs(
        self, session, *, channel_ids, after_id=None, limit=200
    ) -> InventoryPage[ChannelSyncRow]:
        _scope(session)
        _pagination(after_id, limit, str)
        ids = _parent_ids(channel_ids)
        if not ids:
            return InventoryPage((), None)
        await self._parents(session, Channel, ids)
        query = (
            select(*_columns(ChannelKnowledgeSync, ChannelSyncRow, {"tenant_id": Channel.tenant_id}))
            .join(Channel, Channel.id == ChannelKnowledgeSync.channel_id)
            .where(ChannelKnowledgeSync.channel_id.in_(ids))
        )
        return await self._page(session, ChannelKnowledgeSync, ChannelSyncRow, after_id, limit, str, statement=query)

    async def alist_knowledge(self, session, *, after_id=None, limit=200) -> InventoryPage[KnowledgeRow]:
        query = select(*_columns(Knowledge, KnowledgeRow, {"model_transition_json": Knowledge.model_transition}))
        return await self._page(session, Knowledge, KnowledgeRow, after_id, limit, int, statement=query)

    async def alist_model_defaults(self, session, *, after_id=None, limit=200) -> InventoryPage[DefaultRow]:
        query = select(*_columns(TenantSystemModelConfig, DefaultRow)).where(
            TenantSystemModelConfig.key.in_(tuple(MODEL_DEFAULT_SCHEMAS))
        )
        return await self._page(session, TenantSystemModelConfig, DefaultRow, after_id, limit, int, statement=query)

    async def alist_model_servers(self, session, *, after_id=None, limit=200) -> InventoryPage[CatalogServer]:
        return await self._page(session, LLMServer, CatalogServer, after_id, limit, int)

    async def alist_models(self, session, *, after_id=None, limit=200) -> InventoryPage[CatalogModel]:
        parent = LLMServer.__table__.alias("inventory_model_parent")
        query = select(
            *_columns(LLMModel, CatalogModel),
            parent.c.id.label("parent_id"),
            parent.c.tenant_id.label("parent_tenant"),
        ).outerjoin(parent, parent.c.id == LLMModel.server_id)

        def check(row):
            if row["parent_id"] is None or row["parent_tenant"] != row["tenant_id"]:
                _blocked("model_provider_parent_invalid")

        return await self._page(session, LLMModel, CatalogModel, after_id, limit, int, statement=query, check=check)

    async def avalidate_global_orphans(self, session) -> None:
        """One global existence check per run, outside the tenant loop."""
        _scope(session)
        # These two child tables have no tenant column. A missing parent has
        # no trustworthy owner at all; only its existence is read globally.
        for child, parent_model, foreign_key in (
            (AppVersion, App, AppVersion.app_id),
            (ChannelKnowledgeSync, Channel, ChannelKnowledgeSync.channel_id),
        ):
            parent = parent_model.__table__.alias("inventory_orphan_parent")
            query = select(child.id).outerjoin(parent, parent.c.id == foreign_key).where(parent.c.id.is_(None)).limit(1)
            if await self._read(session, query):
                _blocked("unowned_child_found")

    async def avalidate_tenant_orphans(self, session) -> None:
        """One current-tenant existence check; no prior clean result is cached."""
        tenant = _scope(session)
        # Unlike the children above, AssistantLink has a real isolation key.
        # Inspect it once per tenant, including children no valid root batch
        # could enumerate. Never repeat this scan for each root or child page.
        parent = Assistant.__table__.alias("inventory_assistant_parent")
        query = (
            select(AssistantLink.id)
            .outerjoin(parent, parent.c.id == AssistantLink.assistant_id)
            .where(or_(parent.c.id.is_(None), parent.c.tenant_id != tenant))
            .limit(1)
        )
        if await self._read(session, query):
            _blocked("assistant_parent_invalid")

    async def aload_reference_source(self, session, *, source_key):
        """Exact original scalar projections for stopped-service M4 revalidation."""
        from bisheng.resource_reference.application.contracts import SourceKey, SourceType

        tenant = _scope(session)
        if type(source_key) is not SourceKey or source_key.tenant_id != tenant:
            _blocked("source_identity")
        key, kind = source_key, source_key.source_type

        async def one(model, cls, condition, overrides=None, parent=None):
            query = select(*_columns(model, cls, overrides)).where(condition)
            if parent is not None:
                query = query.join(*parent)
            rows = await self._read(session, query.with_for_update())
            if len(rows) != 1:
                _blocked("source_missing_or_duplicated")
            value = _row(cls, rows[0])
            if hasattr(value, "tenant_id") and value.tenant_id != tenant:
                _blocked("source_wrong_tenant")
            return value

        if kind in {SourceType.WORKFLOW_VERSION, SourceType.HOSTED_APP_VERSION}:
            workflow = kind == SourceType.WORKFLOW_VERSION
            model, cls = (Flow, WorkflowRootRow) if workflow else (App, AppRootRow)
            root = await one(model, cls, model.id == key.source_id, {"data_json": Flow.data} if workflow else None)
            if workflow:
                version = await one(
                    FlowVersion,
                    WorkflowVersionRow,
                    (FlowVersion.id == int(key.source_version)) & (FlowVersion.flow_id == key.source_id),
                    {"data_json": FlowVersion.data},
                )
            else:
                version = await one(
                    AppVersion,
                    AppVersionRow,
                    (AppVersion.id == key.source_version) & (AppVersion.app_id == key.source_id),
                    {"tenant_id": App.tenant_id, "capabilities_json": AppVersion.capabilities},
                    (App, App.id == AppVersion.app_id),
                )
            return root, version, ()
        if kind in {SourceType.ASSISTANT, SourceType.CHANNEL_SYNC}:
            assistant = kind == SourceType.ASSISTANT
            model, cls = (Assistant, AssistantRow) if assistant else (Channel, ChannelRow)
            root = await one(model, cls, model.id == key.source_id)
            method = self.alist_assistant_links if assistant else self.alist_channel_syncs
            argument, children, after = "assistant_ids" if assistant else "channel_ids", [], None
            while True:
                page = await method(session, **{argument: (key.source_id,)}, after_id=after, limit=200)
                children.extend(page.items)
                if page.next_after is None:
                    break
                after = page.next_after
            return root, None, tuple(children)
        if kind == SourceType.KNOWLEDGE:
            row = await one(
                Knowledge,
                KnowledgeRow,
                Knowledge.id == int(key.source_id),
                {"model_transition_json": Knowledge.model_transition},
            )
        elif kind == SourceType.MODEL_DEFAULT:
            if key.source_id not in MODEL_DEFAULT_SCHEMAS:
                _blocked("unknown_default")
            row = await one(TenantSystemModelConfig, DefaultRow, TenantSystemModelConfig.key == key.source_id)
        else:
            _blocked("unknown_source_type")
        if key.source_version != "current":
            _blocked("source_version")
        return row, None, ()

    async def acensus_reference_sources(self, session):
        """One actual six-source membership pass; no target/source cross product."""
        from bisheng.resource_reference.application.contracts import SourceKey, SourceRootKey, SourceType

        tenant, roots, sources, versions = _scope(session), {}, set(), set()

        async def pages(method):
            after = None
            while True:
                page = await method(session, after_id=after, limit=200)
                yield page.items
                if page.next_after is None:
                    return
                after = page.next_after

        for kind, root_method, version_method in (
            (SourceType.WORKFLOW_VERSION, self.alist_workflow_roots, self.alist_workflow_versions),
            (SourceType.HOSTED_APP_VERSION, self.alist_app_roots, self.alist_app_versions),
        ):
            live = set()
            async for page in pages(root_method):
                for row in page:
                    roots[SourceRootKey(tenant, kind, row.id)] = row
                    if (row.is_delete == 0) if kind == SourceType.WORKFLOW_VERSION else (row.state != "deleted"):
                        live.add(row.id)
            async for page in pages(version_method):
                for row in page:
                    parent = row.flow_id if kind == SourceType.WORKFLOW_VERSION else row.app_id
                    versions.add(SourceKey(tenant, kind, parent, str(row.id)))
                    if parent in live and (kind != SourceType.WORKFLOW_VERSION or row.is_delete in (None, 0)):
                        sources.add(SourceKey(tenant, kind, parent, str(row.id)))
        for kind, method in (
            (SourceType.ASSISTANT, self.alist_assistants),
            (SourceType.CHANNEL_SYNC, self.alist_channels),
            (SourceType.KNOWLEDGE, self.alist_knowledge),
            (SourceType.MODEL_DEFAULT, self.alist_model_defaults),
        ):
            async for page in pages(method):
                for row in page:
                    ident = row.key if kind == SourceType.MODEL_DEFAULT else str(row.id)
                    roots[SourceRootKey(tenant, kind, ident)] = row
                    if kind == SourceType.ASSISTANT and row.is_delete != 0:
                        continue
                    if kind == SourceType.KNOWLEDGE and row.type == 2:
                        continue
                    sources.add(SourceKey(tenant, kind, ident, "current"))
        return roots, frozenset(sources), frozenset(versions)

    async def aload_reference_root(self, session, *, root_key):
        from bisheng.resource_reference.application.contracts import SourceRootKey, SourceType

        tenant = _scope(session)
        if type(root_key) is not SourceRootKey or root_key.tenant_id != tenant:
            _blocked("root_scope")
        types = {
            SourceType.WORKFLOW_VERSION: (Flow, WorkflowRootRow, {"data_json": Flow.data}),
            SourceType.HOSTED_APP_VERSION: (App, AppRootRow, None),
        }
        if root_key.source_type not in types:
            _blocked("version_root_type")
        model, row_type, overrides = types[root_key.source_type]
        rows = await self._read(
            session,
            select(*_columns(model, row_type, overrides)).where(model.id == root_key.source_id).with_for_update(),
        )
        if len(rows) != 1 or rows[0]["tenant_id"] != tenant:
            _blocked("root_missing")
        return _row(row_type, rows[0])

    async def ais_empty_installation(self, session):
        """Actual global creation-time emptiness, never an existing-tenant ready fallback."""
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
        from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
        from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
        from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

        _scope(session)
        for model in (
            Flow,
            FlowVersion,
            App,
            AppVersion,
            Assistant,
            AssistantLink,
            Channel,
            ChannelKnowledgeSync,
            Knowledge,
            TenantSystemModelConfig,
            KnowledgeUnificationRun,
            BusinessReferenceSet,
            BusinessResourceReference,
            ResourceReferenceTombstone,
        ):
            with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
                if (await session.execute(select(model.__table__.c.id).limit(1))).first() is not None:
                    return False
        return True

    async def avalidate_registered_source_tenants(self, session):
        """One global native tenant-integrity gate for formal M2/M4 only."""
        _scope(session)
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
        from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
        from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

        # Actual registered tenants close the source/index universe. Rows under
        # a nonexistent tenant must never disappear from the global M4 proof.
        for model in (
            Flow,
            FlowVersion,
            App,
            Assistant,
            AssistantLink,
            Channel,
            Knowledge,
            TenantSystemModelConfig,
            BusinessReferenceSet,
            BusinessResourceReference,
            ResourceReferenceTombstone,
        ):
            table, parent = model.__table__, Tenant.__table__.alias("reference_registered_tenant")
            query = (
                select(table.c.id)
                .select_from(table.outerjoin(parent, parent.c.id == table.c.tenant_id))
                .where(parent.c.id.is_(None))
                .limit(1)
            )
            with session.no_autoflush, strict_tenant_filter(), bypass_tenant_filter():
                if (await session.execute(query)).first() is not None:
                    _blocked("unregistered_source_or_index_tenant")
