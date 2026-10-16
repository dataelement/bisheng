"""Background tasks that rename or delete knowledge metadata fields on every file."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services import knowledge_metadata_service as module
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService


def _file(file_id: int, user_metadata):
    return SimpleNamespace(id=file_id, user_metadata=copy.deepcopy(user_metadata))


@pytest.fixture
def harness(monkeypatch):
    files = [
        _file(1, {"author": {"field_value": "alice", "field_type": "string", "updated_at": 1}}),
        _file(2, None),
        _file(
            3,
            {
                "author": {"field_value": "bob", "field_type": "string", "updated_at": 1},
                "dept": {"field_value": "rd", "field_type": "string", "updated_at": 1},
            },
        ),
    ]
    file_repo = SimpleNamespace(find_all=AsyncMock(return_value=files), update=AsyncMock())

    milvus_rows = {
        1: [{"pk": 1, "user_metadata": {"author": "alice"}}],
        2: [{"pk": 2, "user_metadata": None}],
        3: [{"pk": 3, "user_metadata": {"author": "bob", "dept": "rd"}}],
    }

    async def query(collection_name, filter, limit):
        file_id = int(filter.split("==")[1])
        return copy.deepcopy(milvus_rows[file_id])

    vector_client = SimpleNamespace(
        collection_name="col",
        aclient=SimpleNamespace(query=AsyncMock(side_effect=query), upsert=AsyncMock()),
    )
    es_client = SimpleNamespace(client=SimpleNamespace(update_by_query=AsyncMock()))
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_milvus_vectorstore", AsyncMock(return_value=vector_client))
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", AsyncMock(return_value=es_client))

    service = KnowledgeMetadataService(
        knowledge_repository=SimpleNamespace(),
        knowledge_file_repository=file_repo,
        permission_service=SimpleNamespace(),
    )
    knowledge = SimpleNamespace(id=9, collection_name="col", index_name="idx")
    return SimpleNamespace(
        service=service, files=files, file_repo=file_repo, knowledge=knowledge, vector_client=vector_client
    )


def _updated_files(harness):
    return {call.args[0].id: call.args[0] for call in harness.file_repo.update.await_args_list}


async def test_rename_keeps_value_under_new_field_name(harness):
    await harness.service.update_vectorstore_metadata_field_names(7, harness.knowledge, {"author": "owner"})

    updated = _updated_files(harness)
    assert updated[1].user_metadata["owner"]["field_value"] == "alice"
    assert "author" not in updated[1].user_metadata
    assert updated[3].user_metadata["owner"]["field_value"] == "bob"
    assert updated[3].user_metadata["dept"]["field_value"] == "rd"
    assert "author" not in updated[3].user_metadata
    # The stored entry must not contain a copy of itself under the new name.
    assert "owner" not in updated[1].user_metadata["owner"]


async def test_rename_skips_file_without_user_metadata(harness):
    await harness.service.update_vectorstore_metadata_field_names(7, harness.knowledge, {"author": "owner"})

    updated = _updated_files(harness)
    assert set(updated) == {1, 3}
    assert harness.files[1].user_metadata is None


async def test_delete_removes_field_and_skips_file_without_user_metadata(harness):
    await harness.service.delete_vectorstore_metadata_fields(7, harness.knowledge, ["author"])

    updated = _updated_files(harness)
    assert set(updated) == {1, 3}
    assert updated[1].user_metadata == {}
    assert set(updated[3].user_metadata) == {"dept"}
    assert harness.files[1].user_metadata is None
