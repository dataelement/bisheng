"""Recommendations expose only the same native, visible candidate as search."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services import knowledge_version_service as module
from test.knowledge_unification.test_kn_version_read import (
    catalog as catalog,
)
from test.knowledge_unification.test_kn_version_read import (
    chain,
    space,
)
from test.knowledge_unification.test_kn_version_read import (
    concrete_tenant as concrete_tenant,
)
from test.knowledge_unification.test_kn_version_read import (
    identity as identity,
)
from test.knowledge_unification.test_kn_version_read import (
    reads as reads,
)


@pytest.mark.parametrize("method", ["get_version_recommendations", "get_similar_candidates_for_file"])
async def test_native_recommendations_never_disclose_hidden_candidate_or_its_preview_id(reads, monkeypatch, method):
    await reads.catalog.seed([space(), *chain(1), *chain(2), *chain(3)])
    for ident in (10001, 20001, 30001):
        await reads.catalog.change(KnowledgeFile, ident, simhash="0")
    reads.facts.allowed.update({10001, 20001})
    monkeypatch.setattr(
        module,
        "bisheng_settings",
        SimpleNamespace(
            async_get_knowledge=AsyncMock(
                return_value=SimpleNamespace(
                    version_management=SimpleNamespace(enabled=True, simhash_similarity_threshold=0.85)
                )
            )
        ),
    )
    async with reads.catalog.sessions() as native:
        engine = native.bind
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = module.KnowledgeVersionService(
            reads.service.request,
            reads.user,
            None,
            KnowledgeDocumentVersionRepositoryImpl(session),
            KnowledgeFileRepositoryImpl(session),
            version_read_service=reads.service,
        )
        result = await getattr(service, method)(10001)
    assert [entry.target_document_id for entry in result] == [2]
    assert result[0].primary_knowledge_file_id == 20001
    assert "30001" not in str([entry.model_dump() for entry in result])
    assert reads.facts.checked


async def test_actual_recommendation_ranking_threshold_and_single_version_filter(reads):
    await reads.catalog.seed([space(), *chain(1), *chain(2), *chain(3, 2), *chain(4), *chain(5)])
    for ident, simhash in ((10001, "0"), (20001, "1"), (30002, "0"), (40001, "ffffffffffffffff"), (50001, "0")):
        await reads.catalog.change(KnowledgeFile, ident, simhash=simhash)
    reads.facts.allowed.update({10001, 20001, 30002, 40001, 50001})
    result = await reads.service.similar_candidates(10001, threshold=0.98, limit=2)
    assert [row.target_document_id for row in result] == [3, 5]
    assert [row.primary_knowledge_file_id for row in result] == [30002, 50001]
    singleton = await reads.service.similar_candidates(10001, threshold=0.98, limit=2, source_only=True)
    assert [row.target_document_id for row in singleton] == [5, 2]
    assert [row.similarity for row in singleton] == [1.0, 63 / 64]
