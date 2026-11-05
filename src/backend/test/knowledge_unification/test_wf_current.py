"""Current/publish transitions preserve saved versions and reject invalid slots.

覆盖 AC: AC-37, AC-68, AC-71, AC-88, AC-91, AC-92. Force deletion is modelled
with real SQL tombstones; execution transport/graph construction stays isolated.
"""

from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa

from bisheng.api.services import flow as flow_service
from bisheng.api.services import workflow as workflow_service
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    ReferenceState,
    TargetLockReceipt,
    TransactionIdentity,
    VerifiedReferenceTarget,
)
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_wf_create as create_fixtures
from test.knowledge_unification import test_wf_save as save_fixtures
from test.knowledge_unification.test_wf_extract import graph, node

store = create_fixtures.store
tenant = create_fixtures.tenant
bindings = create_fixtures.bindings
saved = save_fixtures.saved
rows = create_fixtures.rows
save = save_fixtures.save


@pytest.fixture
async def configured(saved, monkeypatch):
    original = create_fixtures.SqlTargetOwner.alock_and_verify

    async def with_deletion_evidence(owner, session, target_keys, source_key, operation):
        receipts = []
        for key in target_keys:
            tombstone = await session.scalar(
                sa.select(ResourceReferenceTombstone).where(
                    ResourceReferenceTombstone.target_type == key.target_type.value,
                    ResourceReferenceTombstone.target_id == key.target_id,
                )
            )
            if tombstone is None:
                receipts.extend(await original(owner, session, (key,), source_key, operation))
                continue
            evidence = DeletionEvidence(tombstone.operation_id, key, tombstone.target_tenant_id, tombstone.stage)
            target = VerifiedReferenceTarget(
                key, tombstone.target_tenant_id, None, None, ReferenceState.INVALID_DELETED, "deleted", evidence
            )
            receipts.append(TargetLockReceipt(source_key, target, TransactionIdentity.capture(session), owner))
        return tuple(receipts)

    monkeypatch.setattr(create_fixtures.SqlTargetOwner, "alock_and_verify", with_deletion_evidence)
    monkeypatch.setattr(workflow_service, "get_async_db_session", saved.session_factory)
    monkeypatch.setattr(
        workflow_service, "get_reference_binding_runtime", AsyncMock(return_value=saved.runtime), raising=False
    )
    monkeypatch.setattr(workflow_service, "require_business_action", AsyncMock())
    monkeypatch.setattr(workflow_service, "Workflow", Mock())
    await save(saved, 1, graph(node("old-current", "llm", model_id=7)))
    await save(saved, 2, graph(node("a", "llm", model_id=7), node("b", "llm", model_id=7)))
    return saved


async def force_delete_model(context):
    async with context.session_factory() as session, session.begin():
        await session.execute(sa.text("DELETE FROM wf_test_target WHERE target_type='model' AND target_id='7'"))
        session.add(
            ResourceReferenceTombstone(
                id=1,
                tenant_id=101,
                target_type="model",
                target_id="7",
                target_tenant_id=101,
                operation_id="force-delete-model-7",
                operation_type="force_delete",
                stage="deleted",
                actor_type="user",
                actor_id="11",
            )
        )


async def current(context, version_id):
    return await flow_service.FlowService.change_current_version(context.request, context.user, "wf", version_id)


async def publish(context, version_id, status=2):
    return await workflow_service.WorkFlowService.update_flow_status(context.user, "wf", version_id, status)


async def test_switch_current_keeps_old_and_all_other_saved_version_bindings(configured):
    before = rows(configured, "business_resource_reference")
    old_set = next(row for row in rows(configured, "business_reference_set") if row["source_version"] == "1")
    assert (await current(configured, 2)).status_code == 200
    assert {
        (row["source_version"], row["slot_key"], row["target_id"])
        for row in rows(configured, "business_resource_reference")
    } == {(row["source_version"], row["slot_key"], row["target_id"]) for row in before}
    assert next(row for row in rows(configured, "business_reference_set") if row["source_version"] == "1") == old_set
    assert [(row["id"], row["is_current"]) for row in rows(configured, "flowversion")] == [(1, 0), (2, 1), (3, 0)]


@pytest.mark.parametrize("version_id", [1, 2])
async def test_invalid_current_or_selected_version_cannot_be_selected_even_as_noop(configured, version_id):
    await force_delete_model(configured)
    before = rows(configured, "flowversion")
    with pytest.raises(ResourceReferenceInvalidError):
        await current(configured, version_id)
    assert rows(configured, "flowversion") == before


async def test_invalid_version_cannot_publish_or_construct_runtime_graph(configured):
    await force_delete_model(configured)
    with pytest.raises(ResourceReferenceInvalidError):
        await publish(configured, 2)
    workflow_service.Workflow.assert_not_called()
    assert next(row for row in rows(configured, "flow") if row["id"] == "wf")["status"] == 1


async def test_valid_publish_atomically_changes_status_and_current_without_releasing_history(configured):
    before = {(row["source_version"], row["slot_key"]) for row in rows(configured, "business_resource_reference")}
    await publish(configured, 2)
    assert next(row for row in rows(configured, "flow") if row["id"] == "wf")["status"] == 2
    assert next(row for row in rows(configured, "flowversion") if row["id"] == 2)["is_current"] == 1
    assert {
        (row["source_version"], row["slot_key"]) for row in rows(configured, "business_resource_reference")
    } == before


async def test_publish_binding_failure_rolls_back_status_current_and_guard_revisions(configured, monkeypatch):
    before_flow = rows(configured, "flow")
    before_versions = rows(configured, "flowversion")
    before_sets = rows(configured, "business_reference_set")
    original = configured.runtime.aapply_source_bindings

    async def fail_after_write(session, prepared):
        await original(session, prepared)
        raise RuntimeError("binding write failed")

    monkeypatch.setattr(configured.runtime, "aapply_source_bindings", fail_after_write)
    with pytest.raises(RuntimeError, match="binding write failed"):
        await publish(configured, 2)
    assert rows(configured, "flow") == before_flow
    assert rows(configured, "flowversion") == before_versions
    assert rows(configured, "business_reference_set") == before_sets


async def test_partial_repair_retains_other_invalid_slot_and_only_fully_repaired_version_can_publish(configured):
    await force_delete_model(configured)
    with configured.sync_engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO wf_test_target(target_type,target_id,tenant_id) VALUES('model','8',101)")
        )
    await save(configured, 2, graph(node("a", "llm", model_id=8), node("b", "llm", model_id=7)))
    assert {
        (row["slot_key"], row["target_id"])
        for row in rows(configured, "business_resource_reference")
        if row["source_version"] == "2"
    } == {
        ("node:a.model_id", "8"),
        ("node:b.model_id", "7"),
    }
    with pytest.raises(ResourceReferenceInvalidError):
        await publish(configured, 2)
    await save(configured, 2, graph(node("a", "llm", model_id=8), node("b", "llm", model_id=8)))
    await publish(configured, 2)
    assert any(
        row["source_version"] == "1" and row["target_id"] == "7"
        for row in rows(configured, "business_resource_reference")
    )


async def test_current_switch_rejects_configuration_index_drift(configured):
    async with configured.session_factory() as session, session.begin():
        version = await session.get(FlowVersion, 2)
        version.data = graph(node("drift", "llm", model_id=7))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await current(configured, 2)


async def test_unpublish_still_allows_stopping_business_with_invalid_configuration(configured):
    await publish(configured, 2)
    await force_delete_model(configured)
    await publish(configured, 2, status=1)
    async with configured.session_factory() as session:
        root = await session.get(Flow, "wf")
        assert root.status == 1
    assert len(rows(configured, "business_resource_reference")) == 3
