"""set_primary: promote a non-primary version back to primary."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock, AsyncMock

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
)
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
from bisheng.knowledge.domain.schemas.knowledge_document_distribution_schema import (
    KnowledgeDocumentEntryCapabilities,
    ResolvedKnowledgeDocumentEntry,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    SwitchPrimaryManagerResult,
)


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
    )


@pytest.mark.asyncio
async def test_set_primary_demotes_old_and_points_doc(enable_switch, async_db_session, monkeypatch):
    doc, v1, v2 = await _seed_two_version_doc(async_db_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_set_primary_version",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.set_primary_version(version_id=v1.id)
    assert result.new_primary_version_no == 1

    versions = await svc.version_repo.find_by_document_id(doc.id)
    by_no = {v.version_no: v for v in versions}
    assert by_no[1].is_primary is True
    assert by_no[2].is_primary is False
    fresh_doc = await svc.doc_repo.find_by_id(doc.id)
    assert fresh_doc.primary_version_id == v1.id


@pytest.mark.asyncio
async def test_set_primary_rejects_failed_parse_target(enable_switch, async_db_session, monkeypatch):
    doc, v1, v2 = await _seed_two_version_doc(async_db_session)
    # Mark v1's underlying file as failed (status=3)
    file_repo = KnowledgeFileRepositoryImpl(async_db_session)
    kf = await file_repo.find_by_id(100)
    kf.status = 3
    await file_repo.update(kf)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_set_primary_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.set_primary_version(version_id=v1.id)
    assert ctx.value.status_code == 412


@pytest.mark.asyncio
async def test_set_primary_no_op_when_already_primary(enable_switch, async_db_session, monkeypatch):
    doc, v1, v2 = await _seed_two_version_doc(async_db_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_set_primary_version",
        MagicMock(return_value=None),
    )
    svc = _build_svc(async_db_session)
    result = await svc.set_primary_version(version_id=v2.id)
    assert result.new_primary_version_no == 2
    fresh = await svc.version_repo.find_by_document_id(doc.id)
    by_no = {v.version_no: v for v in fresh}
    assert by_no[2].is_primary is True
    assert by_no[1].is_primary is False


@pytest.mark.asyncio
async def test_set_primary_delegates_distributed_manager_switch(
    enable_switch,
    monkeypatch,
):
    document = KnowledgeDocument(
        id=91,
        tenant_id=7,
        knowledge_id=1,
        primary_version_id=502,
    )
    target_version = KnowledgeDocumentVersion(
        id=501,
        document_id=91,
        knowledge_file_id=100,
        version_no=1,
        is_primary=False,
    )
    current_version = KnowledgeDocumentVersion(
        id=502,
        document_id=91,
        knowledge_file_id=101,
        version_no=2,
        is_primary=True,
    )
    target_file = KnowledgeFile(
        id=100,
        tenant_id=7,
        knowledge_id=1,
        file_name="v1.pdf",
        file_type=1,
        status=2,
    )
    manager = KnowledgeFile(
        id=101,
        tenant_id=7,
        knowledge_id=1,
        file_name="v2.pdf",
        file_type=1,
        status=2,
        reference_document_id=91,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )
    doc_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=document))
    version_repo = SimpleNamespace(
        find_by_id=AsyncMock(
            side_effect=lambda version_id: {
                501: target_version,
                502: current_version,
            }.get(version_id)
        )
    )
    file_repo = SimpleNamespace(
        find_by_id=AsyncMock(
            side_effect=lambda file_id: {
                100: target_file,
                101: manager,
            }.get(file_id)
        )
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_set_primary_version",
        MagicMock(return_value=None),
    )
    service = KnowledgeVersionService(
        request=MagicMock(),
        login_user=SimpleNamespace(
            tenant_id=7,
            user_id=11,
            user_name="tester",
        ),
        doc_repo=doc_repo,
        version_repo=version_repo,
        knowledge_file_repo=file_repo,
    )
    service.document_entry_resolver = SimpleNamespace(
        resolve=AsyncMock(
            return_value=ResolvedKnowledgeDocumentEntry(
                tenant_id=7,
                requested_space_id=1,
                entry_file_id=101,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
                canonical_document_id=91,
                canonical_version_id=502,
                content_file_id=101,
                manager_file_id=101,
                manager_space_id=1,
                capabilities=KnowledgeDocumentEntryCapabilities(
                    can_edit_content=True,
                ),
            )
        )
    )
    service.document_distribution_service = SimpleNamespace(
        switch_primary_manager=AsyncMock(
            return_value=SwitchPrimaryManagerResult(
                document_id=91,
                manager_file_id=100,
                previous_manager_file_id=101,
                primary_version_id=501,
                content_generation=1,
            )
        )
    )
    service._enqueue_document_distribution_projection = AsyncMock()

    result = await service.set_primary_version(version_id=501)

    assert result.new_primary_version_no == 1
    (
        service.document_distribution_service.switch_primary_manager
        .assert_awaited_once_with(
            tenant_id=7,
            document_id=91,
            current_manager_file_id=101,
            target_version_id=501,
        )
    )
    service._enqueue_document_distribution_projection.assert_awaited_once_with(
        tenant_id=7,
        entry_ids=None,
    )


@pytest.mark.asyncio
async def test_set_primary_rejected_when_switch_off(async_db_session, monkeypatch):
    from bisheng.common.errcode.knowledge_space import (
        VersionManagementDisabledError,
    )
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)
    svc = _build_svc(async_db_session)
    with pytest.raises(VersionManagementDisabledError) as ctx:
        await svc.set_primary_version(version_id=1)
    assert ctx.value.code == 18060


@pytest.mark.asyncio
async def test_set_primary_404_when_version_not_found(enable_switch, async_db_session):
    svc = _build_svc(async_db_session)
    with pytest.raises(HTTPException) as ctx:
        await svc.set_primary_version(version_id=9999)
    assert ctx.value.status_code == 404
