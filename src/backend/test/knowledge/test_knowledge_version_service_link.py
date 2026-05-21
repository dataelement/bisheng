"""Link operation: associate a file into a target doc; auto-promote to primary."""
import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock, AsyncMock

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService


@pytest.fixture
def enable_switch(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod
    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = True
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)


def _build_svc(session):
    return KnowledgeVersionService(
        request=MagicMock(), login_user=MagicMock(),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
    )


async def _seed_doc(session, knowledge_id, file_id, file_name="a.pdf", md5=None, status=2):
    # idempotent space seed (the first call creates, later seeds reuse)
    from sqlmodel import select
    existing = await session.execute(select(Knowledge).where(Knowledge.id == knowledge_id))
    if existing.scalars().first() is None:
        session.add(Knowledge(id=knowledge_id, name=f"space{knowledge_id}", type=3, user_id=1))
        await session.commit()

    session.add(KnowledgeFile(id=file_id, knowledge_id=knowledge_id, file_name=file_name,
                              file_type=1, status=status, md5=md5))
    await session.commit()
    doc = KnowledgeDocument(knowledge_id=knowledge_id)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    v = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=file_id, version_no=1, is_primary=True)
    session.add(v)
    await session.commit()
    await session.refresh(v)
    doc.primary_version_id = v.id
    session.add(doc)
    await session.commit()
    return doc, v


@pytest.mark.asyncio
async def test_link_promotes_new_version_to_primary(enable_switch, async_db_session, monkeypatch):
    target_doc, target_v1 = await _seed_doc(async_db_session, 1, 100, "target.pdf", md5="aaa")
    current_doc, current_v1 = await _seed_doc(async_db_session, 1, 101, "incoming.pdf", md5="bbb")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.link_file_to_document(
        knowledge_file_id=101, target_document_id=target_doc.id,
    )
    assert result.new_version_no == 2

    versions = await svc.version_repo.find_by_document_id(target_doc.id)
    by_no = {v.version_no: v for v in versions}
    assert by_no[1].is_primary is False
    assert by_no[1].knowledge_file_id == 100
    assert by_no[2].is_primary is True
    assert by_no[2].knowledge_file_id == 101

    target_doc_fresh = await svc.doc_repo.find_by_id(target_doc.id)
    assert target_doc_fresh.primary_version_id == by_no[2].id

    # original independent doc + V1 row for file 101 are gone
    assert await svc.doc_repo.find_by_id(current_doc.id) is None
    assert await svc.version_repo.find_by_id(current_v1.id) is None


@pytest.mark.asyncio
async def test_link_rejected_when_switch_off(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod
    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)

    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.link_file_to_document(knowledge_file_id=1, target_document_id=1)
    assert ctx.value.status_code == 403


@pytest.mark.asyncio
async def test_link_rejected_when_md5_duplicate_in_target_chain(enable_switch, async_db_session, monkeypatch):
    target_doc, _ = await _seed_doc(async_db_session, 1, 100, "target.pdf", md5="DUP")
    _, _ = await _seed_doc(async_db_session, 1, 101, "incoming.pdf", md5="DUP")
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.link_file_to_document(knowledge_file_id=101, target_document_id=target_doc.id)
    assert ctx.value.status_code == 409


@pytest.mark.asyncio
async def test_link_rejected_when_current_file_not_parsed(enable_switch, async_db_session, monkeypatch):
    target_doc, _ = await _seed_doc(async_db_session, 1, 100, "target.pdf", md5="aaa")
    # Seed an unparsed (status=1 WAITING) incoming file with its own doc
    _, _ = await _seed_doc(async_db_session, 1, 101, "incoming.pdf", md5="bbb", status=1)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.link_file_to_document(knowledge_file_id=101, target_document_id=target_doc.id)
    assert ctx.value.status_code == 412
