"""Approved historical repairs use selected backup plans and native SQL replay."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from test.knowledge_unification import test_prepare_history as fixtures

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from scripts import prepare_f118_history as script

history, native, resource_native = fixtures.history, fixtures.native, fixtures.resource_native


async def execute(history, plan, **kwargs):
    return await script.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7, **kwargs
    )


async def test_orphan_metadata_cleanup_keeps_valid_files_and_replays_same_plan(history):
    async with script.global_session(history.sessions) as session:
        session.add(KnowledgeDocument(id=50, knowledge_id=404, primary_version_id=50))
        session.add(
            KnowledgeDocumentVersion(id=50, document_id=50, knowledge_file_id=30, version_no=1, is_primary=True)
        )
        session.add(Tag(id=51, name="orphan", business_type="knowledge", business_id="404", tenant_id=101, user_id=7))
        session.add(TagLink(id=51, tag_id=51, resource_type=9, resource_id="30", tenant_id=101, user_id=7))
        session.add(SpaceChannelMember(id=51, business_type="space", business_id="404", user_id=7, user_role="member"))
    plan = await script.capture(history.sessions, history.fga)
    removed = {(i["table"], i["before"]["id"]) for i in plan["business"]["deletes"]}
    assert removed == {
        ("knowledge_document", 50),
        ("knowledge_document_version", 50),
        ("tag", 51),
        ("taglink", 51),
        ("space_channel_member", 51),
    }
    assert not plan["blocked"] and history.fga.writes == 0
    await execute(history, plan)
    writes = history.fga.writes
    await execute(history, plan)
    assert history.fga.writes == writes
    async with history.sessions() as session:
        assert await session.get(KnowledgeFile, 30) is not None
        for model, ident in [
            (KnowledgeDocument, 50),
            (KnowledgeDocumentVersion, 50),
            (Tag, 51),
            (TagLink, 51),
            (SpaceChannelMember, 51),
        ]:
            assert await session.get(model, ident) is None


async def test_parent_owner_corrections_and_unmapped_embedding_are_selected_backed_and_replayable(history):
    async with script.global_session(history.sessions) as session:
        await session.exec(sa.update(KnowledgeFile).where(KnowledgeFile.id == 30).values(tenant_id=202))
        session.add(Flow(id="parent", tenant_id=101, name="parent", user_id=7, flow_type=10))
        session.add(FlowVersion(id=71, tenant_id=202, flow_id="parent", name="v", flow_type=10))
        session.add(Knowledge(id=11, tenant_id=101, user_id=7, name="empty", type=0, model="old-unmapped-embedding"))
    plan = await script.capture(history.sessions, history.fga)
    updates = {(i["table"], i["before"]["id"]): i["values"] for i in plan["business"]["updates"]}
    assert updates == {
        ("knowledgefile", 30): {"tenant_id": 101},
        ("flowversion", 71): {"tenant_id": 101},
        ("knowledge", 11): {"model": None},
    }
    assert not plan["blocked"]
    await execute(history, plan)
    await execute(history, plan)
    async with script.global_session(history.sessions) as session:
        assert (await session.get(KnowledgeFile, 30)).tenant_id == 101
        assert (await session.get(FlowVersion, 71)).tenant_id == 101
        assert (await session.get(Knowledge, 11)).model is None


async def test_metadata_drift_blocks_before_any_cleanup(history):
    async with script.global_session(history.sessions) as session:
        session.add(KnowledgeDocument(id=50, knowledge_id=404))
    plan = await script.capture(history.sessions, history.fga)
    async with script.global_session(history.sessions) as session:
        session.add(Knowledge(id=404, tenant_id=101, user_id=7, name="revived", type=3))
    with pytest.raises(KnowledgeOperationPlanConflictError, match=""):
        await execute(history, plan)
    assert history.fga.writes == 0
    async with history.sessions() as session:
        assert await session.get(KnowledgeDocument, 50) is not None


async def test_orphan_file_physical_failure_keeps_sql_and_original_plan(history):
    async with script.global_session(history.sessions) as session:
        session.add(
            KnowledgeFile(
                id=90,
                knowledge_id=10,
                tenant_id=101,
                file_name="orphan",
                file_type=1,
                file_level_path="/404",
                level=1,
                status=3,
            )
        )
    plan = await script.capture(history.sessions, history.fga)
    assert [item["file"]["id"] for item in plan["business"]["physical"]] == [90]
    physical = SimpleNamespace(apply=AsyncMock(side_effect=RuntimeError("transport unavailable")))
    with pytest.raises(RuntimeError):
        await execute(history, plan, physical=physical)
    assert history.fga.writes == 0
    async with history.sessions() as session:
        assert await session.get(KnowledgeFile, 90) is not None


@pytest.mark.parametrize("with_original_binding", [False, True])
async def test_missing_library_requires_original_binding_evidence(history, with_original_binding):
    from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob

    async with script.global_session(history.sessions) as session:
        session.add(KnowledgeFile(id=90, tenant_id=101, knowledge_id=404, file_name="orphan.pdf", file_type=1))
        if with_original_binding:
            session.add(
                KnowledgeSpaceDeleteJob(
                    tenant_id=101,
                    space_id=404,
                    applicant_user_id=7,
                    manifest={
                        "rows": [90],
                        "knowledge": {
                            "id": 404,
                            "tenant_id": 101,
                            "type": 3,
                            "index_name": "original-es",
                            "collection_name": "original-mv",
                        },
                    },
                )
            )
    plan = await script.capture(history.sessions, history.fga)
    if with_original_binding:
        item = plan["business"]["physical"][0]
        assert item["file"]["id"] == 90 and item["knowledge"]["index_name"] == "original-es"
    else:
        assert not plan["business"]["physical"]
        assert any(row["reason"] == "orphan_original_index_binding_unavailable" for row in plan["business"]["blocked"])
    assert history.fga.writes == 0


async def test_file_tenant_repair_keeps_tag_and_link_owners_consistent(history):
    async with script.global_session(history.sessions) as session:
        await session.exec(sa.update(KnowledgeFile).where(KnowledgeFile.id == 30).values(tenant_id=202))
        session.add(Tag(id=52, tenant_id=202, user_id=7, name="tag", business_type="knowledge", business_id="10"))
        session.add(TagLink(id=52, tenant_id=202, user_id=7, tag_id=52, resource_type=8, resource_id="30"))
    plan = await script.capture(history.sessions, history.fga)
    assert not plan["blocked"]
    await execute(history, plan)
    async with script.global_session(history.sessions) as session:
        assert (await session.get(KnowledgeFile, 30)).tenant_id == 101
        assert (await session.get(Tag, 52)).tenant_id == (await session.get(TagLink, 52)).tenant_id == 101


async def test_unowned_orphan_fga_relations_block_before_physical_or_sql_effects(history):
    async with script.global_session(history.sessions) as session:
        session.add(
            KnowledgeFile(
                id=90,
                tenant_id=101,
                knowledge_id=10,
                file_name="orphan.pdf",
                file_type=1,
                file_level_path="/404",
                level=1,
            )
        )
    plan = await script.capture(history.sessions, history.fga)
    history.fga.present.add(("user:7", "visible", "knowledge_file:90"))
    physical = SimpleNamespace(apply=AsyncMock())
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await execute(history, plan, physical=physical)
    physical.apply.assert_not_awaited()
    async with history.sessions() as session:
        assert await session.get(KnowledgeFile, 90) is not None


@pytest.mark.parametrize("model,with_qa", [("0", False), ("-1", False), ("old-embedding", True)])
async def test_empty_embedding_cleanup_does_not_clear_invalid_ids_or_nonempty_qa(history, model, with_qa):
    from bisheng.knowledge.domain.models.knowledge_file import QAKnowledge

    async with script.global_session(history.sessions) as session:
        session.add(Knowledge(id=12, tenant_id=101, user_id=7, name="qa", type=1, model=model))
        if with_qa:
            session.add(QAKnowledge(id=91, tenant_id=101, user_id=7, knowledge_id=12, questions=["q"], answers="a"))
    plan = await script.capture(history.sessions, history.fga)
    assert any(row["table"] == "knowledge" and row["id"] == 12 for row in plan["business"]["blocked"])
    assert not any(row["table"] == "knowledge" and row["before"]["id"] == 12 for row in plan["business"]["updates"])
