from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from bisheng.common.errcode.knowledge import KnowledgeFileDeleteError, KnowledgeSharedStorageUnavailableError
from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpacePermissionDeniedError
from bisheng.open_endpoints.domain.schemas.filelib import FilelibSpaceCreate
from bisheng.open_endpoints.domain.services.filelib_space_command_service import FilelibSpaceCommandService


def commands():
    user = SimpleNamespace(user_id=5, tenant_id=1)
    route = SimpleNamespace(index_name="shared_text", collection_name="shared_vectors", embedding_model_id=7)
    repo = SimpleNamespace(
        find_by_ids=AsyncMock(), root_entries=AsyncMock(return_value=[]), persist_parse_result=AsyncMock()
    )
    owner = SimpleNamespace(
        create_knowledge_space=AsyncMock(return_value=SimpleNamespace(id=7)),
        update_knowledge_space=AsyncMock(),
        delete_space=AsyncMock(),
        delete_file=AsyncMock(),
        batch_delete=AsyncMock(),
        require_root_upload_permission=AsyncMock(),
    )
    guard = SimpleNamespace(
        user=user,
        repository=repo,
        space_service=owner,
        request=None,
        require_space=AsyncMock(return_value=SimpleNamespace(id=7)),
        route=AsyncMock(return_value=route),
    )
    return FilelibSpaceCommandService(query=guard), guard, owner, repo


async def test_create_defaults_to_owned_team_and_checks_physical_target(monkeypatch):
    service, _, owner, _ = commands()
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_space_command_service.QuotaService.check_quota", AsyncMock()
    )
    await service.create(FilelibSpaceCreate(name="资料"))
    assert owner.create_knowledge_space.await_args.kwargs["space_level"] == "team"
    owner.create_knowledge_space.reset_mock()
    with pytest.raises(HTTPException):
        await service.create(FilelibSpaceCreate(name="资料", index_name="old_index"))
    owner.create_knowledge_space.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["mixed", "permission", "missing"])
async def test_batch_rejects_before_first_lifecycle_mutation(invalid):
    service, guard, owner, repo = commands()
    repo.find_by_ids.return_value = [
        SimpleNamespace(id=1, knowledge_id=7, file_type=1, tenant_id=1),
        SimpleNamespace(id=2, knowledge_id=8 if invalid == "mixed" else 7, file_type=1, tenant_id=1),
    ]
    if invalid == "permission":
        guard.require_space.side_effect = SpacePermissionDeniedError()
    elif invalid == "missing":
        repo.find_by_ids.return_value.pop()
    expected = {
        "mixed": KnowledgeFileDeleteError,
        "permission": SpacePermissionDeniedError,
        "missing": SpaceFileNotFoundError,
    }[invalid]
    with pytest.raises(expected):
        await service.delete_files([1, 2])
    owner.batch_delete.assert_not_awaited()
    owner.delete_file.assert_not_awaited()
    owner.delete_space.assert_not_awaited()


async def test_clear_delegates_roots_once_and_keeps_container():
    service, _, owner, repo = commands()
    repo.root_entries.return_value = [SimpleNamespace(id=11, file_type=1), SimpleNamespace(id=12, file_type=0)]
    await service.clear(7)
    owner.batch_delete.assert_awaited_once_with(7, [11], [12])
    owner.delete_space.assert_not_awaited()


async def test_string_ingestion_does_not_modify_input_and_persists_failure(monkeypatch):
    service, _, _, repo = commands()
    file = SimpleNamespace(id=101, model_dump=lambda: {"id": 101})
    repo.persist_parse_result.return_value = file
    module = "bisheng.open_endpoints.domain.services.filelib_space_command_service."
    monkeypatch.setattr(module + "save_download_file", MagicMock(return_value="/tmp/data.txt"))
    monkeypatch.setattr(module + "QuotaService.get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))
    monkeypatch.setattr(
        module + "KnowledgeService.asave_knowledge_file", AsyncMock(return_value=(object(), [], [file], []))
    )
    writer = MagicMock(side_effect=ConnectionError("writer failed"))
    monkeypatch.setattr(module + "SharedSpaceDirectIngestionService.ingest_documents_sync", writer)
    docs = [Document(page_content="正文", metadata={"source": "data.txt", "chunk_index": 4})]
    with pytest.raises(KnowledgeSharedStorageUnavailableError):
        await service.ingest_strings(7, docs)
    assert docs[0].metadata == {"source": "data.txt", "chunk_index": 4}
    assert repo.persist_parse_result.await_args.args[:2] == (101, 3)


async def test_empty_chunks_rejected_before_any_upload():
    service, guard, _, _ = commands()
    with pytest.raises(HTTPException) as error:
        await service.ingest_strings(7, [])
    assert error.value.status_code == 422
    guard.require_space.assert_not_awaited()
