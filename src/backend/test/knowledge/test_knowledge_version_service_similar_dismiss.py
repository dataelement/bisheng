"""Tests for list_pending_similar_files + dismiss_similar."""
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
    conf.version_management.simhash_similarity_threshold = 0.85
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)


def _build_svc(session):
    return KnowledgeVersionService(
        request=MagicMock(), login_user=MagicMock(),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
    )


async def _seed_file_with_doc(
    session, fid, knowledge_id=1, similar_status=0, simhash=None, file_encoding=None
):
    session.add(KnowledgeFile(id=fid, knowledge_id=knowledge_id, file_name=f"f{fid}.pdf",
                              file_type=1, status=2, similar_status=similar_status,
                              simhash=simhash, file_encoding=file_encoding))
    await session.commit()
    doc = KnowledgeDocument(knowledge_id=knowledge_id)
    session.add(doc); await session.commit(); await session.refresh(doc)
    v = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=fid,
                                 version_no=1, is_primary=True)
    session.add(v); await session.commit()
    await session.refresh(v)
    doc.primary_version_id = v.id
    session.add(doc); await session.commit()
    return doc


@pytest.mark.asyncio
async def test_list_pending_returns_status_1_only(enable_switch, async_db_session, monkeypatch):
    """List excludes status=0 and status=2."""
    from unittest.mock import patch
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield async_db_session

    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session,
        100,
        similar_status=1,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )
    await _seed_file_with_doc(
        async_db_session,
        101,
        similar_status=0,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000002",
    )
    await _seed_file_with_doc(async_db_session, 200, similar_status=0)
    await _seed_file_with_doc(async_db_session, 300, similar_status=2)

    with patch("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
               side_effect=lambda: _ctx()):
        svc = _build_svc(async_db_session)
        results = await svc.list_pending_similar_files(knowledge_id=1)
        ids = {r.knowledge_file_id for r in results}
        assert ids == {100}


@pytest.mark.asyncio
async def test_list_pending_clears_stale_status_when_no_candidates(enable_switch, async_db_session, monkeypatch):
    from unittest.mock import patch
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield async_db_session

    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session,
        100,
        similar_status=1,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )

    with patch("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
               side_effect=lambda: _ctx()):
        svc = _build_svc(async_db_session)
        results = await svc.list_pending_similar_files(knowledge_id=1)

    assert results == []
    kf = await async_db_session.get(KnowledgeFile, 100)
    assert kf.similar_status == 0


@pytest.mark.asyncio
async def test_dismiss_sets_status_to_2(enable_switch, async_db_session, monkeypatch):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, similar_status=1)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_dismiss_similar_file",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.dismiss_similar(knowledge_file_id=100)
    assert result.similar_status == 2
    kf = await svc.knowledge_file_repo.find_by_id(100)
    assert kf.similar_status == 2


@pytest.mark.asyncio
async def test_dismiss_idempotent_when_already_2(enable_switch, async_db_session, monkeypatch):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, similar_status=2)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_dismiss_similar_file",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.dismiss_similar(knowledge_file_id=100)
    assert result.similar_status == 2


@pytest.mark.asyncio
async def test_dismiss_404_when_file_not_found(enable_switch, async_db_session):
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.dismiss_similar(knowledge_file_id=9999)
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_dismiss_403_when_switch_off(async_db_session, monkeypatch):
    from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod
    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)

    svc = _build_svc(async_db_session)
    with pytest.raises(VersionManagementDisabledError):
        await svc.dismiss_similar(knowledge_file_id=1)
