"""Original web dedup priority against actual resource/identity/SQL, without network."""

from unittest.mock import Mock

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileDuplicateError, SpaceFileNameDuplicateError
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.web_link_import_service import (
    WEB_LINK_LOGIN_ENTRY_MARKDOWN,
    WebLinkImportResult,
)
from test.knowledge_unification import test_kn_space_web_link_wiring as fixtures
from test.knowledge_unification.test_kn_space_upload_wiring import chain_snapshot

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy
upload = fixtures.upload
web = fixtures.web


def _import_result(*, markdown, final_url, content_hash):
    return WebLinkImportResult(
        title="Example",
        markdown=markdown,
        final_url=final_url,
        content_hash=content_hash,
        content_length=len(markdown.encode("utf-8")),
    )


async def _existing(web, monkeypatch):
    web.fetch.return_value = _import_result(
        markdown="Same real article body.\n", final_url="https://example.com/a", content_hash="real-content-hash"
    )
    await web.upload.service.import_web_link(40, "https://example.com/a")
    dedup = Mock(wraps=module.KnowledgeFileDao.get_file_by_condition)
    monkeypatch.setattr(module.KnowledgeFileDao, "get_file_by_condition", dedup)
    web.upload.publish.reset_mock()
    web.upload.legacy.storage.reset_mock()
    return dedup, await chain_snapshot(web.upload)


async def test_import_web_link_skips_content_dedup_for_placeholder_markdown(web, monkeypatch):
    dedup, before = await _existing(web, monkeypatch)
    web.fetch.return_value = _import_result(
        markdown=f"{WEB_LINK_LOGIN_ENTRY_MARKDOWN}\n",
        final_url="https://www.w3schools.com/",
        content_hash="placeholder-hash-a",
    )
    with pytest.raises(SpaceFileNameDuplicateError):
        await web.upload.service.import_web_link(40, "https://www.rfc-editor.org/rfc/rfc7230.txt")
    dedup.assert_called_once_with(knowledge_id=40, md5_=None, file_name="Example.html")
    assert await chain_snapshot(web.upload) == before
    web.upload.publish.assert_not_called()
    web.upload.legacy.storage.put_object_sync.assert_not_called()


async def test_import_web_link_still_blocks_real_duplicate_content(web, monkeypatch):
    dedup, before = await _existing(web, monkeypatch)
    web.fetch.return_value = _import_result(
        markdown="Same real article body.\n", final_url="https://example.com/a", content_hash="real-content-hash"
    )
    with pytest.raises(SpaceFileDuplicateError):
        await web.upload.service.import_web_link(40, "https://example.com/b")
    dedup.assert_called_once_with(knowledge_id=40, md5_="real-content-hash", file_name="Example.html")
    assert await chain_snapshot(web.upload) == before
    web.upload.publish.assert_not_called()
    web.upload.legacy.storage.put_object_sync.assert_not_called()


async def test_import_web_link_preserves_name_only_duplicate_error(web, monkeypatch):
    dedup, before = await _existing(web, monkeypatch)
    web.fetch.return_value = _import_result(
        markdown="New article body.\n", final_url="https://example.com/a", content_hash="new-content-hash"
    )
    with pytest.raises(SpaceFileNameDuplicateError):
        await web.upload.service.import_web_link(40, "https://example.com/a")
    dedup.assert_called_once_with(knowledge_id=40, md5_="new-content-hash", file_name="Example.html")
    assert await chain_snapshot(web.upload) == before
    web.upload.publish.assert_not_called()
    web.upload.legacy.storage.put_object_sync.assert_not_called()
