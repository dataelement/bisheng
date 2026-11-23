"""Default Embedding saves preserve all existing space configurations and references.

覆盖 AC: AC-06, AC-37, AC-68, AC-71, AC-87, AC-88, AC-89, AC-91, AC-92.
Real default/Knowledge/R2 SQL; authorization and provider IO are doubles.
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete, event, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application import model_reference as knowledge
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.application import model_default as defaults
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services import llm as service
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from test.knowledge_unification import test_kn_model_bindings as facts

store = facts.store
tenant = facts.tenant
business = facts.business


def snapshot_state(context):
    result = facts.state(context)
    with context.sync.connect() as connection:
        result["tenant_system_model_config"] = (
            connection.execute(select(TenantSystemModelConfig.__table__).order_by(TenantSystemModelConfig.id))
            .mappings()
            .all()
        )
    return result


@pytest.fixture
async def workbench(business, monkeypatch):
    names = tenant_filter._tenant_aware_tables | {TenantSystemModelConfig.__tablename__}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    async with business.sessions() as session, session.begin():
        await session.execute(delete(Knowledge).where(Knowledge.tenant_id == 101, Knowledge.type == 3))
    monkeypatch.setattr(defaults, "get_reference_binding_runtime", AsyncMock(return_value=business.runtime))
    monkeypatch.setattr(
        defaults,
        "resolve_permission_actor",
        AsyncMock(return_value=PermissionActor(subject_id=7, tenant_id=101, tenant_admin_tenant_ids=frozenset({101}))),
    )
    monkeypatch.setattr(service, "get_async_db_session", business.sessions)
    probe = AsyncMock(return_value=[0.1, 0.2])
    monkeypatch.setattr(
        service.LLMService, "get_bisheng_embedding", AsyncMock(return_value=SimpleNamespace(aembed_query=probe))
    )
    business.probe = probe
    return business


async def add(context, ident, model="11"):
    async with context.sessions() as session:
        row = Knowledge(id=ident, tenant_id=101, user_id=7, name=str(ident), type=3, model=model, index_generation="g0")
        await knowledge.KnowledgeModelReferenceApplication.acreate(
            session, row, login_user=context.user, project_created=AsyncMock()
        )
        await session.commit()


def config(ident="12"):
    return WorkbenchModelConfig.model_validate({"embedding_model": {"id": ident, "name": "embedding"}, "models": []})


async def save(context, *, session=None, ident="12"):
    tasks = BackgroundTasks()
    result = await service.LLMService.update_workbench_llm(
        7, config(ident), tasks, login_user=context.user, session=session
    )
    assert not tasks.tasks
    return result


def space_state(state):
    return {
        name: [row for row in rows if name == "knowledge" or row["source_type"] == "knowledge"]
        for name, rows in state.items()
        if name in {"knowledge", "business_reference_set", "business_resource_reference"}
    }


@pytest.mark.parametrize("space_count", [0, 1, 25])
async def test_default_save_does_not_read_or_mutate_existing_spaces_or_bindings(workbench, space_count):
    for ident in range(40, 40 + space_count):
        await add(workbench, ident)
    before = space_state(snapshot_state(workbench))
    statements = []

    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(workbench.engine.sync_engine, "before_cursor_execute", observe)
    try:
        result = await save(workbench)
    finally:
        event.remove(workbench.engine.sync_engine, "before_cursor_execute", observe)
    assert result.embedding_model.id == "12"
    assert not any(re.search(r"\bknowledge\b", sql, re.IGNORECASE) for sql in statements)
    after = snapshot_state(workbench)
    assert space_state(after) == before
    default_refs = [row for row in after["business_resource_reference"] if row["source_type"] == "model_default"]
    assert {(row["slot_key"], row["target_id"]) for row in default_refs} == {("embedding_model.id", "12")}
    workbench.probe.assert_awaited_once()


@pytest.mark.parametrize("failure", ["references", "probe", "commit"])
async def test_precommit_failure_rolls_back_default_and_its_references(workbench, monkeypatch, failure):
    await add(workbench, 40)
    before = snapshot_state(workbench)
    if failure == "references":
        original = workbench.runtime.aapply_source_bindings

        async def fail(active, prepared):
            await original(active, prepared)
            raise RuntimeError("reference save failed")

        monkeypatch.setattr(workbench.runtime, "aapply_source_bindings", fail)
    elif failure == "probe":
        workbench.probe.side_effect = RuntimeError("provider probe failed")
        monkeypatch.setattr(service, "to_llm_invoke_error", lambda client, error: RuntimeError("probe failure"))
    else:

        async def fail_commit(self):
            raise RuntimeError("SQL commit failed")

        monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        await save(workbench)
    assert snapshot_state(workbench) == before


async def test_unindexed_or_uneditable_space_cannot_block_independent_default_save(workbench, monkeypatch):
    await add(workbench, 40)
    async with workbench.sessions() as session, session.begin():
        await session.execute(
            delete(BusinessReferenceSet).where(
                BusinessReferenceSet.tenant_id == 101,
                BusinessReferenceSet.source_type == "knowledge",
                BusinessReferenceSet.source_id == "40",
                BusinessReferenceSet.source_version == "current",
            )
        )
    denied = AsyncMock(side_effect=AssertionError("default save must not request edit on existing spaces"))
    monkeypatch.setattr(knowledge, "require_business_action", denied)
    before = space_state(snapshot_state(workbench))
    await save(workbench)
    assert space_state(snapshot_state(workbench)) == before
    denied.assert_not_awaited()


@pytest.mark.parametrize("caller", ["application", "external_service"])
async def test_external_owner_can_save_default_and_rollback_without_command_contract(workbench, caller):
    await add(workbench, 40)
    before = snapshot_state(workbench)
    async with workbench.sessions() as session:
        if caller == "application":
            result = await defaults.ModelDefaultApplication.asave(
                session, "linsight_llm", config(), login_user=workbench.user
            )
        else:
            result = await save(workbench, session=session)
        assert result.embedding_model.id == "12" and session.in_transaction()
        await session.rollback()
    assert snapshot_state(workbench) == before


async def test_same_canonical_embedding_does_not_repeat_provider_probe(workbench):
    async with workbench.sessions() as session, session.begin():
        await defaults.ModelDefaultApplication.asave(session, "linsight_llm", config("11"), login_user=workbench.user)
    await add(workbench, 40)
    before = space_state(snapshot_state(workbench))
    result = await save(workbench, ident="011")
    assert result.embedding_model.id == "11" and space_state(snapshot_state(workbench)) == before
    workbench.probe.assert_not_awaited()


async def test_clearing_default_preserves_independent_space_configuration(workbench):
    async with workbench.sessions() as session, session.begin():
        await defaults.ModelDefaultApplication.asave(session, "linsight_llm", config("11"), login_user=workbench.user)
    await add(workbench, 40)
    before = space_state(snapshot_state(workbench))
    result = await service.LLMService.update_workbench_llm(
        7, WorkbenchModelConfig(models=[]), BackgroundTasks(), login_user=workbench.user
    )
    assert result.embedding_model is None and space_state(snapshot_state(workbench)) == before
    assert not [
        row for row in snapshot_state(workbench)["business_resource_reference"] if row["source_type"] == "model_default"
    ]
    workbench.probe.assert_not_awaited()


async def test_default_override_does_not_repair_existing_spaces_with_revoked_root_model(workbench):
    from sqlalchemy import update

    from bisheng.database.models.tenant import Tenant

    await add(workbench, 40, "22")
    async with workbench.sessions() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == 1).values(share_default_to_children=1))
        session.add(TenantSystemModelConfig(tenant_id=1, key="linsight_llm", value='{"embedding_model":{"id":"22"}}'))
    workbench.sharing.allowed = frozenset()
    before = space_state(snapshot_state(workbench))
    await save(workbench)
    assert space_state(snapshot_state(workbench)) == before


async def test_unavailable_new_default_is_rejected_without_altering_spaces(workbench):
    await add(workbench, 40)
    before = snapshot_state(workbench)
    with pytest.raises(ResourceReferenceInvalidError):
        await save(workbench, ident="999")
    assert snapshot_state(workbench) == before
    workbench.probe.assert_not_awaited()


async def test_frontend_creation_snapshots_default_and_later_spaces_use_new_default(workbench, monkeypatch):
    from bisheng.common.models.space_channel_member import SpaceChannelMember
    from bisheng.knowledge.domain.services import knowledge_space_service as module
    from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository

    SpaceChannelMember.__table__.create(workbench.sync)
    owner = module.KnowledgeSpaceService(None, workbench.user)
    monkeypatch.setattr(module, "get_async_db_session", workbench.sessions)
    monkeypatch.setattr(owner, "_existing_creation", AsyncMock(return_value=None))
    monkeypatch.setattr(owner, "_assert_space_creation_quota", AsyncMock())
    monkeypatch.setattr(owner, "_is_auto_tag_feature_visible", AsyncMock(return_value=False))
    monkeypatch.setattr(owner, "_project_space_created", AsyncMock())
    monkeypatch.setattr(owner, "_complete_knowledge_creation", AsyncMock(side_effect=lambda row, **kwargs: row))
    monkeypatch.setattr(module.KnowledgeService, "_init_knowledge_indices_sync", lambda *args: None)
    monkeypatch.setattr(module.KnowledgeAuditTelemetryService, "audit_create_knowledge_space", AsyncMock())

    async def current_default():
        # Execution admission is covered by the default-consumer suite; use the
        # real persisted payload here to exercise the actual creation snapshot.
        async with workbench.sessions() as session:
            effective = await ModelDefaultRepository().aresolve(session, "linsight_llm")
            return WorkbenchModelConfig.model_validate_json(effective.payload_json)

    monkeypatch.setattr(module.LLMService, "get_workbench_llm", current_default)
    async with workbench.sessions() as session, session.begin():
        await defaults.ModelDefaultApplication.asave(session, "linsight_llm", config("11"), login_user=workbench.user)
    first = await owner.create_knowledge_space("before default change")
    await save(workbench)
    second = await owner.create_knowledge_space("after default change")
    state = snapshot_state(workbench)
    assert next(row for row in state["knowledge"] if row["id"] == first.id)["model"] == "11"
    assert next(row for row in state["knowledge"] if row["id"] == second.id)["model"] == "12"
    refs = [row for row in state["business_resource_reference"] if row["source_type"] == "knowledge"]
    assert {(row["source_id"], row["target_id"]) for row in refs} == {(str(first.id), "11"), (str(second.id), "12")}
