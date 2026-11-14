"""T1018: saved QA references keep their original physical qualification.

覆盖 AC: AC-37, AC-55, AC-65, AC-88.
"""

import json

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.database.models.flow_version import FlowVersion
from bisheng.knowledge.application.unification_preflight import source_decision
from bisheng.knowledge.application.unification_reference_state import OriginalReferenceState
from bisheng.knowledge.application.unification_sources import ReferenceInventoryRecord
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
from bisheng.resource_reference.application.contracts import SourceKey
from bisheng.workflow.domain.services.reference_extractor import extract_workflow_version_references
from test.knowledge_unification import test_migration_inventory_application as inventory
from test.knowledge_unification import test_migration_preflight as original
from test.knowledge_unification import test_wf_extract as workflow

resource_native = original.resource_native
native = original.native
complete = inventory.complete
transport = inventory.transport
module = inventory.module


def saved_graph():
    return workflow.graph(workflow.node("saved-qa", "qa_retriever", qa_knowledge_id=[{"key": 9001}]))


async def test_real_saved_qa_extractor_and_native_target_are_retained_without_new_authority(native):
    await native.insert(original.original.Knowledge, [original.original.resource(9001, type=1)])
    refs = extract_workflow_version_references(saved_graph())
    assert len(refs) == 1
    ref = refs[0]
    source = SourceKey(101, "workflow_version", "old-qa-flow", "v1")
    async with AsyncSession(native.engine) as session, session.begin():
        fact = (await KnowledgeMigrationTargetRepository().ainspect(session, source_key=source, targets=(ref.target,)))[
            0
        ]
        assert fact.exists and fact.space_exists and fact.knowledge_type == 1
        state = OriginalReferenceState()
        index_snapshot = await state.repository.aload_raw_snapshot(session, source_key=source)
        _, states = await state.acapture(
            session,
            source_key=source,
            references=refs,
            physical={ref.target: fact},
            tombstone_cache={},
            snapshot=index_snapshot,
        )
        decision = source_decision(
            ReferenceInventoryRecord(
                source,
                ref.slot_key,
                ref.target,
                "explicit_id",
                fact,
                states[(ref.slot_key, ref.target.target_type.value, ref.target.target_id)],
            ),
            tenant_id=101,
        )
        assert decision.data["disposition"] == "existing_saved_slot"
        assert decision.data["target_id"] == ref.target.target_id
        assert decision.data["revision_digest"] == fact.revision_digest
        assert not session.new and not session.dirty and not session.deleted


async def test_actual_formal_inventory_keeps_qa_type_and_saved_retriever_id_without_conversion(
    module, complete, transport
):
    await complete.insert(original.original.Knowledge, [original.original.resource(9001, type=1, model=None)])
    graph = saved_graph()
    async with AsyncSession(complete.engine) as session, session.begin():
        session.add(inventory.raw.flow("saved-qa-flow", data=graph))
        session.add(
            FlowVersion(
                id=991,
                tenant_id=101,
                flow_id="saved-qa-flow",
                name="original saved QA",
                data=graph,
                is_current=1,
                is_delete=0,
            )
        )
    app = inventory.application(module, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await app.arun(session, **transport.inputs)
    records = []
    async for page in app.aiter_frozen_pages(
        frozen, **{k: transport.inputs[k] for k in ("environment", "backup_ref", "schema_ref")}
    ):
        records.extend(json.loads(page.content)["records"])
    decisions = [r for r in records if r.get("record_type") == "source_decision" and r.get("target_id") == "9001"]
    assert decisions and all(r["disposition"] == "existing_saved_slot" for r in decisions)
    assert not [
        r
        for r in records
        if r.get("record_type") in {"resource_conversion", "space_membership_header"} and r.get("knowledge_id") == 9001
    ]
    async with complete.engine.connect() as connection:
        assert (
            await connection.execute(
                sa.select(inventory.resources.Knowledge.type).where(inventory.resources.Knowledge.id == 9001)
            )
        ).scalar_one() == 1
        assert (
            await connection.execute(
                sa.select(sa.func.count())
                .select_from(SpaceChannelMember)
                .where(SpaceChannelMember.business_id == "9001")
            )
        ).scalar_one() == 0
