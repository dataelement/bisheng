"""Native M2 context reuse and original row revisions, without migration writes."""

import re
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, event, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.database.models.assistant import Assistant, AssistantLink
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.repositories.model_name_resolution_repository import ModelNameResolutionRepository
from test.knowledge_unification import test_migration_source_inventory as original

storage = original.storage
module = original.module
database = original.database
RUN = original.RUN
NOW = datetime(2026, 11, 7, 2, 3, 4)
LATER = NOW + timedelta(seconds=1)


@pytest.fixture
async def populated(database):
    async with AsyncSession(database) as session, session.begin():
        session.add_all(
            [
                original.raw.flow("wf", update_time=NOW),
                original.raw.flow("wf-empty", update_time=NOW),
                original.raw.flow("wf-retired", is_delete=1, update_time=NOW),
                FlowVersion(
                    id=1,
                    flow_id="wf",
                    tenant_id=101,
                    name="saved",
                    data=original.graph(11),
                    is_current=0,
                    update_time=NOW,
                ),
                FlowVersion(
                    id=2,
                    flow_id="wf",
                    tenant_id=101,
                    name="retired",
                    data=original.graph(11),
                    is_delete=1,
                    update_time=NOW,
                ),
                original.raw.app("app", update_time=NOW),
                original.raw.app("app-empty", update_time=NOW),
                original.version("v1", "app", {"models": [{"name": "chat"}]}, update_time=NOW),
                Assistant(id="as", tenant_id=101, user_id=7, model_name="11", status=0, update_time=NOW),
                Assistant(
                    id="as-retired", tenant_id=101, user_id=7, is_delete=1, model_name="malformed", update_time=NOW
                ),
                AssistantLink(id=1, tenant_id=101, assistant_id="as", knowledge_id=40, update_time=NOW),
                AssistantLink(id=2, tenant_id=101, assistant_id="as-retired", knowledge_id=40, update_time=NOW),
                original.raw.channel("ch", is_released=False, update_time=NOW),
                ChannelKnowledgeSync(
                    id="sync", channel_id="ch", knowledge_space_id="43", is_enabled=False, user_id=7, update_time=NOW
                ),
                TenantSystemModelConfig(
                    id=701, tenant_id=101, key="knowledge_llm", value='{"embedding_model_id":12}', update_time=NOW
                ),
                TenantSystemModelConfig(
                    id=702, tenant_id=101, key="assistant_llm", value='{"llm_list":[{"model_id":11}]}', update_time=NOW
                ),
                TenantSystemModelConfig(id=703, tenant_id=101, key="workflow_llm", value="", update_time=NOW),
                TenantSystemModelConfig(id=704, tenant_id=101, key="evaluation_llm", value=None, update_time=NOW),
                TenantSystemModelConfig(id=705, tenant_id=101, key="linsight_llm", value="{}", update_time=NOW),
            ]
        )
        await session.execute(update(Knowledge).values(update_time=NOW))
    return database


async def collect(inventory, session, *, context=None, **identity):
    options = {} if context is None else {"context": context}
    return [record async for record in inventory.aiter_tenant_source_records(session, **(RUN | identity), **options)]


def selected(module, records, kind, ident, version=None):
    for record in records:
        if isinstance(record, module.ReferenceInventoryRecord):
            continue
        key = (
            record.source_key
            if isinstance(record, module.SourceInventoryRecord)
            else getattr(record, "source_key", None)
        )
        if key is None:
            key = getattr(record, "root_key", None)
        if (
            key is not None
            and key.source_type == kind
            and key.source_id == ident
            and getattr(key, "source_version", None) == version
        ):
            return record
    raise AssertionError((kind, ident, version))


async def test_native_fixture_retains_six_sources_empty_roots_and_retired_original_semantics(module, populated):
    async with AsyncSession(populated) as session, session.begin(), original.sharing() as (reader, _):
        # The old signature is intentional in this factual first-green case.
        records = [
            record
            async for record in module.UnificationSourceInventory(sharing_reader=reader).aiter_tenant_source_records(
                session, **RUN
            )
        ]
    assert {
        record.source_key.source_type.value for record in records if isinstance(record, module.SourceInventoryRecord)
    } == {"workflow_version", "hosted_app_version", "assistant", "channel_sync", "knowledge", "model_default"}
    assert selected(module, records, "workflow_version", "wf-empty").retained_version_count == 0
    assert selected(module, records, "hosted_app_version", "app-empty").retained_version_count == 0
    assert isinstance(selected(module, records, "workflow_version", "wf", "2"), module.RetiredInventoryRecord)
    assert original.PRIVATE not in repr(records)


@pytest.mark.parametrize("count", [0, 401])
async def test_prepared_context_reads_directories_once_and_stream_does_not_repeat_preparation(
    module, database, monkeypatch, count
):
    async with AsyncSession(database) as session, session.begin():
        await session.execute(delete(Knowledge).where(Knowledge.tenant_id == 101))
        session.add_all(
            [
                Knowledge(id=1000 + index, tenant_id=101, user_id=7, type=0, name=f"private-{index}", model="11")
                for index in range(count)
            ]
        )
        session.add(original.raw.flow("wf"))
        session.add(FlowVersion(id=1, tenant_id=101, flow_id="wf", name="saved", data=original.graph(*([11] * 401))))
    catalog_calls = []
    actual = ModelNameResolutionRepository.ainspect_catalog

    async def catalog(*args, **kwargs):
        catalog_calls.append(True)
        return await actual(*args, **kwargs)

    monkeypatch.setattr(ModelNameResolutionRepository, "ainspect_catalog", catalog)
    async with AsyncSession(database) as session, session.begin(), original.sharing() as (reader, requests):
        queries, writes = [], []
        event.listen(
            session.sync_session,
            "do_orm_execute",
            lambda state: queries.append(str(state.statement)) if state.is_select else writes.append(True),
        )
        event.listen(session.sync_session, "before_flush", lambda *_: writes.append(True))
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        pending = LLMServer(name="private-pending", type="openai")
        session.add(pending)
        context = await inventory.aprepare_tenant_context(session, **RUN)
        assert isinstance(context, module.PreparedSourceInventoryContext)
        assert (
            context.tenant_id == 101
            and context.run_id == RUN["run_id"]
            and context.writer_contract_version == RUN["writer_contract_version"]
        )
        assert context.shared_server_ids == frozenset({2})
        assert isinstance(context.knowledge_rows, tuple) and len(context.knowledge_rows) == count
        assert "private-" not in repr(context) and "rootchat" not in repr(context)
        assert not hasattr(context, "__dict__")
        with pytest.raises(FrozenInstanceError):
            context.tenant_id = 202
        prepared_count = len(queries)
        assert len(requests) == len(catalog_calls) == 1
        assert sum("knowledge.name" in query and "knowledge.model_transition" in query for query in queries) == (
            3 if count else 1
        )
        assert sum("inventory_assistant_parent" in query for query in queries) == 1
        first = await collect(inventory, session, context=context)
        second = await collect(inventory, session, context=context)
        assert first == second and len(requests) == len(catalog_calls) == 1
        assert sum("knowledge.name" in query and "knowledge.model_transition" in query for query in queries) == (
            3 if count else 1
        )
        assert sum("inventory_assistant_parent" in query for query in queries) == 1
        assert len(queries) - prepared_count < 35  # two real streams, not repeated directory scans or N slots SQL
        assert not writes and pending in session.new and pending.tenant_id is None
        print(
            {
                "knowledge_rows": count,
                "prepare_selects": prepared_count,
                "two_stream_selects": len(queries) - prepared_count,
                "share": len(requests),
                "catalog": len(catalog_calls),
            }
        )


@pytest.mark.parametrize("invalid", ["tenant", "run", "writer", "instance", "session", "bypass", "reconstructed"])
async def test_context_cannot_be_reused_with_another_authority_or_identity(module, database, invalid):
    async with AsyncSession(database) as session, session.begin(), original.sharing() as (reader, requests):
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        context = await inventory.aprepare_tenant_context(session, **RUN)
        other = module.UnificationSourceInventory(sharing_reader=reader) if invalid == "instance" else inventory
        kwargs = (
            {"run_id": "other-run"}
            if invalid == "run"
            else {"writer_contract_version": "other-writer"}
            if invalid == "writer"
            else {}
        )
        if invalid == "reconstructed":
            context = replace(context)
        if invalid == "tenant":
            with tenant_execution_scope(202), pytest.raises(KnowledgeOperationPlanConflictError):
                await collect(other, session, context=context, **kwargs)
        elif invalid == "bypass":
            with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
                await collect(other, session, context=context, **kwargs)
        elif invalid == "session":
            async with AsyncSession(database) as different, different.begin():
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await collect(other, different, context=context, **kwargs)
        else:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await collect(other, session, context=context, **kwargs)
        assert len(requests) == 1


@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_context_rejects_same_session_after_original_transaction_finishes(module, database, finish):
    async with AsyncSession(database) as session, original.sharing() as (reader, _):
        await session.begin()
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        context = await inventory.aprepare_tenant_context(session, **RUN)
        await getattr(session, finish)()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await collect(inventory, session, context=context)
        async with session.begin():
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await collect(inventory, session, context=context)


async def test_each_yield_rechecks_context_and_physical_cache_is_stream_local(module, populated):
    async with AsyncSession(populated) as session, session.begin(), original.sharing() as (reader, _):
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        context = await inventory.aprepare_tenant_context(session, **RUN)
        iterator = inventory.aiter_tenant_source_records(session, **RUN, context=context)
        await anext(iterator)
        with tenant_execution_scope(202), pytest.raises(KnowledgeOperationPlanConflictError):
            await anext(iterator)
        await iterator.aclose()
        before = await collect(inventory, session, context=context)
        await session.execute(update(LLMModel).where(LLMModel.id == 11).values(online=False))
        after = await collect(inventory, session, context=context)
        target = original.TargetKey("model", 11)

        def fact(records):
            return next(
                record.physical_fact
                for record in records
                if isinstance(record, module.ReferenceInventoryRecord) and record.target == target
            )

        assert fact(before).is_online is True and fact(after).is_online is False


@pytest.mark.parametrize(
    "model,where,changes,kind,ident,version",
    [
        (Flow, "wf", {"update_time": LATER}, "workflow_version", "wf", "1"),
        (Flow, "wf", {"status": 0}, "workflow_version", "wf", "1"),
        (Flow, "wf", {"update_time": LATER}, "workflow_version", "wf", "2"),
        (Flow, "wf-empty", {"update_time": LATER}, "workflow_version", "wf-empty", None),
        (Flow, "wf-retired", {"update_time": LATER}, "workflow_version", "wf-retired", None),
        (FlowVersion, 1, {"update_time": LATER}, "workflow_version", "wf", "1"),
        (FlowVersion, 1, {"is_current": 1}, "workflow_version", "wf", "1"),
        (FlowVersion, 2, {"update_time": LATER}, "workflow_version", "wf", "2"),
        (App, "app", {"update_time": LATER}, "hosted_app_version", "app", "v1"),
        (App, "app", {"state": "stopped"}, "hosted_app_version", "app", "v1"),
        (AppVersion, "v1", {"update_time": LATER}, "hosted_app_version", "app", "v1"),
        (AppVersion, "v1", {"terminal_state": "withdrawn"}, "hosted_app_version", "app", "v1"),
        (Assistant, "as", {"update_time": LATER}, "assistant", "as", "current"),
        (Assistant, "as", {"status": 1}, "assistant", "as", "current"),
        (AssistantLink, 1, {"update_time": LATER}, "assistant", "as", "current"),
        (AssistantLink, 1, {"knowledge_id": 43}, "assistant", "as", "current"),
        (AssistantLink, 2, {"update_time": LATER}, "assistant", "as-retired", None),
        (Channel, "ch", {"update_time": LATER}, "channel_sync", "ch", "current"),
        (Channel, "ch", {"is_released": True}, "channel_sync", "ch", "current"),
        (ChannelKnowledgeSync, "sync", {"update_time": LATER}, "channel_sync", "ch", "current"),
        (ChannelKnowledgeSync, "sync", {"is_enabled": True}, "channel_sync", "ch", "current"),
        (TenantSystemModelConfig, 701, {"update_time": LATER}, "model_default", "knowledge_llm", "current"),
        (TenantSystemModelConfig, 701, {"id": 801}, "model_default", "knowledge_llm", "current"),
        (
            TenantSystemModelConfig,
            701,
            {"value": '{"embedding_model_id":11}'},
            "model_default",
            "knowledge_llm",
            "current",
        ),
        (TenantSystemModelConfig, 704, {"value": ""}, "model_default", "evaluation_llm", "current"),
        (Knowledge, 40, {"update_time": LATER}, "knowledge", "40", "current"),
        (Knowledge, 40, {"model": "11"}, "knowledge", "40", "current"),
        (Knowledge, 40, {"user_id": 8}, "knowledge", "40", "current"),
        (Knowledge, 40, {"type": 3}, "knowledge", "40", "current"),
        (Knowledge, 40, {"index_name": "changed-index"}, "knowledge", "40", "current"),
        (Knowledge, 40, {"collection_name": "changed-collection"}, "knowledge", "40", "current"),
        (Knowledge, 42, {"update_time": LATER}, "knowledge", "42", None),
    ],
)
async def test_original_row_or_parent_perturbation_changes_business_revision(
    module, populated, model, where, changes, kind, ident, version
):
    async with AsyncSession(populated) as session, session.begin(), original.sharing() as (reader, _):
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        before = await collect(inventory, session)
        first = selected(module, before, kind, ident, version)
        assert re.fullmatch("[0-9a-f]{64}", first.business_revision_digest)
        await session.execute(update(model).where(model.id == where).values(**changes))
        after = await collect(inventory, session)
        second = selected(module, after, kind, ident, version)
        assert first.business_revision_digest != second.business_revision_digest
        assert original.PRIVATE not in repr(after)


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "model_transition",
            {"schema_version": 1, "operation_id": "planned", "current_model_id": "12", "pending_model_id": "11"},
        ),
        ("model_config_revision", 8),
        ("index_generation", "generation"),
        ("processing_config_version", 8),
        ("metadata_schema_revision", 8),
        ("migration_origin", "migration"),
    ],
)
async def test_knowledge_neutral_columns_stay_separate_from_original_business_revision(module, populated, field, value):
    async with AsyncSession(populated) as session, session.begin(), original.sharing() as (reader, _):
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        before = selected(module, await collect(inventory, session), "knowledge", "40", "current")
        resource_repo = UnificationResourceRepository()
        old_resource = (await resource_repo.alist_resources(session)).items[0]
        await session.execute(update(Knowledge).where(Knowledge.id == 40).values({field: value}))
        after = selected(module, await collect(inventory, session), "knowledge", "40", "current")
        resource = (await resource_repo.alist_resources(session)).items[0]
        assert after.business_revision_digest == before.business_revision_digest
        assert resource.old_business_digest == old_resource.old_business_digest
        assert getattr(resource.neutral, field) == value
        if field == "model_transition":
            assert after.configuration_digest != before.configuration_digest


async def test_root_and_source_headers_are_closed_digests_and_repeated_original_runs_stay_fresh(module, populated):
    async with AsyncSession(populated) as session, session.begin(), original.sharing() as (reader, requests):
        inventory = module.UnificationSourceInventory(sharing_reader=reader)
        first, second = await collect(inventory, session), await collect(inventory, session)
        assert first == second and len(requests) == 2
        headers = [record for record in first if not isinstance(record, module.ReferenceInventoryRecord)]
        for record in headers:
            assert re.fullmatch("[0-9a-f]{64}", record.business_revision_digest)
            assert not hasattr(record, "references") and not hasattr(record, "payload_json")
        assert original.PRIVATE not in repr(first)
