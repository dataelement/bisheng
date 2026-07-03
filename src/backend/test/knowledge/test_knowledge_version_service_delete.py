"""delete_version: remove a historical (non-primary) version."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import KnowledgeFileSimilarityCandidate
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_similarity_candidate_repository_impl import (
    KnowledgeFileSimilarityCandidateRepositoryImpl,
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


async def _seed_two_version_doc(session):
    session.add(Knowledge(id=1, name="space1", type=3, user_id=1))
    session.add(KnowledgeFile(id=100, knowledge_id=1, file_name="v1.pdf", file_type=1, status=2))
    session.add(KnowledgeFile(id=101, knowledge_id=1, file_name="v2.pdf", file_type=1, status=2))
    await session.commit()
    doc = KnowledgeDocument(knowledge_id=1)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    v1 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=1, is_primary=False)
    v2 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=2, is_primary=True)
    session.add_all([v1, v2])
    await session.commit()
    await session.refresh(v1)
    await session.refresh(v2)
    doc.primary_version_id = v2.id
    session.add(doc)
    await session.commit()
    return doc, v1, v2


def _build_svc(session):
    return KnowledgeVersionService(
        request=MagicMock(), login_user=MagicMock(),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        similar_candidate_repo=KnowledgeFileSimilarityCandidateRepositoryImpl(session),
    )


@pytest.mark.asyncio
async def test_delete_history_removes_version_and_file(enable_switch, async_db_session, monkeypatch):
    doc, v1, v2 = await _seed_two_version_doc(async_db_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    # KnowledgeDao.aquery_by_id opens its own DB session; patch it to avoid
    # real connection setup in the unit test environment.
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=MagicMock(id=1)),
    )
    # delete_vector_files and delete_minio_files perform real I/O; stub them out.
    monkeypatch.setattr(
        "bisheng.api.services.knowledge_imp.delete_vector_files",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "bisheng.api.services.knowledge_imp.delete_minio_files",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.delete_version(version_id=v1.id)
    assert result.deleted_version_no == 1
    assert result.document_id == doc.id

    # Version row gone
    assert await svc.version_repo.find_by_id(v1.id) is None
    # Underlying knowledgefile gone
    assert await svc.knowledge_file_repo.find_by_id(100) is None
    # Primary still intact
    fresh_doc = await svc.doc_repo.find_by_id(doc.id)
    assert fresh_doc.primary_version_id == v2.id


@pytest.mark.asyncio
async def test_delete_history_removes_similarity_candidate_cache(enable_switch, async_db_session, monkeypatch):
    doc, v1, _ = await _seed_two_version_doc(async_db_session)
    async_db_session.add(
        KnowledgeFileSimilarityCandidate(
            tenant_id=1,
            knowledge_id=1,
            source_file_id=101,
            candidate_file_id=100,
            candidate_document_id=doc.id,
            similarity=0.9,
            sort_order=0,
        )
    )
    await async_db_session.commit()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=MagicMock(id=1)),
    )
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_vector_files", MagicMock(return_value=True))
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_minio_files", MagicMock(return_value=None))

    svc = _build_svc(async_db_session)
    await svc.delete_version(version_id=v1.id)

    cached = await svc.similar_candidate_repo.find_by_source_file_id(101)
    assert cached == []


@pytest.mark.asyncio
async def test_delete_primary_is_rejected(enable_switch, async_db_session, monkeypatch):
    _, _, v2 = await _seed_two_version_doc(async_db_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.delete_version(version_id=v2.id)
    assert ctx.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_404_when_version_not_found(enable_switch, async_db_session):
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.delete_version(version_id=9999)
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_rejected_when_switch_off(async_db_session, monkeypatch):
    from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)
    svc = _build_svc(async_db_session)
    with pytest.raises(VersionManagementDisabledError) as ctx:
        await svc.delete_version(version_id=1)
    assert ctx.value.code == 18060


# ---------------------------------------------------------------------------
# Cleanup (Milvus/ES/MinIO) behaviour tests — use pure mocks (no real DB)
# ---------------------------------------------------------------------------

def _build_mock_svc():
    """Build a KnowledgeVersionService whose repos are all MagicMock/AsyncMock."""
    return KnowledgeVersionService(
        request=MagicMock(),
        login_user=MagicMock(),
        doc_repo=MagicMock(),
        version_repo=MagicMock(),
        knowledge_file_repo=MagicMock(),
    )


def _patch_switch_enabled(monkeypatch):
    """Monkeypatch settings so the feature switch is enabled."""
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod
    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = True
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)


@pytest.mark.asyncio
async def test_delete_version_calls_vector_and_minio_cleanup(monkeypatch):
    """Happy path: both delete_vector_files and delete_minio_files are called once."""
    _patch_switch_enabled(monkeypatch)

    # Build mock service
    svc = _build_mock_svc()

    # Fake version and knowledge file
    fake_kf = KnowledgeFile(id=10, knowledge_id=5, file_name="report.pdf", file_type=1, status=2)
    fake_version = MagicMock()
    fake_version.id = 42
    fake_version.is_primary = False
    fake_version.knowledge_file_id = 10
    fake_version.document_id = 7
    fake_version.version_no = 2

    # Fake knowledge (the space)
    fake_knowledge = MagicMock()
    fake_knowledge.id = 5

    svc.version_repo.find_by_id = AsyncMock(return_value=fake_version)
    svc.knowledge_file_repo.find_by_id = AsyncMock(return_value=fake_kf)
    svc.version_repo.delete = AsyncMock(return_value=None)
    svc.knowledge_file_repo.delete = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    # Patch KnowledgeDao at its definition so the deferred import picks up the mock.
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=fake_knowledge),
    )
    # Patch at source module; deferred `from ... import` binds the name at call time.
    mock_dvf = MagicMock(return_value=True)
    mock_dmf = MagicMock(return_value=None)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_vector_files", mock_dvf)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_minio_files", mock_dmf)

    result = await svc.delete_version(version_id=42)

    # DB rows deleted
    svc.version_repo.delete.assert_awaited_once_with(42)
    svc.knowledge_file_repo.delete.assert_awaited_once_with(10)

    # Cleanup functions invoked once each
    mock_dvf.assert_called_once_with([fake_kf.id], fake_knowledge)
    mock_dmf.assert_called_once_with(fake_kf)

    assert result.deleted_version_no == 2
    assert result.document_id == 7


@pytest.mark.asyncio
async def test_delete_version_vector_failure_still_succeeds_and_calls_minio(monkeypatch):
    """delete_vector_files raises → delete_version still returns success and minio cleanup runs."""
    _patch_switch_enabled(monkeypatch)

    svc = _build_mock_svc()

    fake_kf = KnowledgeFile(id=11, knowledge_id=5, file_name="doc.pdf", file_type=1, status=2)
    fake_version = MagicMock()
    fake_version.id = 43
    fake_version.is_primary = False
    fake_version.knowledge_file_id = 11
    fake_version.document_id = 8
    fake_version.version_no = 3

    fake_knowledge = MagicMock()
    fake_knowledge.id = 5

    svc.version_repo.find_by_id = AsyncMock(return_value=fake_version)
    svc.knowledge_file_repo.find_by_id = AsyncMock(return_value=fake_kf)
    svc.version_repo.delete = AsyncMock(return_value=None)
    svc.knowledge_file_repo.delete = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=fake_knowledge),
    )
    mock_dvf = MagicMock(side_effect=RuntimeError("Milvus unreachable"))
    mock_dmf = MagicMock(return_value=None)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_vector_files", mock_dvf)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_minio_files", mock_dmf)

    # Must not raise despite vector cleanup failure
    result = await svc.delete_version(version_id=43)

    assert result.deleted_version_no == 3
    mock_dvf.assert_called_once()
    # MinIO cleanup still attempted after vector failure
    mock_dmf.assert_called_once_with(fake_kf)


@pytest.mark.asyncio
async def test_delete_version_minio_failure_still_succeeds(monkeypatch):
    """delete_minio_files raises → delete_version still returns success."""
    _patch_switch_enabled(monkeypatch)

    svc = _build_mock_svc()

    fake_kf = KnowledgeFile(id=12, knowledge_id=5, file_name="img.pdf", file_type=1, status=2)
    fake_version = MagicMock()
    fake_version.id = 44
    fake_version.is_primary = False
    fake_version.knowledge_file_id = 12
    fake_version.document_id = 9
    fake_version.version_no = 4

    fake_knowledge = MagicMock()
    fake_knowledge.id = 5

    svc.version_repo.find_by_id = AsyncMock(return_value=fake_version)
    svc.knowledge_file_repo.find_by_id = AsyncMock(return_value=fake_kf)
    svc.version_repo.delete = AsyncMock(return_value=None)
    svc.knowledge_file_repo.delete = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=fake_knowledge),
    )
    mock_dvf = MagicMock(return_value=True)
    mock_dmf = MagicMock(side_effect=OSError("MinIO connection refused"))
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_vector_files", mock_dvf)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_minio_files", mock_dmf)

    # Must not raise despite MinIO cleanup failure
    result = await svc.delete_version(version_id=44)

    assert result.deleted_version_no == 4
    mock_dvf.assert_called_once()
    mock_dmf.assert_called_once()


@pytest.mark.asyncio
async def test_delete_version_knowledge_none_skips_vector_but_runs_minio(monkeypatch):
    """When KnowledgeDao returns None (orphan kf), vector cleanup is skipped; MinIO still runs."""
    _patch_switch_enabled(monkeypatch)

    svc = _build_mock_svc()

    fake_kf = KnowledgeFile(id=13, knowledge_id=99, file_name="orphan.pdf", file_type=1, status=2)
    fake_version = MagicMock()
    fake_version.id = 45
    fake_version.is_primary = False
    fake_version.knowledge_file_id = 13
    fake_version.document_id = 10
    fake_version.version_no = 5

    svc.version_repo.find_by_id = AsyncMock(return_value=fake_version)
    svc.knowledge_file_repo.find_by_id = AsyncMock(return_value=fake_kf)
    svc.version_repo.delete = AsyncMock(return_value=None)
    svc.knowledge_file_repo.delete = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_delete_file_version",
        MagicMock(return_value=None),
    )
    # Knowledge lookup returns None — orphaned file
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=None),
    )
    mock_dvf = MagicMock(return_value=True)
    mock_dmf = MagicMock(return_value=None)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_vector_files", mock_dvf)
    monkeypatch.setattr("bisheng.api.services.knowledge_imp.delete_minio_files", mock_dmf)

    result = await svc.delete_version(version_id=45)

    assert result.deleted_version_no == 5
    # Vector cleanup skipped because knowledge is None
    mock_dvf.assert_not_called()
    # MinIO cleanup still attempted
    mock_dmf.assert_called_once_with(fake_kf)
