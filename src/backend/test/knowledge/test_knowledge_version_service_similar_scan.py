"""Tests for scan_similar_for_file and get_similar_candidates_for_file."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

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
                               is_primary=True):
    session.add(KnowledgeFile(id=fid, knowledge_id=knowledge_id, file_name=f"f{fid}.pdf",
                              file_type=1, status=2, similar_status=similar_status,
                              simhash=simhash))
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


@pytest.mark.asyncio
async def test_scan_marks_status_1_when_candidate_above_threshold(enable_switch, async_db_session):
    """Two files with identical simhash → candidate similarity = 1.0 > 0.85 → similar_status=1."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, simhash="aaaaaaaaaaaaaaaa")
    await _seed_file_with_doc(async_db_session, 101, simhash="aaaaaaaaaaaaaaaa")

    svc = _build_svc(async_db_session)
    n = await svc.scan_similar_for_file(knowledge_file_id=101)
    assert n >= 1
    kf = await svc.knowledge_file_repo.find_by_id(101)
    assert kf.similar_status == 1


@pytest.mark.asyncio
async def test_scan_leaves_status_0_when_no_candidate_above_threshold(enable_switch, async_db_session):
    """Completely different simhashes → similarity below threshold → similar_status stays 0."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, simhash="0000000000000000")
    await _seed_file_with_doc(async_db_session, 101, simhash="ffffffffffffffff")

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
    await _seed_file_with_doc(async_db_session, 100, simhash="aaaaaaaaaaaaaaaa")  # self
    await _seed_file_with_doc(async_db_session, 200, simhash="aaaaaaaaaaaaaaab")  # hd=1, sim=0.984
    await _seed_file_with_doc(async_db_session, 201, simhash="aaaaaaaaaaaaaaaa")  # hd=0, sim=1.0
    await _seed_file_with_doc(async_db_session, 202, simhash="ffffffffffffffff")  # hd=64-something, very low

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
        await _seed_file_with_doc(async_db_session, fid, simhash="aaaaaaaaaaaaaaaa")  # all identical

    svc = _build_svc(async_db_session)
    candidates = await svc.get_similar_candidates_for_file(knowledge_file_id=100, limit=3)
    assert len(candidates) <= 3


@pytest.mark.asyncio
async def test_scan_no_simhash_on_target_returns_zero(enable_switch, async_db_session):
    """If the file has no simhash, scan does nothing."""
    async_db_session.add(Knowledge(id=1, name="s1", type=3, user_id=1)); await async_db_session.commit()
    await _seed_file_with_doc(async_db_session, 100, simhash=None)

    svc = _build_svc(async_db_session)
    n = await svc.scan_similar_for_file(knowledge_file_id=100)
    assert n == 0
