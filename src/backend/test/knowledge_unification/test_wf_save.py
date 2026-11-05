"""Saved workflow versions own independent atomic binding sets.

覆盖 AC: AC-71, AC-87, AC-88. Uses the actual FlowService entry and SQL-backed
binding runtime, including a flushed new version's generated source identity.
"""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.api.services import flow as flow_service
from bisheng.api.v1.schemas import FlowVersionCreate
from bisheng.common.errcode.flow import WorkFlowOnlineEditError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository
from bisheng.workflow.domain.services.reference_extractor import (
    WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
    extract_workflow_version_references,
)
from test.knowledge_unification import test_wf_create as create_fixtures
from test.knowledge_unification.test_wf_extract import graph, node

store = create_fixtures.store
tenant = create_fixtures.tenant
bindings = create_fixtures.bindings
rows = create_fixtures.rows


def key(version_id):
    return SourceKey(101, "workflow_version", "wf", str(version_id))


@pytest.fixture
async def saved(bindings, monkeypatch):
    monkeypatch.setattr(flow_service, "require_business_action", AsyncMock())
    monkeypatch.setattr(flow_service.FlowService, "update_flow_hook", AsyncMock())
    async with bindings.session_factory() as session, session.begin():
        for version_id in (1, 2, 3):
            prepared = await bindings.runtime.aprepare_source_bindings(
                session,
                key(version_id),
                (),
                extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lambda sql: WorkflowVersionRepository.alock_root(sql, "wf", 101),
                new_source=True,
                effective=version_id != 3,
            )
            await bindings.runtime.aapply_source_bindings(session, prepared)
    return bindings


async def save(context, version_id, saved_data, name=None):
    return await flow_service.FlowService.update_version_info(
        context.request,
        context.user,
        version_id,
        FlowVersionCreate(name=name, data=saved_data),
    )


async def test_new_leaf_uses_flushed_id_and_draft_reference_set(saved):
    result = await flow_service.FlowService.create_new_version(
        saved.user, "wf", FlowVersionCreate(name="new draft", data=graph(node("n", "llm", model_id=7)))
    )
    assert result.status_code == 200 and result.data.id not in {None, 1, 2, 3}
    indexed = [row for row in rows(saved, "business_reference_set") if row["source_version"] == str(result.data.id)]
    assert len(indexed) == 1 and indexed[0]["effective"] == 1 and indexed[0]["ready"] == 1
    references = rows(saved, "business_resource_reference")
    assert [(row["source_version"], row["slot_key"], row["target_id"]) for row in references] == [
        (str(result.data.id), "node:n.model_id", "7")
    ]


async def test_current_and_noncurrent_saved_versions_keep_independent_sets(saved):
    first = graph(node("first", "llm", model_id=7))
    second = graph(node("second", "llm", model_id=7))
    assert (await save(saved, 1, first)).status_code == 200
    assert (await save(saved, 2, second)).status_code == 200
    assert {(row["source_version"], row["slot_key"]) for row in rows(saved, "business_resource_reference")} == {
        ("1", "node:first.model_id"),
        ("2", "node:second.model_id"),
    }
    root = next(row for row in rows(saved, "flow") if row["id"] == "wf")
    async with saved.session_factory() as session:
        assert (await session.get(Flow, root["id"])).data == first


async def test_binding_failure_rolls_back_existing_definition_and_source_revisions(saved, monkeypatch):
    before_versions = rows(saved, "flowversion")
    before_sets = rows(saved, "business_reference_set")
    original = saved.runtime.aapply_source_bindings

    async def fail_after_write(session, prepared):
        await original(session, prepared)
        raise RuntimeError("binding write failed")

    monkeypatch.setattr(saved.runtime, "aapply_source_bindings", fail_after_write)
    with pytest.raises(RuntimeError, match="binding write failed"):
        await save(saved, 1, graph(node("first", "llm", model_id=7)), name="changed")
    assert rows(saved, "flowversion") == before_versions
    assert rows(saved, "business_reference_set") == before_sets
    assert not rows(saved, "business_resource_reference")
    flow_service.FlowService.update_flow_hook.assert_not_awaited()


async def test_binding_failure_rolls_back_new_flushed_leaf(saved, monkeypatch):
    original = saved.runtime.aapply_source_bindings

    async def fail_after_write(session, prepared):
        await original(session, prepared)
        raise RuntimeError("binding write failed")

    monkeypatch.setattr(saved.runtime, "aapply_source_bindings", fail_after_write)
    with pytest.raises(RuntimeError, match="binding write failed"):
        await flow_service.FlowService.create_new_version(
            saved.user, "wf", FlowVersionCreate(name="uncommitted", data=graph(node("n", "llm", model_id=7)))
        )
    assert {row["id"] for row in rows(saved, "flowversion")} == {1, 2, 3}
    assert not rows(saved, "business_resource_reference")


async def test_no_reference_incomplete_new_draft_still_gets_ready_source(saved):
    result = await flow_service.FlowService.create_new_version(
        saved.user, "wf", FlowVersionCreate(name="blank", data={})
    )
    indexed = [row for row in rows(saved, "business_reference_set") if row["source_version"] == str(result.data.id)]
    assert len(indexed) == 1 and indexed[0]["ready"] == 1


async def test_existing_unindexed_version_fails_closed_instead_of_bootstrapping(saved):
    async with saved.session_factory() as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(
                BusinessReferenceSet.source_id == "wf", BusinessReferenceSet.source_version == "1"
            )
        )
    before = rows(saved, "flowversion")
    with pytest.raises(ReferenceCoverageNotReadyError):
        await save(saved, 1, graph(node("n", "llm", model_id=7)))
    assert rows(saved, "flowversion") == before


async def test_actual_configuration_drift_is_rejected_instead_of_reindexed_by_ordinary_save(saved):
    async with saved.session_factory() as session, session.begin():
        version = await session.get(FlowVersion, 2)
        version.data = graph(node("unindexed-old", "llm", model_id=7))
    before = rows(saved, "flowversion")
    before_sets = rows(saved, "business_reference_set")
    with pytest.raises(ReferenceCoverageNotReadyError):
        await save(saved, 2, graph(node("next", "llm", model_id=7)))
    assert rows(saved, "flowversion") == before
    assert rows(saved, "business_reference_set") == before_sets
    assert not rows(saved, "business_resource_reference")


async def test_removing_one_semantic_slot_keeps_other_slot_on_same_target(saved):
    await save(saved, 2, graph(node("a", "llm", model_id=7), node("b", "llm", model_id=7)))
    await save(saved, 2, graph(node("b", "llm", model_id=7)))
    assert [(row["source_version"], row["slot_key"]) for row in rows(saved, "business_resource_reference")] == [
        ("2", "node:b.model_id")
    ]


async def test_restoring_deleted_version_reestablishes_its_source_without_changing_current(saved):
    result = await save(saved, 3, graph(node("restored", "llm", model_id=7)))
    assert result.data.is_delete == 0 and result.data.is_current == 0
    assert {(row["source_version"], row["slot_key"]) for row in rows(saved, "business_resource_reference")} == {
        ("3", "node:restored.model_id")
    }
    assert next(row for row in rows(saved, "flowversion") if row["id"] == 1)["is_current"] == 1


async def test_new_leaf_cannot_survive_root_becoming_deleted_at_locked_recheck(saved, monkeypatch):
    original = WorkflowVersionRepository.alock_root

    async def deleted_before_root_recheck(session, flow_id, tenant_id):
        await session.execute(
            sa.update(Flow).where(Flow.id == flow_id, Flow.tenant_id == tenant_id).values(is_delete=1)
        )
        return await original(session, flow_id, tenant_id)

    monkeypatch.setattr(WorkflowVersionRepository, "alock_root", deleted_before_root_recheck)
    with pytest.raises(NotFoundError):
        await flow_service.FlowService.create_new_version(
            saved.user, "wf", FlowVersionCreate(name="must rollback", data={})
        )
    assert {row["id"] for row in rows(saved, "flowversion")} == {1, 2, 3}


async def test_empty_graph_update_cannot_bypass_online_current_version_edit_guard(saved):
    async with saved.session_factory() as session, session.begin():
        root = await session.get(Flow, "wf")
        root.status = 2
    before = rows(saved, "flowversion")
    result = await save(saved, 1, {})
    assert result.status_code == WorkFlowOnlineEditError.Code
    assert rows(saved, "flowversion") == before


async def test_partial_save_cannot_overwrite_a_newer_normal_save_before_runtime_candidate_read(saved, monkeypatch):
    original = saved.runtime.aprepare_source_bindings
    newer_data = graph(node("concurrent", "llm", model_id=7))

    async def concurrent_save_then_prepare(session, source_key, references, **kwargs):
        async with saved.session_factory() as concurrent, concurrent.begin():
            root = await WorkflowVersionRepository.aget_root(concurrent, "wf", 101)
            prepared = await original(
                concurrent,
                key(2),
                extract_workflow_version_references(newer_data),
                extractor_version=WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
                lock_source_root=lambda sql: WorkflowVersionRepository.alock_root(sql, "wf", 101),
            )
            await WorkflowVersionRepository.aupdate_version(
                concurrent, root, FlowVersion(id=2, flow_id="wf", name="concurrent", data=newer_data)
            )
            await saved.runtime.aapply_source_bindings(concurrent, prepared)
        return await original(session, source_key, references, **kwargs)

    monkeypatch.setattr(saved.runtime, "aprepare_source_bindings", concurrent_save_then_prepare)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await save(saved, 2, None, name="stale rename")
    async with saved.session_factory() as session:
        version = await session.get(FlowVersion, 2)
        assert version.name == "concurrent" and version.data == newer_data
    assert [(row["source_version"], row["slot_key"]) for row in rows(saved, "business_resource_reference")] == [
        ("2", "node:concurrent.model_id")
    ]
