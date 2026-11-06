"""T693: native bounded SQL facts, without Source authority or migration writes.

SQLite proves query/isolation/flush behavior, not MySQL locks. DM8 runtime
verification is waived for this iteration; the implementation remains portable.
"""

import importlib
import json
from dataclasses import FrozenInstanceError, fields

import pytest
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    visible_tenant_ids,
)
from bisheng.core.database import tenant_filter
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_name_resolution_repository import CatalogModel, CatalogServer
from bisheng.user.domain.models.user import User

TABLES = (
    Tenant,
    User,
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
    LLMServer,
    LLMModel,
)
METHODS = {
    "alist_tenants": (int, {}),
    "alist_workflow_roots": (str, {}),
    "alist_workflow_versions": (int, {}),
    "alist_app_roots": (str, {}),
    "alist_app_versions": (str, {}),
    "alist_assistants": (str, {}),
    "alist_assistant_links": (int, {"assistant_ids": ()}),
    "alist_channels": (str, {}),
    "alist_channel_syncs": (str, {"channel_ids": ()}),
    "alist_knowledge": (int, {}),
    "alist_model_defaults": (int, {}),
    "alist_model_servers": (int, {}),
    "alist_models": (int, {}),
}


@pytest.fixture
def repo():
    return importlib.import_module(
        "bisheng.knowledge.domain.repositories.unification_inventory_repository"
    ).UnificationInventoryRepository()


@pytest.fixture
async def storage(monkeypatch):
    names = {model.__tablename__ for model in TABLES if "tenant_id" in model.__table__.c}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: SQLModel.metadata.create_all(conn, tables=[model.__table__ for model in TABLES])
            )
        yield engine
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


def flow(ident, tenant=101, **changes):
    return Flow(id=ident, tenant_id=tenant, name=ident, user_id=7, flow_type=10, **changes)


def app(ident, tenant=101, **changes):
    return App(id=ident, tenant_id=tenant, slug=ident, name=ident, owner_user_id=7, state="draft", **changes)


def app_version(ident, parent, **changes):
    return AppVersion(
        id=ident,
        app_id=parent,
        version_no=int(ident.split("-")[-1]) + 1,
        kind="initial",
        code_object_key="private-code-object",
        tier_id="small",
        runtime="python3.11",
        **changes,
    )


def channel(ident, tenant=101, **changes):
    return Channel(
        id=ident, tenant_id=tenant, name=ident, user_id=7, visibility=ChannelVisibilityEnum.PRIVATE, **changes
    )


async def pages(repo, method, session, **kwargs):
    result, after = [], None
    while True:
        page = await getattr(repo, method)(session, after_id=after, **kwargs)
        assert type(page.items) is tuple and len(page.items) <= kwargs.get("limit", 200)
        result.extend(page.items)
        if page.next_after is None:
            return tuple(result)
        assert page.items and page.next_after == page.items[-1].id and page.next_after != after
        after = page.next_after


def record_queries(session):
    statements = []
    event.listen(
        session.sync_session,
        "do_orm_execute",
        lambda state: statements.append(state.statement) if state.is_select else None,
    )
    return statements


async def test_roots_have_real_pk_pages_without_join_multiplication_and_keep_zero_versions(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        session.add_all([flow(f"wf-{i:04}", is_delete=i % 2) for i in range(401)])
        session.add_all([flow("other-tenant", 202), Flow(id="other-kind", tenant_id=101, name="Other", flow_type=5)])
        session.add_all([app("app-empty"), app("app-many"), app("app-outside", 202)])
        session.add(app_version("outside-version-9999", "app-outside"))
        session.add(FlowVersion(id=9999, tenant_id=202, flow_id="other-tenant", name="outside"))
        for i in range(401):
            session.add(
                FlowVersion(
                    id=i + 1,
                    tenant_id=101,
                    flow_id="wf-0000",
                    name=str(i),
                    flow_type=10,
                    is_delete=i % 2,
                    is_current=0,
                    data={"nodes": [], "edges": []},
                )
            )
            session.add(app_version(f"version-{i:04}", "app-many", terminal_state="withdrawn" if i % 2 else None))
        await session.flush()
        statements = record_queries(session)
        roots = await pages(repo, "alist_workflow_roots", session)
        versions = await pages(repo, "alist_workflow_versions", session)
        apps = await pages(repo, "alist_app_roots", session)
        app_versions = await pages(repo, "alist_app_versions", session)
        assert len(roots) == len(versions) == len(app_versions) == 401
        assert [row.id for row in roots] == [f"wf-{i:04}" for i in range(401)]
        assert {row.is_delete for row in roots} == {0, 1}
        assert {row.is_delete for row in versions} == {0, 1}
        assert {row.is_current for row in versions} == {0}
        assert {row.id for row in apps} == {"app-empty", "app-many"}
        assert {row.terminal_state for row in app_versions} == {None, "withdrawn"}
        assert all(row.tenant_id == 101 for row in app_versions)
        assert len(statements) == 10  # three + three + one + three PK page reads
        assert all(query._offset_clause is None and int(query._limit_clause.value) <= 201 for query in statements)
        for query in statements:
            assert len(query.get_final_froms()) == 1


async def test_all_tenant_statuses_knowledge_types_and_only_physical_own_defaults_are_kept(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        session.add_all(
            [
                Tenant(
                    id=i + 1,
                    tenant_code=f"tenant-{i}",
                    tenant_name=str(i),
                    status=("active", "disabled", "archived", "orphaned")[i % 4],
                )
                for i in range(401)
            ]
        )
        for i, kind in enumerate((0, 1, 2, 3, 99), 1):
            session.add(Knowledge(id=i, tenant_id=101, user_id=7, name=str(i), type=kind, model="42"))
        keys = ("knowledge_llm", "assistant_llm", "evaluation_llm", "workflow_llm", "linsight_llm")
        for i, key in enumerate(keys, 1):
            session.add(
                TenantSystemModelConfig(id=i, tenant_id=101, key=key, value=None if i == 1 else "" if i == 2 else "{}")
            )
            session.add(TenantSystemModelConfig(id=i + 10, tenant_id=1, key=key, value='{"model_id":999}'))
        session.add(TenantSystemModelConfig(id=100, tenant_id=101, key="initdb_config", value="do-not-read"))
        await session.flush()
        token = visible_tenant_ids.set(frozenset({1, 101, 202}))
        try:
            tenants = await pages(repo, "alist_tenants", session)
            knowledge = await pages(repo, "alist_knowledge", session, limit=2)
            defaults = await pages(repo, "alist_model_defaults", session, limit=2)
        finally:
            visible_tenant_ids.reset(token)
        assert len(tenants) == 401 and {row.status for row in tenants} == {"active", "disabled", "archived", "orphaned"}
        assert [row.type for row in knowledge] == [0, 1, 2, 3, 99]
        assert len(defaults) == 5 and {row.key for row in defaults} == set(keys)
        assert all(row.tenant_id == 101 for row in defaults)
        assert [row.value for row in defaults[:2]] == [None, ""]


async def test_batched_assistant_links_and_disabled_channel_configs_keep_empty_roots_and_original_slots(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        session.add_all(
            [
                Assistant(id="as-empty", tenant_id=101, model_name="", status=1),
                Assistant(id="as-many", tenant_id=101, model_name="42", status=1, is_delete=1),
                Assistant(id="as-foreign", tenant_id=202),
                channel("ch-empty"),
                channel("ch-many"),
                channel("ch-foreign", 202),
            ]
        )
        for i in range(401):
            session.add(
                AssistantLink(
                    id=i + 1, tenant_id=101, assistant_id="as-many", knowledge_id=0 if i == 0 else None if i == 1 else i
                )
            )
            session.add(
                ChannelKnowledgeSync(
                    id=f"sync-{i:04}",
                    channel_id="ch-many",
                    knowledge_space_id="7",
                    folder_id=None,
                    sub_channel_name=None if i == 0 else f"sub {i}",
                    is_enabled=False,
                    user_id=7,
                )
            )
        await session.flush()
        # The ORM applies knowledge_id's Python default even for explicit None;
        # persist a real SQL NULL so the raw inventory must distinguish it.
        await session.execute(update(AssistantLink).where(AssistantLink.id == 2).values(knowledge_id=None))
        statements = record_queries(session)
        assistants = await pages(repo, "alist_assistants", session)
        channels = await pages(repo, "alist_channels", session)
        links = await pages(repo, "alist_assistant_links", session, assistant_ids=("as-empty", "as-many", "as-many"))
        syncs = await pages(repo, "alist_channel_syncs", session, channel_ids=("ch-empty", "ch-many"))
        assert {row.id for row in assistants} == {"as-empty", "as-many"}
        assert {row.id for row in channels} == {"ch-empty", "ch-many"}
        assert len(links) == len(syncs) == 401
        assert [row.knowledge_id for row in links[:2]] == [0, None]
        assert all(not row.is_enabled and row.tenant_id == 101 for row in syncs)
        assert syncs[0].sub_channel_name is None and syncs[1].sub_channel_name == "sub 1"
        assert all(row.status == 1 for row in assistants) and assistants[1].is_delete == 1
        assert len(statements) <= 14  # root pages + one complete parent check per child page
        assert all(query._offset_clause is None for query in statements)


@pytest.mark.parametrize("method", tuple(METHODS))
async def test_read_only_pages_preserve_owner_pending_writes_and_transaction(repo, storage, method):
    async with AsyncSession(storage) as session, session.begin():
        pending = Assistant(id="pending", model_name="42")
        session.add(pending)
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        transaction = session.get_transaction()
        page = await getattr(repo, method)(session, **METHODS[method][1])
        assert page.items == () and page.next_after is None
        await repo.avalidate_global_orphans(session)
        assert pending in session.new and pending.tenant_id is None and not flushes
        assert session.get_transaction() is transaction


@pytest.mark.parametrize("method", tuple(METHODS))
async def test_bad_pagination_and_bypass_reject_before_any_sql(repo, storage, method):
    kind, kwargs = METHODS[method]
    invalid_cursors = (True, 0, -1, "1") if kind is int else (True, 0, "", "bad\x00cursor", "x" * 65)
    async with AsyncSession(storage) as session, session.begin():
        statements = record_queries(session)
        for after in invalid_cursors:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(repo, method)(session, after_id=after, **kwargs)
        for limit in (True, 0, -1, 201, 1.5, "2"):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(repo, method)(session, limit=limit, **kwargs)
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await getattr(repo, method)(session, **kwargs)
        assert statements == []


@pytest.mark.parametrize(
    "method,parameter", [("alist_assistant_links", "assistant_ids"), ("alist_channel_syncs", "channel_ids")]
)
async def test_invalid_parent_batches_and_missing_or_foreign_roots_are_explicit_failures(
    repo, storage, method, parameter
):
    async with AsyncSession(storage) as session, session.begin():
        session.add(Assistant(id="outside", tenant_id=202))
        session.add(channel("outside", 202))
        await session.flush()
        statements = record_queries(session)
        for value in ("single", ["list"], (True,), ("",), ("nul\x00",), tuple(str(i) for i in range(201))):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(repo, method)(session, **{parameter: value})
        assert statements == []
        for value in (("outside",), ("missing",)):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(repo, method)(session, **{parameter: value})


@pytest.mark.parametrize("broken", ["missing", "foreign", "wrong_type", "version_type"])
async def test_workflow_version_bad_real_parent_is_not_hidden_by_join_filtering(repo, storage, broken):
    async with AsyncSession(storage) as session, session.begin():
        if broken != "missing":
            parent = flow("parent", 202 if broken == "foreign" else 101)
            if broken == "wrong_type":
                parent.flow_type = 5
            session.add(parent)
        session.add(
            FlowVersion(
                id=1, tenant_id=101, flow_id="parent", name="old", flow_type=5 if broken == "version_type" else 10
            )
        )
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_workflow_versions(session)


@pytest.mark.parametrize("table", ["app", "channel", "assistant_missing", "assistant_foreign"])
async def test_global_orphan_probe_checks_only_existence_and_preserves_owner_pending_writes(repo, storage, table):
    async with AsyncSession(storage) as session, session.begin():
        if table == "app":
            session.add(app_version("orphan-1", "missing", capabilities={"secret": "foreign-private-value"}))
        elif table == "channel":
            session.add(ChannelKnowledgeSync(id="orphan", channel_id="missing", knowledge_space_id="7", user_id=7))
        else:
            if table == "assistant_foreign":
                session.add(Assistant(id="missing", tenant_id=202, system_prompt="foreign-private-value"))
            session.add(AssistantLink(id=1, tenant_id=101, assistant_id="missing", knowledge_id=7))
        await session.flush()
        pending = Assistant(id="pending")
        session.add(pending)
        statements = record_queries(session)
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await repo.avalidate_global_orphans(session)
        assert "foreign-private-value" not in str(caught.value)
        assert pending in session.new and pending.tenant_id is None
        assert all(int(query._limit_clause.value) == 1 for query in statements)
        assert all("capabilities" not in str(query) and "folder_path" not in str(query) for query in statements)


async def test_model_catalog_reads_exact_scalar_columns_and_rejects_bad_provider_parent(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        session.add(
            LLMServer(id=1, tenant_id=101, name="Provider", type="openai", config={"api_key": "provider-secret"})
        )
        session.add(LLMServer(id=2, tenant_id=202, name="Outside", type="openai"))
        for i in range(401):
            session.add(
                LLMModel(
                    id=i + 1,
                    tenant_id=101,
                    server_id=1,
                    model_name=f"model-{i}",
                    model_type="llm",
                    online=False,
                    config={"api_key": "model-secret"},
                )
            )
        await session.flush()
        statements = record_queries(session)
        servers = await pages(repo, "alist_model_servers", session)
        models = await pages(repo, "alist_models", session)
        assert servers == (CatalogServer(1, 101, "Provider", "openai"),)
        assert len(models) == 401 and all(isinstance(row, CatalogModel) and not row.online for row in models)
        assert len(statements) == 4
        assert all("config" not in str(query) for query in statements)
        session.add(LLMModel(id=999, tenant_id=101, server_id=2, model_name="bad", model_type="llm"))
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.alist_models(session, after_id=998)


async def test_orphan_probe_does_not_reclassify_valid_foreign_children_or_scan_foreign_assistant_links(repo, storage):
    async with AsyncSession(storage) as session, session.begin():
        session.add(app("foreign-app", 202))
        session.add(app_version("foreign-version-1", "foreign-app", capabilities={"private": "outside"}))
        session.add(channel("foreign-channel", 202))
        session.add(
            ChannelKnowledgeSync(id="foreign-sync", channel_id="foreign-channel", knowledge_space_id="7", user_id=7)
        )
        # This tenant's scan must not disclose or classify another tenant's
        # AssistantLink, even when that foreign tenant needs its own repair.
        session.add(AssistantLink(id=1, tenant_id=202, assistant_id="missing", knowledge_id=7))
        await session.flush()
        statements = record_queries(session)
        await repo.avalidate_global_orphans(session)
        assert len(statements) == 3
        assert all(len(query.selected_columns) == 1 and int(query._limit_clause.value) == 1 for query in statements)


async def test_raw_json_and_default_values_are_frozen_closed_rows_with_hidden_payloads(repo, storage):
    secret = "private-business-payload"
    async with AsyncSession(storage) as session, session.begin():
        session.add(flow("wf", data={"nodes": [], "secret": secret}))
        session.add(FlowVersion(id=1, tenant_id=101, flow_id="wf", name="draft", data={"secret": secret}))
        session.add(app("application"))
        session.add(
            app_version("version-1", "application", capabilities={"secret": secret}, injections={"secret": secret})
        )
        session.add(Knowledge(id=1, tenant_id=101, name="Knowledge", type=3, model_transition={"secret": secret}))
        session.add(TenantSystemModelConfig(id=1, tenant_id=101, key="knowledge_llm", value=secret))
        await session.flush()
        result = []
        for method in (
            "alist_workflow_roots",
            "alist_workflow_versions",
            "alist_app_versions",
            "alist_knowledge",
            "alist_model_defaults",
        ):
            result.extend((await getattr(repo, method)(session)).items)
        for row in result:
            assert secret not in repr(row)
            assert not hasattr(row, "__dict__")
            with pytest.raises(FrozenInstanceError):
                row.id = 99
        assert json.loads(result[0].data_json)["secret"] == secret
        assert json.loads(result[2].capabilities_json)["secret"] == secret
        assert json.loads(result[3].model_transition_json)["secret"] == secret
        assert result[4].value == secret
        assert [field.name for field in fields(result[2])] == [
            "id",
            "app_id",
            "tenant_id",
            "version_no",
            "kind",
            "terminal_state",
            "update_time",
            "capabilities_json",
        ]
        assert not any(name in {"injections", "manifest", "code_object_key"} for name in result[2].__slots__)


async def test_every_entry_requires_native_session_and_existing_concrete_transaction(repo, storage):
    for method, (_, kwargs) in METHODS.items():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await getattr(repo, method)(object(), **kwargs)
    async with AsyncSession(storage) as session:
        for method, (_, kwargs) in METHODS.items():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await getattr(repo, method)(session, **kwargs)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.avalidate_global_orphans(session)
    token = set_current_tenant_id(None)
    try:
        async with AsyncSession(storage) as session, session.begin():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.alist_tenants(session)
    finally:
        current_tenant_id.reset(token)
