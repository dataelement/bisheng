"""F062 T017 — temp resolve is session-owned, never view_file, never anonymous."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    TempCitationItemSchema,
    TempCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService
from bisheng.common.errcode.http_error import NotFoundError

FORBIDDEN = "forbidden"
EXPIRED = "expired"
OBJECT_NAME = "chat/42/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
SIGNED_URL = "https://minio.example/signed/报价单.pdf"


def _temp_item(citation_id: str = "tempsearch_abcd1234") -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.TEMP,
        sourcePayload=TempCitationPayloadSchema(
            documentId="3f2a1c9e8b7d4f6a",
            documentName="报价单.pdf",
            objectName=OBJECT_NAME,
            items=[TempCitationItemSchema(itemId="0", content="chunk")],
        ),
    )


def _service(item: CitationRegistryItemSchema | None):
    repository = MagicMock()
    repository.find_by_citation_id = AsyncMock(return_value=SimpleNamespace(chat_id="chat-1") if item else None)
    service = CitationResolveService(repository, runtime_cache_service=MagicMock())
    service.runtime_cache_service.get_citation = AsyncMock(return_value=item)
    service.runtime_cache_service.get_citations_by_ids = AsyncMock(return_value=[item] if item else [])
    service.registry_service.get_citation = AsyncMock(return_value=item)
    service.registry_service.list_citations_by_ids = AsyncMock(return_value=[item] if item else [])
    return service


def _owner():
    return SimpleNamespace(user_id=42)


def _other():
    return SimpleNamespace(user_id=99)


def _reasons(result) -> dict[str, str]:
    return {entry.citationId: entry.reason for entry in result.unresolved}


def _minio(*, exists: bool = True, url: str = SIGNED_URL):
    client = MagicMock()
    client.object_exists = AsyncMock(return_value=exists)
    client.get_share_link = AsyncMock(return_value=url)
    return client


async def test_session_owner_gets_freshly_signed_url_without_knowledge_file():
    item = _temp_item()
    service = _service(item)
    minio = _minio()
    with (
        patch(
            "bisheng.database.models.session.MessageSessionDao.async_get_one",
            AsyncMock(return_value=SimpleNamespace(user_id=42, chat_id="chat-1")),
        ),
        patch(
            "bisheng.core.storage.minio.minio_manager.get_minio_storage",
            AsyncMock(return_value=minio),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.query_by_id_sync",
        ) as knowledge_file_mock,
        patch.object(service, "_permitted_file_ids", AsyncMock(return_value=set())) as permitted_mock,
    ):
        resolved = await service.resolve_citation(item.citationId, login_user=_owner())

    assert resolved.sourcePayload.previewUrl == SIGNED_URL
    assert resolved.sourcePayload.downloadUrl == SIGNED_URL
    assert resolved.sourcePayload.objectName == OBJECT_NAME
    knowledge_file_mock.assert_not_called()
    permitted_mock.assert_not_called()
    minio.object_exists.assert_awaited()


async def test_anonymous_caller_is_forbidden_including_share_page():
    item = _temp_item()
    service = _service(item)
    with pytest.raises(NotFoundError) as exc:
        await service.resolve_citation(item.citationId, login_user=None)
    assert exc.value.kwargs.get("reason") == FORBIDDEN

    result = await service.resolve_citations_with_reasons([item.citationId], login_user=None)
    assert result.items == []
    assert _reasons(result) == {item.citationId: FORBIDDEN}


async def test_logged_in_non_owner_is_forbidden():
    item = _temp_item()
    service = _service(item)
    with patch(
        "bisheng.database.models.session.MessageSessionDao.async_get_one",
        AsyncMock(return_value=SimpleNamespace(user_id=42, chat_id="chat-1")),
    ):
        with pytest.raises(NotFoundError) as exc:
            await service.resolve_citation(item.citationId, login_user=_other())
    assert exc.value.kwargs.get("reason") == FORBIDDEN


async def test_owner_sees_expired_when_object_is_gone():
    item = _temp_item()
    service = _service(item)
    with (
        patch(
            "bisheng.database.models.session.MessageSessionDao.async_get_one",
            AsyncMock(return_value=SimpleNamespace(user_id=42, chat_id="chat-1")),
        ),
        patch(
            "bisheng.core.storage.minio.minio_manager.get_minio_storage",
            AsyncMock(return_value=_minio(exists=False)),
        ),
    ):
        result = await service.resolve_citations_with_reasons([item.citationId], login_user=_owner())
    assert result.items == []
    assert _reasons(result) == {item.citationId: EXPIRED}


async def test_no_permission_and_missing_object_still_reports_forbidden():
    item = _temp_item()
    service = _service(item)
    minio = _minio(exists=False)
    with (
        patch(
            "bisheng.database.models.session.MessageSessionDao.async_get_one",
            AsyncMock(return_value=SimpleNamespace(user_id=42, chat_id="chat-1")),
        ),
        patch(
            "bisheng.core.storage.minio.minio_manager.get_minio_storage",
            AsyncMock(return_value=minio),
        ),
    ):
        result = await service.resolve_citations_with_reasons([item.citationId], login_user=_other())
    assert _reasons(result) == {item.citationId: FORBIDDEN}
    minio.object_exists.assert_not_awaited()


async def test_debug_item_without_object_name_signs_still_live_tmp_object():
    item = CitationRegistryItemSchema(
        citationId="tempsearch_abcd1234",
        type=CitationType.TEMP,
        sourcePayload=TempCitationPayloadSchema(
            documentId="3f2a1c9e8b7d4f6a",
            documentName="报价单.pdf",
            sourceUrl="http://192.168.106.116:9000/tmp-dir/abc.pdf",
            items=[TempCitationItemSchema(itemId="0", content="chunk")],
        ),
    )
    service = _service(item)
    service.registry_service.repository.find_by_citation_id = AsyncMock(return_value=None)
    minio = _minio()
    minio.tmp_bucket = "tmp-dir"
    with patch(
        "bisheng.core.storage.minio.minio_manager.get_minio_storage",
        AsyncMock(return_value=minio),
    ):
        resolved = await service.resolve_citation(item.citationId, login_user=_owner())

    assert resolved.sourcePayload.previewUrl == SIGNED_URL
    minio.object_exists.assert_awaited()
    minio.get_share_link.assert_awaited()
