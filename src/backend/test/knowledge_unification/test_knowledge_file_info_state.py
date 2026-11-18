"""File info must expose the half of the state that `status` alone cannot carry.

`status`/`remark` describe the latest processing attempt; the index keeps the
last successful content. A client that only reads `status` plus chunks will
present retained content as if this attempt produced it, so the response has to
state version identity and whether retrieval may serve the file right now.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_file_service as module
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService

SPACE_ID = 7
FILE_ID = 89
USER = SimpleNamespace(user_id=7, user_name="u")


def _file(status: int = 3) -> KnowledgeFile:
    return KnowledgeFile(
        id=FILE_ID,
        knowledge_id=SPACE_ID,
        file_name="纯文本.docx",
        status=status,
        remark='{"code": 10953}',
    )


def _service(file_row: KnowledgeFile, knowledge) -> KnowledgeFileService:
    return KnowledgeFileService(
        knowledge_file_repository=SimpleNamespace(find_by_id=AsyncMock(return_value=file_row)),
        knowledge_repository=SimpleNamespace(find_by_id=AsyncMock(return_value=knowledge)),
    )


def _space() -> SimpleNamespace:
    return SimpleNamespace(id=SPACE_ID, type=KnowledgeTypeEnum.SPACE.value, metadata_fields=[])


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(KnowledgeFileService, "_ensure_knowledge_access", AsyncMock(return_value=None))
    monkeypatch.setattr(module.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_name="u")))


async def test_failed_attempt_reports_version_and_non_retrievable(monkeypatch, stub):
    service = _service(_file(status=3), _space())
    monkeypatch.setattr(service, "_file_version_link", AsyncMock(return_value=(77, 1, True)))
    monkeypatch.setattr(service, "_file_retrievable", AsyncMock(return_value=False))

    result = await service.get_knowledge_file_info(USER, FILE_ID)

    assert result.status == 3
    assert result.version_id == 77
    assert result.version_no == 1
    assert result.is_primary_version is True
    assert result.retrievable is False


async def test_successful_primary_version_is_retrievable(monkeypatch, stub):
    service = _service(_file(status=2), _space())
    monkeypatch.setattr(service, "_file_version_link", AsyncMock(return_value=(78, 2, True)))
    monkeypatch.setattr(service, "_file_retrievable", AsyncMock(return_value=True))

    result = await service.get_knowledge_file_info(USER, FILE_ID)

    assert (result.version_no, result.is_primary_version) == (2, True)
    assert result.retrievable is True


async def test_version_link_marks_a_superseded_file_as_non_primary(monkeypatch):
    service = _service(_file(), _space())
    version = SimpleNamespace(id=77, version_no=1, is_primary=False)
    document = SimpleNamespace(primary_version_id=78)
    anchor = SimpleNamespace(version=version, document=document)
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 60)
    monkeypatch.setattr(
        module.KnowledgeVersionReadRepository, "aget_anchor", AsyncMock(return_value=anchor)
    )

    assert await service._file_version_link(_space(), FILE_ID) == (77, 1, False)


async def test_version_link_degrades_without_hiding_file_facts(monkeypatch):
    service = _service(_file(), _space())
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 60)
    monkeypatch.setattr(
        module.KnowledgeVersionReadRepository,
        "aget_anchor",
        AsyncMock(side_effect=KnowledgeProcessingConflictError(reason="processing_scope_incomplete")),
    )

    assert await service._file_version_link(_space(), FILE_ID) == (None, None, None)


async def test_retrieval_read_failure_never_claims_retrievable(monkeypatch):
    service = _service(_file(), _space())

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(module, "get_async_db_session", session)
    monkeypatch.setattr(
        module.KnowledgeRetrievalFileRepository,
        "alist_successful_files",
        AsyncMock(side_effect=ValueError("session not admissible")),
    )

    assert await service._file_retrievable(_space(), _file()) is False


async def test_legacy_library_keeps_the_status_rule_without_version_chain():
    service = _service(_file(), SimpleNamespace(id=SPACE_ID, type=KnowledgeTypeEnum.NORMAL.value))

    legacy = SimpleNamespace(type=KnowledgeTypeEnum.NORMAL.value)

    assert await service._file_version_link(legacy, FILE_ID) == (None, None, None)
    assert await service._file_retrievable(legacy, _file(status=2)) is True
    assert await service._file_retrievable(legacy, _file(status=3)) is False