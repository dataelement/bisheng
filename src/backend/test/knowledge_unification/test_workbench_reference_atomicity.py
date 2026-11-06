"""T480: the real default and complete personal-space set commit as one unit.

覆盖 AC: AC-37, AC-68, AC-71, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91, AC-92
Actual SQL/R2/KN application; provider and postcommit queue transports are doubles.
"""

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application import model_reference as knowledge
from bisheng.llm.application import model_default as defaults
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services import llm as service
from bisheng.permission.application.identity import PermissionActor
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from test.knowledge_unification import test_kn_model_bindings as facts
from test.knowledge_unification import test_kn_workbench_model_batch as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
spaces = fixtures.spaces


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
async def workbench(spaces, monkeypatch):
    monkeypatch.setattr(defaults, "get_reference_binding_runtime", AsyncMock(return_value=spaces.runtime))
    monkeypatch.setattr(
        defaults,
        "resolve_permission_actor",
        AsyncMock(return_value=PermissionActor(subject_id=7, tenant_id=101, tenant_admin_tenant_ids=frozenset({101}))),
    )
    monkeypatch.setattr(service, "get_async_db_session", spaces.sessions)
    probe = AsyncMock(return_value=[0.1, 0.2])
    monkeypatch.setattr(
        service.LLMService, "get_bisheng_embedding", AsyncMock(return_value=SimpleNamespace(aembed_query=probe))
    )
    queued = []

    def dispatch(commands):
        # Queue publishing must observe the already committed business/indexes.
        state = snapshot_state(spaces)
        payload = next(
            row["value"]
            for row in state["tenant_system_model_config"]
            if row["tenant_id"] == 101 and row["key"] == "linsight_llm"
        )
        assert json.loads(payload)["embedding_model"]["id"] == "12"
        for command in commands:
            row = next(item for item in state["knowledge"] if item["id"] == command.knowledge_id)
            assert row["model_config_revision"] == command.expected_model_config_revision
            assert row["index_generation"] == command.expected_index_generation
        queued.append(commands)

    monkeypatch.setattr(service.LLMService, "_dispatch_model_default_commands", dispatch, raising=False)
    spaces.probe, spaces.queued = probe, queued
    return spaces


def config(ident="12"):
    return WorkbenchModelConfig.model_validate({"embedding_model": {"id": ident, "name": "embedding"}, "models": []})


async def save(context, *, session=None, ident="12"):
    return await service.LLMService.update_workbench_llm(
        7, config(ident), BackgroundTasks(), login_user=context.user, session=session
    )


async def test_actual_service_commits_all_spaces_and_default_before_publishing_original_commands(workbench):
    await fixtures.add(workbench, 40)
    await fixtures.add(workbench, 41)
    result = await save(workbench)
    assert result.embedding_model.id == "12" and len(workbench.queued) == 1 and len(workbench.queued[0]) == 2
    assert {(item.knowledge_id, item.tenant_id, item.actor_user_id) for item in workbench.queued[0]} == {
        (40, 101, 7),
        (41, 101, 7),
    }
    assert all(not hasattr(item, "model_id") for item in workbench.queued[0])
    state = snapshot_state(workbench)
    changed = [row for row in state["knowledge"] if row["id"] in {40, 41}]
    assert all(row["model"] == "11" and row["model_transition"]["pending_model_id"] == "12" for row in changed)
    assert all(row["model_config_revision"] == 4 for row in state["knowledge"] if row["id"] in {12, 13})
    assert {row["target_id"] for row in state["business_resource_reference"] if row["source_type"] == "knowledge"} == {
        "11",
        "12",
    }
    workbench.probe.assert_awaited_once()


@pytest.mark.parametrize("failure", ["second_source", "probe", "commit"])
async def test_every_precommit_failure_rolls_back_all_business_and_references(workbench, monkeypatch, failure):
    await fixtures.add(workbench, 40)
    await fixtures.add(workbench, 41)
    before = snapshot_state(workbench)
    if failure == "second_source":
        original = workbench.runtime.aapply_source_bindings

        async def fail(active, prepared):
            result = await original(active, prepared)
            if prepared.source_key.source_type == "knowledge" and prepared.source_key.source_id == "41":
                raise RuntimeError("second source failed")
            return result

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
    assert snapshot_state(workbench) == before and not workbench.queued


async def test_any_existing_space_missing_index_blocks_before_provider_or_default_side_effect(workbench):
    await fixtures.add(workbench, 40)
    await fixtures.add(workbench, 41)
    async with workbench.sessions() as session, session.begin():
        await session.execute(
            delete(BusinessReferenceSet).where(
                BusinessReferenceSet.tenant_id == 101,
                BusinessReferenceSet.source_type == "knowledge",
                BusinessReferenceSet.source_id == "41",
                BusinessReferenceSet.source_version == "current",
            )
        )
    before = snapshot_state(workbench)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await save(workbench)
    assert snapshot_state(workbench) == before and not workbench.queued
    workbench.probe.assert_not_awaited()


@pytest.mark.parametrize("caller", ["application_without_commands", "external_service"])
async def test_external_transaction_must_explicitly_own_nonempty_postcommit_commands(workbench, caller):
    await fixtures.add(workbench, 40)
    before = snapshot_state(workbench)
    async with workbench.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError) as raised:
            if caller == "application_without_commands":
                await defaults.ModelDefaultApplication.asave(
                    session, "linsight_llm", config(), login_user=workbench.user
                )
            else:
                await save(workbench, session=session)
        assert raised.value.kwargs["reason"] == "workbench_model_change_requires_command_owner"
        await session.rollback()
    assert snapshot_state(workbench) == before and not workbench.queued
    workbench.probe.assert_not_awaited()


async def test_explicit_application_commands_remain_with_external_transaction_owner(workbench):
    await fixtures.add(workbench, 40)
    before = snapshot_state(workbench)
    async with workbench.sessions() as session:
        result = await defaults.ModelDefaultApplication.asave_with_commands(
            session, "linsight_llm", config(), login_user=workbench.user, operation_id="one-operation"
        )
        assert (
            result.config.embedding_model.id == "12"
            and len(result.commands) == 1
            and result.commands[0].operation_id == "one-operation"
        )
        assert session.in_transaction() and not workbench.queued
        await session.rollback()
    assert snapshot_state(workbench) == before


async def test_initially_empty_space_inventory_is_rechecked_before_default_write(workbench, monkeypatch):
    original = knowledge.KnowledgeModelReferenceApplication.aplan_workbench_model_changes

    async def add_after_plan(*args, **kwargs):
        batch = await original(*args, **kwargs)
        await fixtures.add(workbench, 41)
        return batch

    monkeypatch.setattr(knowledge.KnowledgeModelReferenceApplication, "aplan_workbench_model_changes", add_after_plan)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await save(workbench)
    state = snapshot_state(workbench)
    assert not state["tenant_system_model_config"] and not workbench.queued
    assert next(row for row in state["knowledge"] if row["id"] == 41)["model"] == "11"
    workbench.probe.assert_not_awaited()


async def test_queue_failure_after_commit_does_not_claim_sql_was_rolled_back(workbench, monkeypatch):
    await fixtures.add(workbench, 40)
    queued = []

    def fail(commands):
        queued.extend(commands)
        raise RuntimeError("queue unavailable after commit")

    monkeypatch.setattr(service.LLMService, "_dispatch_model_default_commands", fail)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await save(workbench)
    state = snapshot_state(workbench)
    assert (
        queued
        and next(row for row in state["knowledge"] if row["id"] == 40)["model_transition"]["pending_model_id"] == "12"
    )
    assert (
        json.loads(next(row["value"] for row in state["tenant_system_model_config"] if row["tenant_id"] == 101))[
            "embedding_model"
        ]["id"]
        == "12"
    )


def test_dispatch_uses_frozen_business_expectations_and_actual_tenant_header(monkeypatch):
    from bisheng.knowledge.application.model_reference import KnowledgeModelRebuildCommand

    document = SimpleNamespace(apply_async=Mock())
    qa = SimpleNamespace(apply_async=Mock())
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.knowledge.rebuild_knowledge_worker",
        SimpleNamespace(rebuild_knowledge_celery=document),
    )
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge.qa", SimpleNamespace(rebuild_qa_knowledge_celery=qa))
    commands = tuple(
        KnowledgeModelRebuildCommand(i, t, "operation", 4, "generation", 101, 7) for i, t in [(40, 3), (41, 1)]
    )
    service.LLMService._dispatch_model_default_commands(commands)
    for task, ident in ((document, 40), (qa, 41)):
        task.apply_async.assert_called_once_with(
            args=(ident, None, 7),
            kwargs={
                "operation_id": "operation",
                "expected_model_config_revision": 4,
                "expected_index_generation": "generation",
            },
            headers={"tenant_id": 101},
        )
