"""T716: actual SQL/extractors/original-pin transport, without migration writes.

SQLite verifies bounded queries and transaction behavior, not MySQL locks.
DM8 runtime verification is waived; the production composition stays portable.
"""

import importlib
import json
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, asdict, fields
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.common.errcode.model_face import ModelFaceModelNotFoundError, ModelFaceModelOfflineError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_name_resolution_repository import ModelNameResolutionRepository
from bisheng.permission.application.migration_read import PinnedMigrationPermissionReader
from bisheng.permission.migration.f118_plan import (
    AuthorizationPinBaseline,
    CatalogReleaseBaseline,
    PermissionCatalogBaseline,
)
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey, reference_set_digest
from test.knowledge_unification import test_migration_inventory_repository as raw
from test.knowledge_unification import test_migration_permission_read as original_pin

storage = raw.storage
RUN = {"run_id": "formal-run", "writer_contract_version": "f118-v1"}
PRIVATE = "private-prompt-and-provider-config"


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_sources")


@pytest.fixture
async def database(storage):
    async with storage.begin() as connection:
        await connection.run_sync(lambda conn: KnowledgeFile.__table__.create(conn, checkfirst=True))
    async with AsyncSession(storage) as session, session.begin():
        session.add_all(
            [
                Tenant(id=1, tenant_code="root", tenant_name="Root"),
                Tenant(id=101, tenant_code="own", tenant_name="Own", parent_tenant_id=1),
                Tenant(id=202, tenant_code="other", tenant_name="Other", parent_tenant_id=1),
                LLMServer(id=1, tenant_id=101, name="own", type="openai", config={"private": PRIVATE}),
                LLMServer(id=2, tenant_id=1, name="root", type="openai", config={"private": PRIVATE}),
                LLMServer(id=3, tenant_id=202, name="foreign", type="openai"),
                LLMModel(id=11, tenant_id=101, server_id=1, model_name="chat", model_type="llm", online=True),
                LLMModel(id=12, tenant_id=1, server_id=2, model_name="embed", model_type="embedding", online=False),
                LLMModel(id=21, tenant_id=1, server_id=2, model_name="rootchat", model_type="llm", online=True),
                LLMModel(id=31, tenant_id=202, server_id=3, model_name="foreign", model_type="llm"),
                LLMModel(id=32, tenant_id=101, server_id=999, model_name="bad-parent", model_type="llm"),
                Knowledge(id=40, tenant_id=101, user_id=7, name="Docs", type=0, model="12"),
                Knowledge(id=41, tenant_id=101, user_id=7, name="QA", type=1, model="11"),
                Knowledge(id=42, tenant_id=101, user_id=7, name="Retired", type=2, model="31"),
                Knowledge(id=43, tenant_id=101, user_id=7, name="Space", type=3, model="11"),
                Knowledge(id=99, tenant_id=202, user_id=8, name="Docs", type=0),
                KnowledgeFile(id=81, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0),
            ]
        )
    return storage


@asynccontextmanager
async def sharing(*, malformed=False):
    requests = []

    def transport(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["authorization_model_id"] == "old-model"
        lines = [{"result": {"object": "llm_server:2"}}]
        if malformed:
            lines.append({"error": {"message": "stream failed"}})
        return httpx.Response(200, text="\n".join(json.dumps(row) for row in lines) + "\n")

    client = original_pin.FGAClient("http://offline", "old-store", "old-model")
    await client._http.aclose()
    client._http = httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(transport))
    catalog = PermissionCatalogBaseline(
        CatalogReleaseBaseline(1, "original", 1, "c" * 64, 10),
        AuthorizationPinBaseline(10, "test", "old-store", "old-model", "a" * 64, "b" * 64),
        (),
        (),
    )
    discovery = AsyncMock(return_value=original_pin.OpenFGARuntimePin("old-store", "old-model", "a" * 64))
    async with PinnedMigrationPermissionReader(
        OpenFGAConf(), catalog, discovery=discovery, client_factory=lambda **kwargs: client
    ) as reader:
        yield reader, requests
    assert client._http.is_closed


def graph(*targets):
    return {
        "nodes": [
            {
                "data": {
                    "id": f"node-{index}",
                    "type": "llm",
                    "group_params": [
                        {"params": [{"key": "model_id", "value": value}, {"key": "prompt", "value": PRIVATE}]}
                    ],
                }
            }
            for index, value in enumerate(targets)
        ],
        "edges": [],
        "prompt": PRIVATE,
    }


def version(ident, parent, capabilities=None, **changes):
    ordinal = changes.pop("version_no", 1)
    return AppVersion(
        id=ident,
        app_id=parent,
        version_no=ordinal,
        kind="initial" if ordinal == 1 else "iteration",
        code_object_key=PRIVATE,
        capabilities=capabilities or {},
        injections={"env": {"PRIVATE": PRIVATE}},
        tier_id="small",
        runtime="python3.11",
        **changes,
    )


async def collect(module, session, reader):
    return [
        row
        async for row in module.UnificationSourceInventory(sharing_reader=reader).aiter_tenant_source_records(
            session, **RUN
        )
    ]


async def test_actual_six_sources_preserve_versions_zero_roots_retired_and_private_content(module, database):
    from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync

    async with AsyncSession(database) as session, session.begin():
        session.add_all(
            [
                raw.flow("wf", data=graph(777)),
                raw.flow("wf-empty"),
                raw.flow("wf-deleted", is_delete=1),
                FlowVersion(
                    id=1, tenant_id=101, flow_id="wf", name="old", data=graph(11, 12, 31, 32, 999), is_current=0
                ),
                FlowVersion(
                    id=2, tenant_id=101, flow_id="wf", name="draft", data=None, is_current=None, is_delete=None
                ),
                FlowVersion(id=3, tenant_id=101, flow_id="wf", name="deleted", data=None, is_delete=1),
                FlowVersion(id=4, tenant_id=101, flow_id="wf-deleted", name="deleted-root", data=None),
                FlowVersion(id=5, tenant_id=101, flow_id="wf", name="later", data=graph(11)),
                raw.app("app"),
                raw.app("app-empty"),
                version(
                    "app-v1",
                    "app",
                    {"models": [{"name": "root/rootchat"}], "knowledge_bases": [{"name": "Docs"}, {"id": "43"}]},
                    terminal_state="withdrawn",
                ),
                version("app-v2", "app", version_no=2, terminal_state="rejected"),
                Assistant(id="as", tenant_id=101, user_id=7, model_name="11", status=0),
                Assistant(id="as-empty", tenant_id=101, user_id=7),
                Assistant(id="as-deleted", tenant_id=101, user_id=7, model_name="malformed", is_delete=1),
                AssistantLink(id=1, tenant_id=101, assistant_id="as", knowledge_id=40),
                AssistantLink(id=2, tenant_id=101, assistant_id="as", knowledge_id=0),
                AssistantLink(id=3, tenant_id=101, assistant_id="as", knowledge_id=None, tool_id=1),
                AssistantLink(id=4, tenant_id=101, assistant_id="as", knowledge_id=42),
                AssistantLink(id=5, tenant_id=101, assistant_id="as", knowledge_id=99),
                raw.channel("ch", is_released=False),
                raw.channel("ch-empty"),
                ChannelKnowledgeSync(
                    id="sync",
                    channel_id="ch",
                    sub_channel_name=None,
                    knowledge_space_id="43",
                    folder_id="81",
                    is_enabled=False,
                    user_id=7,
                ),
                TenantSystemModelConfig(tenant_id=101, key="knowledge_llm", value='{"embedding_model_id":12}'),
                TenantSystemModelConfig(tenant_id=101, key="assistant_llm", value='{"llm_list":[{"model_id":11}]}'),
                TenantSystemModelConfig(tenant_id=101, key="workflow_llm", value=""),
                TenantSystemModelConfig(tenant_id=101, key="evaluation_llm", value=None),
                TenantSystemModelConfig(tenant_id=101, key="linsight_llm", value="{}"),
                TenantSystemModelConfig(tenant_id=1, key="evaluation_llm", value='{"model_id":21}'),
                TenantSystemModelConfig(tenant_id=101, key="not-a-model-source", value=PRIVATE),
            ]
        )
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, requests):
        writes = []
        event.listen(session.sync_session, "before_flush", lambda *args: writes.append(True))
        records = await collect(module, session, reader)
        assert not writes and len(requests) == 1
        assert json.loads(requests[0].content)["user"] == "tenant:101"
    roots = {row.root_key: row for row in records if isinstance(row, module.RootInventoryRecord)}
    sources = {row.source_key: row for row in records if isinstance(row, module.SourceInventoryRecord)}
    references = [row for row in records if isinstance(row, module.ReferenceInventoryRecord)]
    retired = [row for row in records if isinstance(row, module.RetiredInventoryRecord)]
    assert {key.source_type.value for key in sources} == {
        "workflow_version",
        "hosted_app_version",
        "assistant",
        "channel_sync",
        "knowledge",
        "model_default",
    }
    assert next(row for key, row in roots.items() if key.source_id == "wf").retained_version_count == 3
    for ident in ("wf-empty", "app-empty"):
        assert next(row for key, row in roots.items() if key.source_id == ident).retained_version_count == 0
        assert not any(key.source_id == ident for key in sources)
    assert SourceKey(101, "workflow_version", "wf", "1") in sources
    assert sources[SourceKey(101, "workflow_version", "wf", "2")].reference_count == 0
    assert sources[SourceKey(101, "hosted_app_version", "app", "app-v2")].reference_count == 0
    assert sources[SourceKey(101, "assistant", "as-empty", "current")].reference_count == 0
    assert sources[SourceKey(101, "channel_sync", "ch-empty", "current")].reference_count == 0
    assert len([key for key in sources if key.source_type == "model_default"]) == 5
    assert len(retired) == 5  # two WF versions, WF root, deleted AS, KN type2
    assert not any(key.source_id in {"as-deleted", "wf-deleted", "42", "99"} for key in sources)
    for key, header in sources.items():
        actual = tuple(ReferenceSpec(row.slot_key, row.target) for row in references if row.source_key == key)
        assert header.reference_count == len(actual) and header.reference_digest == reference_set_digest(actual)
        assert len(header.configuration_digest) == 64 and not hasattr(header, "references")
    app_refs = [row for row in references if row.source_key.source_type == "hosted_app_version"]
    assert {(row.target, row.origin) for row in app_refs} == {
        (TargetKey("model", 21), "resolved_name"),
        (TargetKey("knowledge_space", 40), "resolved_name"),
        (TargetKey("knowledge_space", 43), "explicit_id"),
    }
    workflow_order = [
        row.source_key.source_version
        for row in records
        if isinstance(row, (module.SourceInventoryRecord, module.RetiredInventoryRecord))
        and row.source_key is not None
        and row.source_key.source_type == "workflow_version"
    ]
    assert workflow_order == ["1", "2", "3", "4", "5"]
    physical = {row.target: row.physical_fact for row in references}
    assert TargetKey("model", 777) not in physical
    assert physical[TargetKey("model", 12)].exists and not physical[TargetKey("model", 12)].is_online
    assert physical[TargetKey("model", 31)].target_tenant_id == 202
    assert not physical[TargetKey("model", 32)].server_exists
    assert physical[TargetKey("model", 32)].exists
    assert physical[TargetKey("knowledge_space", 42)].knowledge_type == 2
    assert physical[TargetKey("knowledge_space", 99)].target_tenant_id == 202
    assert not physical[TargetKey("model", 999)].exists
    assert physical[TargetKey("knowledge_file", 81)].file_type == 0
    assert PRIVATE not in repr(records) and "rootchat" not in repr(records)
    assert all(not hasattr(row, "__dict__") for row in records)
    with pytest.raises(FrozenInstanceError):
        records[0].lifecycle = ()
    assert [field.name for field in fields(module.SourceInventoryRecord)] == [
        "source_key",
        "extractor_version",
        "configuration_digest",
        "reference_digest",
        "reference_count",
        "lifecycle",
    ]


async def test_401_pages_child_batches_and_duplicate_targets_do_not_repeat_directory_or_physical_queries(
    module, database, monkeypatch
):
    from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync

    async with AsyncSession(database) as session, session.begin():
        session.add_all([raw.flow("wf"), raw.app("app")])
        for index in range(401):
            session.add(FlowVersion(id=index + 1, tenant_id=101, flow_id="wf", name="saved", data=graph(11)))
            session.add(version(f"v-{index:04}", "app", {"models": [{"name": "chat"}]}, version_no=index + 1))
            session.add(Assistant(id=f"as-{index:04}", tenant_id=101, user_id=7, model_name="11"))
            session.add(AssistantLink(tenant_id=101, assistant_id=f"as-{index:04}", knowledge_id=40))
            session.add(raw.channel(f"ch-{index:04}"))
            session.add(
                ChannelKnowledgeSync(channel_id=f"ch-{index:04}", knowledge_space_id="40", is_enabled=False, user_id=7)
            )
    catalogs = []
    actual = ModelNameResolutionRepository.ainspect_catalog

    async def counted(*args, **kwargs):
        catalogs.append(True)
        return await actual(*args, **kwargs)

    monkeypatch.setattr(ModelNameResolutionRepository, "ainspect_catalog", counted)
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, requests):
        statements = []
        event.listen(
            session.sync_session,
            "do_orm_execute",
            lambda state: statements.append(state.statement) if state.is_select else None,
        )
        records = await collect(module, session, reader)
    assert len(catalogs) == len(requests) == 1
    headers = [row for row in records if isinstance(row, module.SourceInventoryRecord)]
    assert len(headers) == 401 * 4 + 3  # three retained own KN model configurations
    refs = [row for row in records if isinstance(row, module.ReferenceInventoryRecord)]
    assert len({id(row.physical_fact) for row in refs if row.target == TargetKey("model", 11)}) == 1
    queries = [str(statement) for statement in statements]
    assert sum("inventory_workflow_parent" in query for query in queries) == 3
    assert sum("app_version.capabilities" in query for query in queries) == 3
    assert sum("knowledge.name" in query and "knowledge.model_transition" in query for query in queries) == 1
    assert sum("inventory_assistant_parent" in query for query in queries) == 1
    assert not any("inventory_orphan_parent" in query for query in queries)
    assert sum("llm_server.update_time AS parent_update_time" in query for query in queries) <= 2
    print(
        {
            "case": "401x4",
            "select_count": len(queries),
            "catalog_reads": len(catalogs),
            "sharing_reads": len(requests),
            "source_count": len(headers),
            "model_fact_queries": sum("llm_server.update_time AS parent_update_time" in query for query in queries),
        }
    )
    assert len(queries) < 55
    assert all(statement._offset_clause is None for statement in statements)


@pytest.mark.parametrize("many_sources", [True, False])
async def test_401_unique_model_targets_are_grouped_not_queried_per_source(module, database, many_sources):
    async with AsyncSession(database) as session, session.begin():
        session.add(raw.flow("wf"))
        session.add_all(
            [FlowVersion(id=i + 1, tenant_id=101, flow_id="wf", name="draft", data=graph(i + 1000)) for i in range(401)]
            if many_sources
            else [FlowVersion(id=1, tenant_id=101, flow_id="wf", name="draft", data=graph(*range(1000, 1401)))]
        )
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, _):
        statements = []
        event.listen(
            session.sync_session,
            "do_orm_execute",
            lambda state: statements.append(str(state.statement)) if state.is_select else None,
        )
        records = await collect(module, session, reader)
    facts = [
        row for row in records if isinstance(row, module.ReferenceInventoryRecord) and int(row.target.target_id) >= 1000
    ]
    assert len(facts) == 401 and all(not row.physical_fact.exists for row in facts)
    headers = [
        row
        for row in records
        if isinstance(row, module.SourceInventoryRecord) and row.source_key.source_type == "workflow_version"
    ]
    assert len(headers) == (401 if many_sources else 1)
    assert sum(row.reference_count for row in headers) == 401
    count = sum("llm_server.update_time AS parent_update_time" in query for query in statements)
    print({"case": "unique401", "many_sources": many_sources, "physical_model_queries": count})
    assert count <= 4


@pytest.mark.parametrize(
    "bad",
    [
        "knowledge_type",
        "workflow_flag",
        "graph",
        "app_state",
        "app_capabilities",
        "default",
        "json_null_default",
        "json_empty_default",
        "transition",
        "assistant_link",
    ],
)
async def test_unknown_or_malformed_original_facts_fail_without_ready_or_writes(module, database, bad):
    from bisheng.database.models.app import App
    from bisheng.database.models.flow import Flow

    async with AsyncSession(database) as session, session.begin():
        if bad == "knowledge_type":
            await session.execute(update(Knowledge).where(Knowledge.id == 40).values(type=99))
        elif bad == "transition":
            await session.execute(update(Knowledge).where(Knowledge.id == 40).values(model_transition={"raw": PRIVATE}))
        elif bad in {"workflow_flag", "graph"}:
            session.add(raw.flow("wf"))
            if bad == "workflow_flag":
                await session.flush()
                await session.execute(update(Flow).where(Flow.id == "wf").values(is_delete=2))
            else:
                session.add(FlowVersion(tenant_id=101, flow_id="wf", name="bad", data={"nodes": "bad"}))
        elif bad in {"app_state", "app_capabilities"}:
            session.add(raw.app("app"))
            if bad == "app_state":
                await session.flush()
                await session.execute(update(App).where(App.id == "app").values(state="unknown"))
            else:
                session.add(version("v1", "app", {"models": [{"id": 11}]}))
        elif bad in {"default", "json_null_default", "json_empty_default"}:
            value = {"default": "[]", "json_null_default": "null", "json_empty_default": '""'}[bad]
            session.add(TenantSystemModelConfig(tenant_id=101, key="knowledge_llm", value=value))
        else:
            session.add(AssistantLink(tenant_id=101, assistant_id="missing", knowledge_id=40))
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, _):
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        with pytest.raises((KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError)):
            await collect(module, session, reader)
        assert not flushes
        assert not session.new and not session.dirty


@pytest.mark.parametrize("name", ["missing", "root/embed"])
async def test_name_only_missing_and_offline_never_become_legacy_or_guessed_ids(module, database, name):
    async with AsyncSession(database) as session, session.begin():
        session.add(raw.app("app"))
        session.add(version("v1", "app", {"models": [{"name": name}]}))
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, _):
        with pytest.raises((ModelFaceModelNotFoundError, ModelFaceModelOfflineError)):
            await collect(module, session, reader)


async def test_stream_failure_no_reader_invalid_identity_and_scope_are_rejected(module, database):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        module.UnificationSourceInventory(sharing_reader=None)
    async with AsyncSession(database) as session, session.begin(), sharing(malformed=True) as (reader, _):
        with pytest.raises(PermissionMigrationBlockedError):
            await collect(module, session, reader)
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, _):
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        for identity in ({**RUN, "run_id": "../bad"}, {**RUN, "writer_contract_version": "x" * 33}):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                _ = [row async for row in inventory.aiter_tenant_source_records(session, **identity)]
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await collect(module, session, reader)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await collect(module, object(), reader)


async def test_partial_iteration_cannot_reuse_cache_after_scope_or_transaction_change(module, database):
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, _):
        iterator = module.UnificationSourceInventory(sharing_reader=reader).aiter_tenant_source_records(session, **RUN)
        await anext(iterator)
        with management_tenant_scope(202), pytest.raises(KnowledgeOperationPlanConflictError):
            await anext(iterator)
        await iterator.aclose()
    async with AsyncSession(database) as session, sharing() as (reader, _):
        async with session.begin():
            iterator = module.UnificationSourceInventory(sharing_reader=reader).aiter_tenant_source_records(
                session, **RUN
            )
            await anext(iterator)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await anext(iterator)
        await iterator.aclose()


async def test_no_autoflush_repeated_iterators_are_fresh_and_output_contains_only_closed_records(module, database):
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, requests):
        pending = LLMServer(name="pending", type="openai")
        session.add(pending)
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        first = await collect(module, session, reader)
        second = await collect(module, session, reader)
        assert first == second and len(requests) == 2 and not flushes
        assert pending in session.new and pending.tenant_id is None
        assert all(
            not any(key in asdict(row) for key in ("ready", "legacy", "payload_json", "references")) for row in first
        )


async def test_iterator_cache_is_not_reused_after_real_target_change(module, database):
    async with AsyncSession(database) as session, session.begin(), sharing() as (reader, _):
        first = await collect(module, session, reader)
        await session.execute(update(LLMModel).where(LLMModel.id == 11).values(online=False))
        second = await collect(module, session, reader)

        def model(rows):
            return next(
                row.physical_fact
                for row in rows
                if isinstance(row, module.ReferenceInventoryRecord) and row.target == TargetKey("model", 11)
            )

        assert model(first).is_online is True and model(second).is_online is False
