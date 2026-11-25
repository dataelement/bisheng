from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from bisheng.open_mcp import metadata as metadata_service
from bisheng.open_mcp.contracts import (
    FileMetadataDeleteInput,
    FileMetadataListInput,
    FileMetadataWriteInput,
    MetadataFieldsAddInput,
    MetadataFieldsDeleteInput,
    MetadataFieldsGetInput,
    MetadataFieldsRenameInput,
)
from bisheng.open_mcp.registry import TOOL_REGISTRY
from bisheng.open_mcp.tools import metadata as metadata_tools


@pytest.fixture
def services(monkeypatch):
    user = SimpleNamespace(user_id=5)
    monkeypatch.setattr(metadata_service, "get_open_api_operator_async", AsyncMock(return_value=user))
    knowledge_service, file_service = MagicMock(), MagicMock()
    for name in (
        "add_metadata_fields",
        "update_metadata_fields",
        "delete_metadata_fields",
        "list_metadata_fields",
    ):
        setattr(knowledge_service, name, AsyncMock())
    for name in (
        "add_file_user_metadata",
        "batch_modify_file_user_metadata",
        "batch_delete_file_user_metadata",
        "list_knowledge_file_user_metadata",
    ):
        setattr(file_service, name, AsyncMock())

    @asynccontextmanager
    async def fake_services():
        yield knowledge_service, file_service

    monkeypatch.setattr(metadata_service, "_services", fake_services)
    return SimpleNamespace(user=user, knowledge=knowledge_service, files=file_service)


def test_field_names_must_follow_the_existing_rule():
    with pytest.raises(ValidationError):
        MetadataFieldsAddInput(knowledge_id=1, metadata_fields=[{"field_name": "Bad-Name", "field_type": "string"}])
    with pytest.raises(ValidationError):
        MetadataFieldsRenameInput(
            knowledge_id=1, metadata_fields=[{"old_field_name": "a", "new_field_name": "1abc"}]
        )
    with pytest.raises(ValidationError):
        FileMetadataListInput(knowledge_id=1, knowledge_file_ids=[])


def test_all_metadata_tools_require_write_scope_and_are_hidden_from_personal_keys():
    names = [name for name in TOOL_REGISTRY if "metadata" in name]
    assert len(names) == 8
    for name in names:
        assert TOOL_REGISTRY[name].scope == "knowledge:write"
        assert TOOL_REGISTRY[name].allow_pat is False


@pytest.mark.asyncio
async def test_add_fields_passes_validated_request(services):
    result = await metadata_tools.metadata_fields_add(
        MetadataFieldsAddInput(knowledge_id=9, metadata_fields=[{"field_name": "dept", "field_type": "string"}])
    )

    assert result.success is True
    user, request = services.knowledge.add_metadata_fields.await_args.args
    assert user is services.user
    assert request.knowledge_id == 9
    assert request.metadata_fields[0].field_name == "dept"


@pytest.mark.asyncio
async def test_rename_and_delete_run_background_follow_up(services):
    ran = []

    async def fake_update(user, request, tasks):
        tasks.add_task(lambda: ran.append("rename"))

    async def fake_delete(user, knowledge_id, field_names, tasks):
        tasks.add_task(lambda: ran.append("delete"))

    services.knowledge.update_metadata_fields = fake_update
    services.knowledge.delete_metadata_fields = fake_delete

    await metadata_tools.metadata_fields_rename(
        MetadataFieldsRenameInput(knowledge_id=9, metadata_fields=[{"old_field_name": "a", "new_field_name": "b"}])
    )
    await metadata_tools.metadata_fields_delete(MetadataFieldsDeleteInput(knowledge_id=9, field_names=["b"]))

    assert ran == ["rename", "delete"]


@pytest.mark.asyncio
async def test_get_fields_maps_only_declared_fields(services):
    services.knowledge.list_metadata_fields.return_value = [
        {"field_name": "dept", "field_type": "string", "updated_at": 1, "internal": "x"}
    ]

    result = await metadata_tools.metadata_fields_get(MetadataFieldsGetInput(knowledge_id=9))

    assert result.model_dump()["metadata_fields"] == [{"field_name": "dept", "field_type": "string", "updated_at": 1}]


@pytest.mark.asyncio
async def test_file_metadata_write_delete_and_list(services):
    write = FileMetadataWriteInput(
        knowledge_id=9,
        items=[{"knowledge_file_id": 3, "user_metadata_list": [{"field_name": "dept", "field_value": "法务"}]}],
    )
    await metadata_tools.file_metadata_add(write)
    await metadata_tools.file_metadata_modify(write)
    await metadata_tools.file_metadata_delete(
        FileMetadataDeleteInput(knowledge_id=9, items=[{"knowledge_file_id": 3, "field_names": ["dept"]}])
    )
    services.files.list_knowledge_file_user_metadata.return_value = {3: {"dept": "法务"}}
    listed = await metadata_tools.file_metadata_list(FileMetadataListInput(knowledge_id=9, knowledge_file_ids=[3]))

    _, knowledge_id, requests = services.files.add_file_user_metadata.await_args.args
    assert knowledge_id == 9
    assert requests[0].knowledge_file_id == 3
    assert requests[0].user_metadata_list[0].field_value == "法务"
    services.files.batch_modify_file_user_metadata.assert_awaited_once()
    _, _, deletes = services.files.batch_delete_file_user_metadata.await_args.args
    assert deletes[0].field_names == ["dept"]
    assert listed.items == {"3": {"dept": "法务"}}
