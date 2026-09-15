"""F062 T016 — cited temp files get a main-bucket objectName; uncited stay temp."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
    TempCitationItemSchema,
    TempCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_prompt_helper import attach_temp_object_names
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService

OBJECT_NAME = "chat/42/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"


def _temp_item(
    citation_id: str = "tempsearch_abcd1234",
    name: str = "报价单.pdf",
    source_url: str = "https://minio.example/tmp/报价单.pdf",
    object_name: str | None = None,
) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.TEMP,
        sourcePayload=TempCitationPayloadSchema(
            documentId="3f2a1c9e8b7d4f6a",
            documentName=name,
            sourceUrl=source_url,
            objectName=object_name,
            items=[TempCitationItemSchema(itemId="0", content="chunk")],
        ),
    )


def _rag_item() -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId="knowledgesearch_1111aaaa",
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=1,
            documentId=7,
            documentName="政策.pdf",
            items=[RagCitationItemSchema(itemId="0", content="chunk")],
        ),
    )


def test_cited_temp_item_reuses_promoted_object_name_and_refreshes_cache():
    item = _temp_item()
    files = [
        {
            "filename": "报价单.pdf",
            "file_url": "https://minio.example/tmp/报价单.pdf",
            "object_name": OBJECT_NAME,
        }
    ]
    cached: list = []

    def _save(items):
        cached.extend(items)
        return items

    with (
        patch(
            "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
            side_effect=_save,
        ) as cache_mock,
        patch(
            "bisheng.core.storage.chat_attachment.promote_chat_attachments_sync",
        ) as promote_mock,
    ):
        result = attach_temp_object_names([item], files, user_id=42)

    assert len(result) == 1
    payload = result[0].sourcePayload
    assert payload.objectName == OBJECT_NAME
    assert payload.objectName.startswith("chat/")
    assert "workflow_temp/" not in payload.objectName
    assert payload.previewUrl is None
    assert payload.downloadUrl is None
    promote_mock.assert_not_called()
    cache_mock.assert_called_once()
    assert cached[0].sourcePayload.objectName == OBJECT_NAME


def test_uncited_files_are_not_promoted():
    cited = _temp_item(name="报价单.pdf")
    files = [
        {"filename": "报价单.pdf", "file_url": "https://minio.example/tmp/a.pdf", "object_name": OBJECT_NAME},
        {"filename": "未引用.docx", "file_url": "https://minio.example/tmp/b.docx"},
    ]
    with patch(
        "bisheng.core.storage.chat_attachment.promote_chat_attachments_sync",
        return_value=files,
    ) as promote_mock:
        with patch(
            "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
            side_effect=lambda items: items,
        ):
            attach_temp_object_names([cited], files, user_id=42)
    promote_mock.assert_not_called()


def test_missing_object_name_promotes_only_the_matched_file():
    item = _temp_item()
    matched = {"filename": "报价单.pdf", "file_url": "https://minio.example/tmp/报价单.pdf"}
    other = {"filename": "未引用.docx", "file_url": "https://minio.example/tmp/b.docx"}

    def _promote(files, user_id):
        assert files == [matched]
        assert user_id == 42
        promoted = dict(files[0])
        promoted["object_name"] = OBJECT_NAME
        return [promoted]

    with (
        patch(
            "bisheng.core.storage.chat_attachment.promote_chat_attachments_sync",
            side_effect=_promote,
        ) as promote_mock,
        patch(
            "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
            side_effect=lambda items: items,
        ),
    ):
        result = attach_temp_object_names([item], [matched, other], user_id=42)

    promote_mock.assert_called_once()
    assert result[0].sourcePayload.objectName == OBJECT_NAME


def test_promote_failure_drops_that_citation_and_keeps_others():
    temp = _temp_item()
    rag = _rag_item()
    matched = {"filename": "报价单.pdf", "file_url": "https://minio.example/tmp/报价单.pdf"}

    with (
        patch(
            "bisheng.core.storage.chat_attachment.promote_chat_attachments_sync",
            side_effect=RuntimeError("minio down"),
        ),
        patch(
            "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
            side_effect=lambda items: items,
        ),
    ):
        result = attach_temp_object_names([temp, rag], [matched], user_id=42)

    assert [item.citationId for item in result] == [rag.citationId]


def test_cache_write_failure_drops_temp_citations():
    temp = _temp_item(object_name=OBJECT_NAME)
    rag = _rag_item()
    files = [{"filename": "报价单.pdf", "object_name": OBJECT_NAME}]

    with patch(
        "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
        side_effect=RuntimeError("redis down"),
    ):
        result = attach_temp_object_names([temp, rag], files, user_id=42)

    assert [item.citationId for item in result] == [rag.citationId]


def test_source_url_promotes_when_question_files_are_missing():
    """Canvas debug has no chat_id, so question-message files are empty."""
    item = _temp_item()

    def _promote(files, user_id):
        assert files == [{"filename": "报价单.pdf", "file_url": item.sourcePayload.sourceUrl}]
        promoted = dict(files[0])
        promoted["object_name"] = OBJECT_NAME
        return [promoted]

    with (
        patch(
            "bisheng.core.storage.chat_attachment.promote_chat_attachments_sync",
            side_effect=_promote,
        ) as promote_mock,
        patch(
            "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
            side_effect=lambda items: items,
        ),
    ):
        result = attach_temp_object_names([item], [], user_id=42)

    promote_mock.assert_called_once()
    assert result[0].sourcePayload.objectName == OBJECT_NAME


def test_workflow_temp_prefix_is_rejected():
    item = _temp_item()
    files = [{"filename": "报价单.pdf", "object_name": "workflow_temp/42/x.pdf"}]
    with patch(
        "bisheng.citation.domain.services.citation_prompt_helper.cache_citation_registry_items_sync",
        side_effect=lambda items: items,
    ):
        result = attach_temp_object_names([item], files, user_id=42)
    assert result == []


def test_saving_the_same_answer_twice_does_not_insert_duplicate_rows():
    repository = MagicMock()
    repository.ensure_citations_sync = MagicMock()
    repository.ensure_relations_sync = MagicMock()
    repository.find_by_message_id_sync = MagicMock(return_value=[SimpleNamespace(citation_id="tempsearch_abcd1234")])
    service = CitationRegistryService(repository)
    item = _temp_item(object_name=OBJECT_NAME)
    service.save_citations_sync(message_id=9, items=[item, item], chat_id="chat-1")
    written = repository.ensure_citations_sync.call_args[0][0]
    assert len(written) == 1
    assert written[0].citation_id == item.citationId
    service.save_citations_sync(message_id=9, items=[item], chat_id="chat-1")
    second = repository.ensure_citations_sync.call_args[0][0]
    assert len(second) == 1
