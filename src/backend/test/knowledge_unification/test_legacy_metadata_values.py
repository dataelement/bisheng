"""Legacy v2 metadata operations use the real physical-version SPACE writer."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeFileFailedError,
    KnowledgeFileNotExistError,
    KnowledgeMetadataFieldNotExistError,
)
from bisheng.knowledge.application import knowledge_index_edit as editor_module
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.open_endpoints.api import dependencies
from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq
from bisheng.worker.knowledge.metadata_worker import MetadataIndexResult
from test.knowledge_unification import test_move_scope_repository as native

store, tenant, moving = native.store, native.tenant, native.moving
USER = UserPayload(user_id=7, tenant_id=101, user_role=[], user_name="creator")


async def test_actual_v2_dependency_installs_metadata_writer():
    service = await dependencies.get_knowledge_file_service(
        knowledge_repository=object(), knowledge_file_repository=object()
    )
    assert isinstance(service.metadata_value_writer, editor_module.KnowledgeIndexEditApplication)


@pytest.mark.parametrize("operation", ["add", "patch", "delete"])
@pytest.mark.parametrize("failed", [False, True])
async def test_space_batch_keeps_history_and_commits_only_after_index_ack(moving, monkeypatch, operation, failed):
    with Session(moving.sync) as session:
        original = session.get(KnowledgeFile, 81).model_dump()
        before = session.get(KnowledgeFile, 82).model_dump()
    opened, writes = [], []

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine) as session:
            opened.append(session)
            yield session

    async def authorize(*args, **kwargs):
        assert kwargs["resource_type"] == "knowledge_space" and kwargs["action"] == "edit"
        assert not any(session.in_transaction() for session in opened)

    async def writer(**kwargs):
        assert kwargs["file_id"] == 82
        assert not any(session.in_transaction() for session in opened)
        with Session(moving.sync) as session:
            assert session.get(KnowledgeFile, 82).model_dump() == before
        writes.append(kwargs)
        await kwargs["guard"]()
        if failed:
            raise KnowledgeFileFailedError(exception="ES_ack_failed")
        return MetadataIndexResult(82, 12, 12)

    monkeypatch.setattr(editor_module, "require_business_action", authorize)
    monkeypatch.setattr(KnowledgeFileService, "_ensure_knowledge_access", AsyncMock())
    monkeypatch.setattr(
        KnowledgeFileService,
        "modify_milvus_file_user_metadata",
        AsyncMock(side_effect=AssertionError("old SPACE path")),
    )
    editor = editor_module.KnowledgeIndexEditApplication(session_factory=sessions, writer=writer)
    async with AsyncSession(moving.engine) as session:
        service = KnowledgeFileService(
            KnowledgeFileRepositoryImpl(session), KnowledgeRepositoryImpl(session), metadata_value_writer=editor
        )
        monkeypatch.setattr(
            service.knowledge_repository,
            "find_by_id",
            AsyncMock(side_effect=AssertionError("SPACE dispatch must not hold legacy SQL open during IO")),
        )
        request = ModifyKnowledgeFileMetaDataReq(
            knowledge_file_id=82,
            user_metadata_list=[{"field_name": "lose" if operation == "add" else "keep", "field_value": "19"}],
        )
        calls = {
            "add": lambda: service.add_file_user_metadata(USER, 10, [request]),
            "patch": lambda: service.batch_modify_file_user_metadata(USER, 10, [request]),
            "delete": lambda: service.batch_delete_file_user_metadata(
                USER, 10, [DeleteUserMetadataReq(knowledge_file_id=82, field_names=["keep"])]
            ),
        }
        if failed:
            with pytest.raises(KnowledgeFileFailedError):
                await calls[operation]()
        else:
            await calls[operation]()
    assert len(writes) == 1
    with Session(moving.sync) as session:
        assert session.get(KnowledgeFile, 81).model_dump() == original
        after = session.get(KnowledgeFile, 82).user_metadata
        if failed:
            assert after == before["user_metadata"]
        else:
            assert after["source_url"] == before["user_metadata"]["source_url"]
            assert after["html_snapshot_object_name"] == before["user_metadata"]["html_snapshot_object_name"]
            if operation == "delete":
                assert "keep" not in after
            elif operation == "add":
                assert after["lose"]["field_value"] == 19
                assert after["keep"] == before["user_metadata"]["keep"]
            else:
                assert after["keep"]["field_value"] == "19"


async def test_later_invalid_metadata_does_not_write_the_first_file(moving, monkeypatch):
    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine) as session:
            yield session

    monkeypatch.setattr(editor_module, "require_business_action", AsyncMock())
    writer = AsyncMock(side_effect=AssertionError("validate the whole request before external writes"))
    editor = editor_module.KnowledgeIndexEditApplication(session_factory=sessions, writer=writer)
    requests = [
        ModifyKnowledgeFileMetaDataReq(
            knowledge_file_id=file_id, user_metadata_list=[{"field_name": field, "field_value": "new"}]
        )
        for file_id, field in [(81, "keep"), (82, "absent")]
    ]
    with pytest.raises(KnowledgeMetadataFieldNotExistError):
        await editor.abatch_metadata(USER, 10, requests, operation="patch")
    writer.assert_not_awaited()


async def test_repeated_file_requests_compose_once_without_cross_space_writes(moving, monkeypatch):
    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine) as session:
            yield session

    monkeypatch.setattr(editor_module, "require_business_action", AsyncMock())
    writer = AsyncMock(side_effect=lambda **kwargs: MetadataIndexResult(kwargs["file_id"], 1, 1))
    editor = editor_module.KnowledgeIndexEditApplication(session_factory=sessions, writer=writer)
    requests = [
        ModifyKnowledgeFileMetaDataReq(
            knowledge_file_id=82, user_metadata_list=[{"field_name": "keep", "field_value": value}]
        )
        for value in ["first", "final"]
    ]
    with pytest.raises(KnowledgeFileNotExistError):
        await editor.abatch_metadata(USER, 11, requests, operation="patch")
    writer.assert_not_awaited()
    results = await editor.abatch_metadata(USER, 10, requests, operation="patch")
    writer.assert_awaited_once()
    assert len(results) == 2
    assert all(result["user_metadata"]["keep"]["field_value"] == "final" for result in results)
