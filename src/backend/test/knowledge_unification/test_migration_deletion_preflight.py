"""M2 must close all real direct and ancestor deletion evidence."""

from datetime import datetime

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_preflight import source_decision
from bisheng.knowledge.application.unification_reference_state import OriginalReferenceState
from bisheng.knowledge.application.unification_sources import ReferenceInventoryRecord
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey, reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_migration_resource_repository as original
from test.knowledge_unification.test_migration_preflight import native as native, resource_native as resource_native


async def captured_record(native, *, live=False, direct_stage="deleted", ancestor_stage="deleted", ancestor_owner=101):
    source = SourceKey(101, "workflow_version", "original-flow", "v1")
    target = TargetKey("knowledge_file", "1")
    reference = ReferenceSpec("saved-file", target)
    if live:
        await native.insert(original.Knowledge, [original.resource(9000)])
        await native.insert(original.KnowledgeFile, [original.file(1)])
    common = {
        "tenant_id": 101,
        "source_type": source.source_type.value,
        "source_id": source.source_id,
        "source_revision": 4,
    }
    await native.insert(
        BusinessReferenceSet,
        [
            common
            | {
                "source_version": "__root__",
                "record_kind": "root_guard",
                "effective": False,
                "ready": False,
                "extractor_version": "root-guard-v1",
                "digest": reference_set_digest(()),
            },
            common
            | {
                "source_version": "v1",
                "record_kind": "source",
                "effective": False,
                "ready": True,
                "extractor_version": "workflow-v1",
                "digest": reference_set_digest((reference,)),
            },
        ],
    )
    await native.insert(
        BusinessResourceReference,
        [
            common
            | {
                "source_version": "v1",
                "slot_key": reference.slot_key,
                "target_type": "knowledge_file",
                "target_id": "1",
                "target_tenant_id": 101,
                "target_space_id": "9000",
            }
        ],
    )
    await native.insert(
        ResourceReferenceTombstone,
        [
            {
                "tenant_id": owner,
                "target_tenant_id": owner,
                "target_type": kind,
                "target_id": ident,
                "operation_id": operation,
                "operation_type": "direct_delete",
                "stage": stage,
                "actor_type": "user",
                "actor_id": "7",
                "deleted_at": datetime(2026, 11, 9) if stage == "deleted" else None,
            }
            for kind, ident, owner, stage, operation in (
                ("knowledge_file", "1", 101, direct_stage, "old-file-delete"),
                ("knowledge_space", "9000", ancestor_owner, ancestor_stage, "later-space-delete"),
            )
        ],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        fact = (await KnowledgeMigrationTargetRepository().ainspect(session, source_key=source, targets=(target,)))[0]
        state = OriginalReferenceState()
        snapshot = await state.repository.aload_raw_snapshot(session, source_key=source)
        _, states = await state.acapture(
            session,
            source_key=source,
            references=(reference,),
            physical={target: fact},
            tombstone_cache={},
            snapshot=snapshot,
        )
        assert not session.new and not session.dirty
    return ReferenceInventoryRecord(
        source,
        reference.slot_key,
        target,
        "explicit_id",
        fact,
        states[(reference.slot_key, target.target_type.value, target.target_id)],
    )


@pytest.mark.parametrize("direct_stage,ancestor_stage", [("deleting", "deleted"), ("deleted", "deleting")])
@pytest.mark.parametrize("live", [False, True])
async def test_actual_m2_rejects_unfinished_direct_or_ancestor_deletion(native, direct_stage, ancestor_stage, live):
    record = await captured_record(native, live=live, direct_stage=direct_stage, ancestor_stage=ancestor_stage)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        source_decision(record, tenant_id=101)


async def test_actual_m2_checks_ancestor_owner_even_when_direct_evidence_exists(native):
    record = await captured_record(native, ancestor_owner=202)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        source_decision(record, tenant_id=101)


async def test_two_completed_deletes_same_owner_keep_both_original_evidence_and_remain_invalid(native):
    record = await captured_record(native)
    result = source_decision(record, tenant_id=101)
    assert result.data["disposition"] == "existing_invalid_deleted"
    assert not result.data["exists"]
    assert "old-file-delete" in record.frozen_state and "later-space-delete" in record.frozen_state


async def test_completed_deletion_does_not_make_live_target_valid(native):
    record = await captured_record(native, live=True)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        source_decision(record, tenant_id=101)
