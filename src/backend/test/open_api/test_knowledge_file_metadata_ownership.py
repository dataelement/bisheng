"""File user-metadata writes must stay inside the knowledge base named in the request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.open_api.api.exception_handlers import open_api_http_status
from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq

KNOWLEDGE_ID = 1
OTHER_KNOWLEDGE_ID = 2


def _file(file_id: int, knowledge_id: int):
    return SimpleNamespace(
        id=file_id,
        knowledge_id=knowledge_id,
        user_metadata={"author": {"field_value": "old", "field_type": "string"}},
        updater_id=None,
    )


@pytest.fixture
def service(monkeypatch):
    knowledge = SimpleNamespace(
        id=KNOWLEDGE_ID,
        metadata_fields=[
            {"field_name": "author", "field_type": "string"},
            {"field_name": "dept", "field_type": "string"},
        ],
    )
    knowledge_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=knowledge))
    file_repo = SimpleNamespace(
        find_by_ids=AsyncMock(return_value=[_file(10, KNOWLEDGE_ID), _file(20, OTHER_KNOWLEDGE_ID)]),
        update=AsyncMock(side_effect=lambda model: model),
    )
    svc = KnowledgeFileService(knowledge_file_repository=file_repo, knowledge_repository=knowledge_repo)
    monkeypatch.setattr(KnowledgeFileService, "_ensure_knowledge_access", AsyncMock(return_value=None))
    monkeypatch.setattr(KnowledgeFileService, "modify_milvus_file_user_metadata", AsyncMock())
    monkeypatch.setattr(KnowledgeFileService, "modify_elasticsearch_file_user_metadata", AsyncMock())
    return svc


USER = SimpleNamespace(user_id=7)


def _modify_reqs(field_name: str):
    return [
        ModifyKnowledgeFileMetaDataReq(
            knowledge_file_id=10, user_metadata_list=[{"field_name": field_name, "field_value": "a"}]
        ),
        ModifyKnowledgeFileMetaDataReq(
            knowledge_file_id=20, user_metadata_list=[{"field_name": field_name, "field_value": "b"}]
        ),
    ]


async def _assert_rejected_without_writes(service, call):
    with pytest.raises(KnowledgeFileNotExistError) as raised:
        await call
    assert raised.value.code == 10971
    assert open_api_http_status(raised.value) == 404
    # The message is the same as for a missing file, so it does not reveal file 20 exists elsewhere.
    assert raised.value.message == "Knowledge Base FilesID:20 Does not exist"
    service.knowledge_file_repository.update.assert_not_awaited()
    KnowledgeFileService.modify_milvus_file_user_metadata.assert_not_awaited()
    KnowledgeFileService.modify_elasticsearch_file_user_metadata.assert_not_awaited()


async def test_add_user_metadata_rejects_file_from_other_knowledge(service):
    await _assert_rejected_without_writes(
        service, service.add_file_user_metadata(USER, KNOWLEDGE_ID, _modify_reqs("dept"))
    )


async def test_modify_user_metadata_rejects_file_from_other_knowledge(service):
    await _assert_rejected_without_writes(
        service, service.batch_modify_file_user_metadata(USER, KNOWLEDGE_ID, _modify_reqs("author"))
    )


async def test_delete_user_metadata_rejects_file_from_other_knowledge(service):
    reqs = [
        DeleteUserMetadataReq(knowledge_file_id=10, field_names=["author"]),
        DeleteUserMetadataReq(knowledge_file_id=20, field_names=["author"]),
    ]
    await _assert_rejected_without_writes(service, service.batch_delete_file_user_metadata(USER, KNOWLEDGE_ID, reqs))


async def test_modify_user_metadata_accepts_files_of_same_knowledge(service):
    reqs = [
        ModifyKnowledgeFileMetaDataReq(
            knowledge_file_id=10, user_metadata_list=[{"field_name": "author", "field_value": "new"}]
        )
    ]

    updated = await service.batch_modify_file_user_metadata(USER, KNOWLEDGE_ID, reqs)

    assert [f.id for f in updated] == [10]
    assert updated[0].user_metadata["author"]["field_value"] == "new"
    service.knowledge_file_repository.update.assert_awaited_once()
