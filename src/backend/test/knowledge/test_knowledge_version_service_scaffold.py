"""Scaffold tests for KnowledgeVersionService: construction, switch guard, DI."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_login_user():
    user = MagicMock()
    user.user_id = 1
    user.user_name = "tester"
    return user


@pytest.fixture
def mock_request():
    return MagicMock()


@pytest.fixture
def svc(mock_request, mock_login_user):
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    return KnowledgeVersionService(
        request=mock_request,
        login_user=mock_login_user,
        doc_repo=MagicMock(),
        version_repo=MagicMock(),
        knowledge_file_repo=MagicMock(),
    )


@pytest.mark.asyncio
async def test_require_enabled_raises_when_disabled(svc, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    mock_conf = MagicMock()
    mock_conf.version_management.enabled = False
    mock_settings.async_get_knowledge = AsyncMock(return_value=mock_conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)

    from bisheng.common.errcode.knowledge_space import VersionManagementDisabledError

    with pytest.raises(VersionManagementDisabledError) as ctx:
        await svc._require_version_management_enabled()
    assert ctx.value.code == 18060


@pytest.mark.asyncio
async def test_require_enabled_passes_when_enabled(svc, monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_version_service as kvs_mod

    mock_settings = MagicMock()
    mock_conf = MagicMock()
    mock_conf.version_management.enabled = True
    mock_settings.async_get_knowledge = AsyncMock(return_value=mock_conf)
    monkeypatch.setattr(kvs_mod, "bisheng_settings", mock_settings)

    await svc._require_version_management_enabled()  # should not raise


@pytest.mark.asyncio
async def test_dependency_factory(async_db_session):
    from bisheng.knowledge.api.dependencies import get_knowledge_version_service
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

    svc = await get_knowledge_version_service(
        request=MagicMock(),
        login_user=MagicMock(),
        doc_repo=KnowledgeDocumentRepositoryImpl(async_db_session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(async_db_session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(async_db_session),
        similar_candidate_repo=KnowledgeFileSimilarityCandidateRepositoryImpl(async_db_session),
    )
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    assert isinstance(svc, KnowledgeVersionService)
