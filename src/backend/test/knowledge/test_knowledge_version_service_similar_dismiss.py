"""Tests for list_pending_similar_files + dismiss_similar."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError
from bisheng.common.errcode.permission import PermissionDeniedError
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
from test.knowledge.test_knowledge_version_service_similar_scan import (  # noqa: F401
    native_reads as _native_reads_fixture,
)


@pytest.fixture
def native_reads(request):
    return request.getfixturevalue("_native_reads_fixture")


@pytest.fixture
def enable_switch(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = True
    conf.version_management.simhash_similarity_threshold = 0.85
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)
    authorization = AsyncMock()
    monkeypatch.setattr(kvs_mod, "require_business_action", authorization)
    return authorization


def _build_svc(session, reads=None):
    return KnowledgeVersionService(
        request=MagicMock(),
        login_user=UserPayload(user_id=42, tenant_id=1, user_role=[]),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        version_read_service=reads,
    )


async def _seed_file_with_doc(session, fid, knowledge_id=1, similar_status=0, simhash=None):
    session.add(
        KnowledgeFile(
            id=fid,
            knowledge_id=knowledge_id,
            file_name=f"f{fid}.pdf",
            file_type=1,
            status=2,
            similar_status=similar_status,
            simhash=simhash,
        )
    )
    await session.commit()
    doc = KnowledgeDocument(knowledge_id=knowledge_id)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    v = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=fid, version_no=1, is_primary=True)
    session.add(v)
    await session.commit()
    await session.refresh(v)
    doc.primary_version_id = v.id
    session.add(doc)
    await session.commit()
    return doc


@pytest.mark.asyncio
async def test_list_pending_returns_status_1_only(
    enable_switch,
    async_db_session,
    monkeypatch,
    native_reads,
):
    """List excludes status=0 and status=2."""
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    @asynccontextmanager
    async def _ctx():
        yield async_db_session

    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, similar_status=1, simhash="aaaaaaaaaaaaaaaa")
    await _seed_file_with_doc(async_db_session, 200, similar_status=0)
    await _seed_file_with_doc(async_db_session, 300, similar_status=2)

    with patch("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session", side_effect=lambda: _ctx()):
        svc = _build_svc(async_db_session, native_reads)
        results = await svc.list_pending_similar_files(knowledge_id=1)
        ids = {r.knowledge_file_id for r in results}
        assert ids == {100}


@pytest.mark.asyncio
async def test_list_pending_scans_space_once_and_caps_counts(
    enable_switch, async_db_session, native_reads, monkeypatch
):
    """Several pending files share one candidate read, and the count matches the single-file top 3."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    for fid in (100, 200, 201, 203):
        await _seed_file_with_doc(async_db_session, fid, similar_status=1, simhash="aaaaaaaaaaaaaaaa")
    await _seed_file_with_doc(async_db_session, 202, similar_status=1, simhash="ffffffffffffffff")
    shared = await _seed_file_with_doc(async_db_session, 300, similar_status=1, simhash="aaaaaaaaaaaaaaaa")
    async_db_session.add(
        KnowledgeFile(
            id=301,
            knowledge_id=1,
            file_name="f301.pdf",
            file_type=1,
            status=2,
            similar_status=1,
            simhash="aaaaaaaaaaaaaaaa",
        )
    )
    await async_db_session.commit()
    async_db_session.add(
        KnowledgeDocumentVersion(document_id=shared.id, knowledge_file_id=301, version_no=2, is_primary=False)
    )
    await async_db_session.commit()

    calls = {"n": 0}
    original = native_reads.repository.alist_candidates

    async def counting(**kwargs):
        calls["n"] += 1
        return await original(**kwargs)

    monkeypatch.setattr(native_reads.repository, "alist_candidates", counting)
    svc = _build_svc(async_db_session, native_reads)
    results = await svc.list_pending_similar_files(knowledge_id=1)

    assert calls["n"] == 1
    by_id = {row.knowledge_file_id: row.candidate_count for row in results}
    assert set(by_id) == {100, 200, 201, 202, 203}
    assert by_id[100] == 3
    assert by_id[202] == 0
    for entry in results:
        single = await svc.get_similar_candidates_for_file(entry.knowledge_file_id)
        assert entry.candidate_count == len(single)


@pytest.mark.asyncio
async def test_list_pending_rejects_when_one_file_is_invisible(
    enable_switch, async_db_session, native_reads, monkeypatch
):
    from bisheng.permission.application import business_authorization

    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, similar_status=1, simhash="aaaaaaaaaaaaaaaa")
    await _seed_file_with_doc(async_db_session, 200, similar_status=1, simhash="aaaaaaaaaaaaaaaa")

    async def deny_one(_actor, targets, action):
        assert action == "visible"
        return tuple(target.resource_id != "100" for target in targets)

    monkeypatch.setattr(
        business_authorization,
        "get_f048_runtime",
        AsyncMock(return_value=MagicMock(batch_check_actions=AsyncMock(side_effect=deny_one))),
    )
    svc = _build_svc(async_db_session, native_reads)
    with pytest.raises(PermissionDeniedError):
        await svc.list_pending_similar_files(knowledge_id=1)


@pytest.mark.asyncio
async def test_dismiss_sets_status_to_2(enable_switch, async_db_session, monkeypatch):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, similar_status=1)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_dismiss_similar_file",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)
    result = await svc.dismiss_similar(knowledge_file_id=100)
    assert result.similar_status == 2
    enable_switch.assert_awaited_once_with(
        svc.login_user, resource_type="knowledge_file", resource_id=100, action="edit"
    )
    kf = await svc.knowledge_file_repo.find_by_id(100)
    assert kf.similar_status == 2


@pytest.mark.asyncio
async def test_dismiss_idempotent_when_already_2(enable_switch, async_db_session, monkeypatch):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
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
async def test_dismiss_returns_business_error_when_switch_off(async_db_session, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    conf = MagicMock()
    conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)

    svc = _build_svc(async_db_session)
    with pytest.raises(VersionManagementDisabledError) as ctx:
        await svc.dismiss_similar(knowledge_file_id=1)
    assert ctx.value.Code == 18060


@pytest.mark.parametrize("similar_status", [1, 2])
async def test_dismiss_denied_without_file_edit_before_write_or_audit(
    enable_switch, async_db_session, monkeypatch, similar_status
):
    async_db_session.add(Knowledge(id=7, name="s7", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, knowledge_id=7, similar_status=similar_status)
    enable_switch.side_effect = PermissionDeniedError()
    audit = MagicMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_dismiss_similar_file",
        audit,
    )
    svc = _build_svc(async_db_session)
    update = AsyncMock(wraps=svc.knowledge_file_repo.update)
    monkeypatch.setattr(svc.knowledge_file_repo, "update", update)

    with pytest.raises(PermissionDeniedError):
        await svc.dismiss_similar(100)

    enable_switch.assert_awaited_once_with(
        svc.login_user, resource_type="knowledge_file", resource_id=100, action="edit"
    )
    update.assert_not_awaited()
    audit.assert_not_called()
    assert (await svc.knowledge_file_repo.find_by_id(100)).similar_status == similar_status
