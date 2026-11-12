"""Link operation: associate a file into a target doc; auto-promote to primary."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    VersionLinkFileNotReadyError,
    VersionLinkSourceMultiVersionError,
    VersionManagementDisabledError,
)
from bisheng.knowledge.application.knowledge_version_mutation import KnowledgeVersionMutationApplication
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


@pytest.fixture(autouse=True)
def concrete_tenant(tenant_context):
    tenant_context(1)


@pytest.fixture
def enable_switch(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = True
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)


def _build_svc(session):
    service = KnowledgeVersionService(
        request=MagicMock(),
        login_user=UserPayload(user_id=1, tenant_id=1, user_role=[]),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
    )

    @asynccontextmanager
    async def fresh():
        assert not session.new and not session.dirty and not session.deleted
        async with AsyncSession(bind=session.bind, expire_on_commit=False) as owned:
            try:
                yield owned
            finally:
                # These older tests keep the seed Session for read assertions.
                # Real requests read afresh after the independent mutation TX.
                # Detach, without expiring or dropping any pending caller work.
                session.expunge_all()

    service.version_mutation_application = KnowledgeVersionMutationApplication(
        session_factory=fresh,
        require_version_management_enabled=service._require_version_management_enabled,
    )
    return service


async def _seed_doc(session, knowledge_id, file_id, file_name="a.pdf", md5=None, status=2):
    # idempotent space seed (the first call creates, later seeds reuse)
    from sqlmodel import select

    existing = await session.execute(select(Knowledge).where(Knowledge.id == knowledge_id))
    if existing.scalars().first() is None:
        session.add(Knowledge(id=knowledge_id, name=f"space{knowledge_id}", type=3, user_id=1))
        await session.commit()

    session.add(
        KnowledgeFile(id=file_id, knowledge_id=knowledge_id, file_name=file_name, file_type=1, status=status, md5=md5)
    )
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
    target_doc, _target_v1 = await _seed_doc(async_db_session, 1, 100, "target.pdf", md5="aaa")
    current_doc, current_v1 = await _seed_doc(async_db_session, 1, 101, "incoming.pdf", md5="bbb")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.link_file_to_document(
        knowledge_file_id=101,
        target_document_id=target_doc.id,
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
    with pytest.raises(VersionManagementDisabledError):
        await svc.link_file_to_document(knowledge_file_id=1, target_document_id=1)


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
    with pytest.raises(VersionLinkFileNotReadyError):
        await svc.link_file_to_document(knowledge_file_id=101, target_document_id=target_doc.id)


@pytest.mark.asyncio
async def test_link_rejected_when_source_is_primary_of_multi_version_doc(enable_switch, async_db_session, monkeypatch):
    """Source file is the primary of a doc that already has >=2 versions.

    Moving it would orphan the source doc, so the link must be rejected with 409.
    """
    target_doc, _ = await _seed_doc(async_db_session, 1, 100, "target.pdf", md5="aaa")
    # Source doc with V1 (historical) + V2 (primary, current source) — V2 is the file to link
    source_doc, _ = await _seed_doc(async_db_session, 1, 200, "v1.pdf", md5="bbb")
    # Demote V1 and add V2 as the new primary
    chain = await KnowledgeDocumentVersionRepositoryImpl(async_db_session).find_by_document_id(source_doc.id)
    chain[0].is_primary = False
    async_db_session.add(chain[0])
    async_db_session.add(KnowledgeFile(id=201, knowledge_id=1, file_name="v2.pdf", file_type=1, status=2, md5="ccc"))
    await async_db_session.commit()
    v2 = KnowledgeDocumentVersion(document_id=source_doc.id, knowledge_file_id=201, version_no=2, is_primary=True)
    async_db_session.add(v2)
    await async_db_session.commit()
    await async_db_session.refresh(v2)
    source_doc.primary_version_id = v2.id
    async_db_session.add(source_doc)
    await async_db_session.commit()

    svc = _build_svc(async_db_session)
    with pytest.raises(VersionLinkSourceMultiVersionError):
        await svc.link_file_to_document(knowledge_file_id=201, target_document_id=target_doc.id)


@pytest.mark.asyncio
async def test_link_rejected_when_source_is_historical_version_of_multi_version_doc(
    enable_switch, async_db_session, monkeypatch
):
    """The existing rule protects the entire multi-version source chain."""
    target_doc, _ = await _seed_doc(async_db_session, 1, 100, "target.pdf", md5="aaa")
    # Source doc with V1 (will become historical) + V2 (primary)
    source_doc, _ = await _seed_doc(async_db_session, 1, 300, "v1.pdf", md5="ddd")
    chain = await KnowledgeDocumentVersionRepositoryImpl(async_db_session).find_by_document_id(source_doc.id)
    chain[0].is_primary = False  # demote V1
    async_db_session.add(chain[0])
    async_db_session.add(KnowledgeFile(id=301, knowledge_id=1, file_name="v2.pdf", file_type=1, status=2, md5="eee"))
    await async_db_session.commit()
    v2 = KnowledgeDocumentVersion(document_id=source_doc.id, knowledge_file_id=301, version_no=2, is_primary=True)
    async_db_session.add(v2)
    await async_db_session.commit()
    await async_db_session.refresh(v2)
    source_doc.primary_version_id = v2.id
    async_db_session.add(source_doc)
    await async_db_session.commit()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    before = [
        (row.id, row.knowledge_file_id, row.is_primary)
        for row in await svc.version_repo.find_by_document_id(source_doc.id)
    ]
    with pytest.raises(VersionLinkSourceMultiVersionError):
        await svc.link_file_to_document(knowledge_file_id=300, target_document_id=target_doc.id)
    surviving = await svc.version_repo.find_by_document_id(source_doc.id)
    assert [(row.id, row.knowledge_file_id, row.is_primary) for row in surviving] == before
    target = await svc.version_repo.find_by_document_id(target_doc.id)
    assert len(target) == 1 and target[0].knowledge_file_id == 100 and target[0].is_primary
