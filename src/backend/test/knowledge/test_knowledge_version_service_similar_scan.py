"""Tests for scan_similar_for_file and get_similar_candidates_for_file."""
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


async def _seed_file_with_doc(session, fid, knowledge_id=1, simhash=None, similar_status=0,
                               is_primary=True, file_encoding=None):
    session.add(KnowledgeFile(id=fid, knowledge_id=knowledge_id, file_name=f"f{fid}.pdf",
                              file_type=1, status=2, similar_status=similar_status,
                              simhash=simhash, file_encoding=file_encoding))
    await session.commit()
    doc = KnowledgeDocument(knowledge_id=knowledge_id)
    session.add(doc); await session.commit(); await session.refresh(doc)
    v = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=fid,
                                 version_no=1, is_primary=is_primary)
    session.add(v); await session.commit()
    if is_primary:
        await session.refresh(v)
        doc.primary_version_id = v.id
        session.add(doc); await session.commit()
    return doc


async def _seed_file_without_doc(session, fid, knowledge_id=1, file_name=None, file_encoding=None):
    session.add(KnowledgeFile(
        id=fid,
        knowledge_id=knowledge_id,
        file_name=file_name or f"f{fid}.pdf",
        file_type=1,
        status=2,
        file_encoding=file_encoding,
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_scan_marks_status_1_when_candidate_above_threshold(enable_switch, async_db_session):
    """Two files with identical simhash → candidate similarity = 1.0 > 0.85 → similar_status=1."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session, 100, simhash="aaaaaaaaaaaaaaaa", file_encoding="GF-ZD-SC-20260500000001"
    )
    await _seed_file_with_doc(
        async_db_session, 101, simhash="aaaaaaaaaaaaaaaa", file_encoding="GF-ZD-SC-20260500000002"
    )

    svc = _build_svc(async_db_session)
    n = await svc.scan_similar_for_file(knowledge_file_id=101)
    assert n >= 1
    kf = await svc.knowledge_file_repo.find_by_id(101)
    assert kf.similar_status == 1


@pytest.mark.asyncio
async def test_scan_leaves_status_0_when_no_candidate_above_threshold(enable_switch, async_db_session):
    """Completely different simhashes → similarity below threshold → similar_status stays 0."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session, 100, simhash="0000000000000000", file_encoding="GF-ZD-SC-20260500000001"
    )
    await _seed_file_with_doc(
        async_db_session, 101, simhash="ffffffffffffffff", file_encoding="GF-ZD-SC-20260500000002"
    )

    svc = _build_svc(async_db_session)
    n = await svc.scan_similar_for_file(knowledge_file_id=101)
    assert n == 0
    kf = await svc.knowledge_file_repo.find_by_id(101)
    assert kf.similar_status == 0


@pytest.mark.asyncio
async def test_get_similar_candidates_returns_top_n_sorted(enable_switch, async_db_session):
    """get_similar_candidates_for_file returns candidates sorted by similarity desc."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    # File 100 hash = aaaa...; candidates with hamming distances 0, 1, 8, 32 from "a" base
    await _seed_file_with_doc(
        async_db_session, 100, simhash="aaaaaaaaaaaaaaaa", file_encoding="GF-ZD-SC-20260500000001"
    )  # self
    await _seed_file_with_doc(
        async_db_session, 200, simhash="aaaaaaaaaaaaaaab", file_encoding="GF-ZD-SC-20260500000002"
    )  # hd=1, sim=0.984
    await _seed_file_with_doc(
        async_db_session, 201, simhash="aaaaaaaaaaaaaaaa", file_encoding="GF-ZD-SC-20260500000003"
    )  # hd=0, sim=1.0
    await _seed_file_with_doc(
        async_db_session, 202, simhash="ffffffffffffffff", file_encoding="GF-ZD-SC-20260500000004"
    )  # hd=64-something, very low

    svc = _build_svc(async_db_session)
    candidates = await svc.get_similar_candidates_for_file(knowledge_file_id=100, limit=3)
    # Should include 201 (perfect) and 200 (near), exclude 202 (below threshold)
    # Self (100) must be excluded
    self_v = await svc.version_repo.find_by_knowledge_file_id(100)
    self_doc_id = self_v.document_id
    assert all(c.target_document_id != self_doc_id for c in candidates)
    # Sorted by similarity desc
    sims = [c.similarity for c in candidates]
    assert sims == sorted(sims, reverse=True)


@pytest.mark.asyncio
async def test_get_similar_candidates_respects_limit(enable_switch, async_db_session):
    """limit caps the number of returned candidates."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    for fid in [100, 200, 201, 202, 203]:
        await _seed_file_with_doc(
            async_db_session, fid, simhash="aaaaaaaaaaaaaaaa", file_encoding=f"GF-ZD-SC-20260500000{fid}"
        )  # all identical

    svc = _build_svc(async_db_session)
    candidates = await svc.get_similar_candidates_for_file(knowledge_file_id=100, limit=3)
    assert len(candidates) <= 3


@pytest.mark.asyncio
async def test_scan_no_simhash_on_target_returns_zero(enable_switch, async_db_session):
    """If the file has no simhash, scan does nothing."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, simhash=None, file_encoding="GF-ZD-SC-20260500000001")

    svc = _build_svc(async_db_session)
    n = await svc.scan_similar_for_file(knowledge_file_id=100)
    assert n == 0


@pytest.mark.asyncio
async def test_zero_simhash_is_not_recommended(enable_switch, async_db_session):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session,
        100,
        simhash="0000000000000000",
        file_encoding="GF-ZD-SC-20260500000001",
    )
    await _seed_file_with_doc(
        async_db_session,
        101,
        simhash="0000000000000000",
        file_encoding="GF-ZD-SC-20260500000002",
    )

    svc = _build_svc(async_db_session)

    assert await svc.scan_similar_for_file(knowledge_file_id=101) == 0
    assert await svc.get_version_recommendations(current_file_id=101, limit=10) == []
    assert await svc.get_similar_candidates_for_file(knowledge_file_id=101, limit=10) == []


@pytest.mark.asyncio
async def test_shougang_publish_candidates_require_first_three_encoding_segments(enable_switch, async_db_session):
    async_db_session.add(Knowledge(id=1, name="source", type=3, user_id=1))
    async_db_session.add(Knowledge(id=2, name="target", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session,
        100,
        knowledge_id=1,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )
    matched_doc = await _seed_file_with_doc(
        async_db_session,
        200,
        knowledge_id=2,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000002",
    )
    await _seed_file_with_doc(
        async_db_session,
        201,
        knowledge_id=2,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-BG-SC-20260500000003",
    )

    svc = _build_svc(async_db_session)
    candidates = await svc.get_shougang_publish_similar_candidates_for_file_in_space(
        knowledge_file_id=100,
        target_knowledge_id=2,
        limit=10,
    )

    assert [one.target_document_id for one in candidates] == [matched_doc.id]


@pytest.mark.asyncio
async def test_shougang_publish_candidates_skip_files_without_encoding(enable_switch, async_db_session):
    async_db_session.add(Knowledge(id=1, name="source", type=3, user_id=1))
    async_db_session.add(Knowledge(id=2, name="target", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session,
        100,
        knowledge_id=1,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )
    await _seed_file_with_doc(
        async_db_session,
        200,
        knowledge_id=2,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding=None,
    )

    svc = _build_svc(async_db_session)
    candidates = await svc.get_shougang_publish_similar_candidates_for_file_in_space(
        knowledge_file_id=100,
        target_knowledge_id=2,
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_scan_requires_first_three_encoding_segments(enable_switch, async_db_session):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_with_doc(
        async_db_session,
        100,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )
    await _seed_file_with_doc(
        async_db_session,
        101,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-BG-SC-20260500000002",
    )

    svc = _build_svc(async_db_session)
    n = await svc.scan_similar_for_file(knowledge_file_id=101)

    assert n == 0
    kf = await svc.knowledge_file_repo.find_by_id(101)
    assert kf.similar_status == 0


@pytest.mark.asyncio
async def test_version_recommendations_require_first_three_encoding_segments(enable_switch, async_db_session):
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    matched_doc = await _seed_file_with_doc(
        async_db_session,
        200,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000002",
    )
    await _seed_file_with_doc(
        async_db_session,
        201,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-BG-SC-20260500000003",
    )
    await _seed_file_with_doc(
        async_db_session,
        100,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )

    svc = _build_svc(async_db_session)
    candidates = await svc.get_version_recommendations(current_file_id=100, limit=10)

    assert [one.target_document_id for one in candidates] == [matched_doc.id]


@pytest.mark.asyncio
async def test_merge_allows_document_regardless_of_similarity(enable_switch, async_db_session, monkeypatch):
    """Version linking is a deliberate, user-driven choice: the user manually picks
    the document to merge, so the merge must NOT be gated on content/encoding
    similarity. Here source (GF-BG) and current (GF-ZD) differ in business domain
    and the merge must still succeed."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1))
    await async_db_session.commit()
    source_doc = await _seed_file_with_doc(
        async_db_session,
        200,
        simhash="ffffffffffffffff",
        file_encoding="GF-BG-SC-20260500000002",
    )
    current_doc = await _seed_file_with_doc(
        async_db_session,
        100,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding="GF-ZD-SC-20260500000001",
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(return_value=None),
    )

    svc = _build_svc(async_db_session)

    result = await svc.merge_source_document_into_current(
        current_knowledge_file_id=100,
        source_document_id=source_doc.id,
    )

    assert result.document_id == current_doc.id
    assert result.new_version_no == 2
    # The current file's chain now has two versions, with the source file as the new primary.
    chain = await svc.version_repo.find_by_document_id(current_doc.id)
    assert len(chain) == 2
    primary = await svc.version_repo.find_primary(current_doc.id)
    assert primary.knowledge_file_id == 200


@pytest.mark.asyncio
async def test_shougang_publish_document_search_returns_target_files_without_version_document(
    enable_switch,
    async_db_session,
):
    async_db_session.add(Knowledge(id=1, name="source", type=3, user_id=1))
    async_db_session.add(Knowledge(id=2, name="target", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_without_doc(async_db_session, 100, knowledge_id=1, file_name="源文件.pdf")
    await _seed_file_without_doc(
        async_db_session,
        300,
        knowledge_id=2,
        file_name="桃新品种经济效益分析.pdf",
        file_encoding="SGGF-STD-PP-20260500000004",
    )

    svc = _build_svc(async_db_session)
    entries = await svc.search_shougang_publish_version_sources(
        knowledge_id=2,
        keyword="桃",
        current_file_id=100,
    )

    assert len(entries) == 1
    assert entries[0].document_id is None
    assert entries[0].target_file_id == 300
    assert entries[0].title == "桃新品种经济效益分析.pdf"


@pytest.mark.asyncio
async def test_ensure_shougang_publish_document_for_file_creates_v1_document_chain(
    enable_switch,
    async_db_session,
):
    async_db_session.add(Knowledge(id=2, name="target", type=3, user_id=1))
    await async_db_session.commit()
    await _seed_file_without_doc(
        async_db_session,
        300,
        knowledge_id=2,
        file_name="桃新品种经济效益分析.pdf",
    )

    svc = _build_svc(async_db_session)
    document_id = await svc.ensure_shougang_publish_document_for_file(300)
    second_document_id = await svc.ensure_shougang_publish_document_for_file(300)

    assert second_document_id == document_id
    doc = await svc.doc_repo.find_by_id(document_id)
    version = await svc.version_repo.find_by_knowledge_file_id(300)
    docs = await svc.doc_repo.find_by_knowledge_id(2)
    assert len(docs) == 1
    assert version.document_id == document_id
    assert version.version_no == 1
    assert version.is_primary is True
    assert doc.primary_version_id == version.id
