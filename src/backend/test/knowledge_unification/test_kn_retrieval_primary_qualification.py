"""Actual F029 SQL and file visibility must prove a successful primary version."""

import pytest
from sqlalchemy import update

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.knowledge_unification.test_kn_rebuild_retrieval_gate import (
    call,
)
from test.knowledge_unification.test_kn_rebuild_retrieval_gate import (
    concrete_tenant as concrete_tenant,
)
from test.knowledge_unification.test_kn_rebuild_retrieval_gate import (
    retrieval as retrieval,
)
from test.knowledge_unification.test_kn_rebuild_retrieval_gate import (
    writes as writes,
)


async def idle(retrieval):
    session = retrieval.writes.session
    await session.execute(update(Knowledge).where(Knowledge.id == 19).values(state=1))
    await session.commit()
    return session


async def unregistered(session):
    session.add(
        KnowledgeFile(
            id=104,
            tenant_id=101,
            knowledge_id=19,
            user_id=7,
            file_name="unregistered.txt",
            file_type=1,
            status=2,
            md5="unregistered",
            file_level_path="",
            level=0,
        )
    )
    await session.commit()


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
async def test_unregistered_successful_file_is_not_a_retrievable_primary(retrieval, entry):
    session = await idle(retrieval)
    await unregistered(session)
    retrieval.facts.files = {101, 104}
    result = await call(retrieval.service, entry, ids=[101, 104])
    assert result.milvus_expr == "document_id in [101]" if entry == "prefilter" else result == {101}
    retrieval.writes.service._require_action.assert_not_awaited()


@pytest.mark.parametrize("entry", ["prefilter", "postfilter"])
@pytest.mark.parametrize("corruption", ["pointer", "document_space", "duplicate_primary_alias"])
async def test_primary_qualification_rejects_inconsistent_actual_version_chain(retrieval, entry, corruption):
    session = await idle(retrieval)
    if corruption == "pointer":
        await session.execute(
            update(KnowledgeDocument).where(KnowledgeDocument.id == 500).values(primary_version_id=602)
        )
    elif corruption == "document_space":
        await session.execute(update(KnowledgeDocument).where(KnowledgeDocument.id == 500).values(knowledge_id=20))
    else:
        session.add(KnowledgeDocument(id=590, knowledge_id=19, primary_version_id=690))
        session.add(
            KnowledgeDocumentVersion(id=690, document_id=590, knowledge_file_id=101, version_no=1, is_primary=True)
        )
    await session.commit()
    retrieval.facts.files = {101}
    result = await call(retrieval.service, entry, ids=[101])
    assert result.is_empty if entry == "prefilter" else result == set()


@pytest.mark.parametrize("kind", [0, 1])
async def test_original_library_and_qa_qualification_remains_unchanged(retrieval, kind):
    session = await idle(retrieval)
    await unregistered(session)
    await session.execute(update(Knowledge).where(Knowledge.id == 19).values(type=kind))
    await session.commit()
    retrieval.facts.files = {101, 104}
    assert await call(retrieval.service, "postfilter", ids=[101, 104]) == {101, 104}


async def test_same_visible_file_loses_retrieval_after_primary_pointer_changes(retrieval):
    session = await idle(retrieval)
    retrieval.facts.files = {101, 103}
    assert await call(retrieval.service, "postfilter", ids=[101, 103]) == {101}
    await session.execute(
        update(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == 700).values(is_primary=False)
    )
    await session.execute(
        update(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == 702).values(is_primary=True)
    )
    await session.execute(update(KnowledgeDocument).where(KnowledgeDocument.id == 500).values(primary_version_id=702))
    await session.commit()
    assert await call(retrieval.service, "postfilter", ids=[101, 103]) == {103}
    assert await retrieval.service.post_filter_visible_files(19, [101]) == {101}
