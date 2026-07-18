"""Web link import dedup rules shared by Platform knowledge base and Client knowledge space."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileDuplicateError, SpaceFileNameDuplicateError
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.web_link_import_service import (
    WEB_LINK_LOGIN_ENTRY_MARKDOWN,
    WebLinkImportResult,
)

_KS = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 1
    user_name = "tester"
    tenant_id = 1


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(request=None, login_user=_User())


def _import_result(*, markdown: str, final_url: str, content_hash: str) -> WebLinkImportResult:
    return WebLinkImportResult(
        title="Example",
        markdown=markdown,
        final_url=final_url,
        content_hash=content_hash,
        content_length=len(markdown.encode("utf-8")),
    )


@pytest.mark.asyncio
async def test_import_web_link_skips_content_dedup_for_placeholder_markdown() -> None:
    service = _service()
    dedup_calls: list[tuple] = []
    existing = SimpleNamespace(id=99, md5="existing-content-hash")

    def _get_file_by_condition(knowledge_id, md5_=None, file_name=None):
        dedup_calls.append((md5_, file_name))
        return [existing]

    import_result = _import_result(
        markdown=f"{WEB_LINK_LOGIN_ENTRY_MARKDOWN}\n",
        final_url="https://www.w3schools.com/",
        content_hash="placeholder-hash-a",
    )

    with (
        patch.object(service, "_require_permission_id", new=AsyncMock()),
        patch(
            f"{_KS}.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=SimpleNamespace(tenant_id=1)),
        ),
        patch.object(service, "_ensure_space_async_task_tenant_consistency"),
        patch(
            f"{_KS}.KnowledgeWebLinkImportService.fetch",
            new=AsyncMock(return_value=import_result),
        ),
        patch(
            f"{_KS}.KnowledgeFileDao.get_file_by_condition",
            side_effect=_get_file_by_condition,
        ),
    ):
        with pytest.raises(SpaceFileNameDuplicateError):
            await service.import_web_link(
                knowledge_id=1,
                url="https://www.rfc-editor.org/rfc/rfc7230.txt",
            )

    assert len(dedup_calls) == 1
    assert dedup_calls[0][0] is None
    assert dedup_calls[0][1] is not None


@pytest.mark.asyncio
async def test_import_web_link_still_blocks_real_duplicate_content() -> None:
    service = _service()
    existing = SimpleNamespace(id=99, md5="real-content-hash")
    dedup_calls: list[tuple] = []
    import_result = _import_result(
        markdown="Same real article body.\n",
        final_url="https://example.com/a",
        content_hash="real-content-hash",
    )

    with (
        patch.object(service, "_require_permission_id", new=AsyncMock()),
        patch(
            f"{_KS}.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=SimpleNamespace(tenant_id=1)),
        ),
        patch.object(service, "_ensure_space_async_task_tenant_consistency"),
        patch(
            f"{_KS}.KnowledgeWebLinkImportService.fetch",
            new=AsyncMock(return_value=import_result),
        ),
        patch(
            f"{_KS}.KnowledgeFileDao.get_file_by_condition",
            side_effect=lambda knowledge_id, md5_=None, file_name=None: (
                dedup_calls.append((md5_, file_name)) or [existing]
            ),
        ),
    ):
        with pytest.raises(SpaceFileDuplicateError):
            await service.import_web_link(
                knowledge_id=1,
                url="https://example.com/b",
            )

    assert len(dedup_calls) == 1
    assert dedup_calls[0][0] == "real-content-hash"
    assert dedup_calls[0][1] is not None


@pytest.mark.asyncio
async def test_import_web_link_preserves_name_only_duplicate_error() -> None:
    service = _service()
    existing = SimpleNamespace(id=99, md5="different-content-hash")
    import_result = _import_result(
        markdown="New article body.\n",
        final_url="https://example.com/a",
        content_hash="new-content-hash",
    )

    with (
        patch.object(service, "_require_permission_id", new=AsyncMock()),
        patch(
            f"{_KS}.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=SimpleNamespace(tenant_id=1)),
        ),
        patch.object(service, "_ensure_space_async_task_tenant_consistency"),
        patch(
            f"{_KS}.KnowledgeWebLinkImportService.fetch",
            new=AsyncMock(return_value=import_result),
        ),
        patch(
            f"{_KS}.KnowledgeFileDao.get_file_by_condition",
            return_value=[existing],
        ),
    ):
        with pytest.raises(SpaceFileNameDuplicateError):
            await service.import_web_link(
                knowledge_id=1,
                url="https://example.com/b",
            )
