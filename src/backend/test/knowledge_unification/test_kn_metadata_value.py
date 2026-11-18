"""T099: one physical version, actual SQL and complete index acknowledgements."""

from contextlib import asynccontextmanager

import pytest
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError
from bisheng.knowledge.application import knowledge_index_edit as module
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.knowledge_schema import ModifyKnowledgeFileMetaDataReq
from bisheng.worker.knowledge.metadata_worker import MetadataIndexResult
from test.knowledge_unification import test_move_scope_repository as native

store, tenant, moving = native.store, native.tenant, native.moving


@pytest.mark.parametrize("failed", [False, True])
async def test_history_metadata_awaits_real_writer_and_only_then_commits_its_physical_file(moving, monkeypatch, failed):
    opened = []

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine) as session:
            opened.append(session)
            yield session

    async def authorize(*args, **kwargs):
        assert (
            kwargs["resource_type"] == "knowledge_space" and kwargs["resource_id"] == 10 and kwargs["action"] == "edit"
        )
        assert not any(session.in_transaction() for session in opened)

    async def writer(**kwargs):
        assert kwargs["file_id"] == 82 and not any(session.in_transaction() for session in opened)
        await kwargs["guard"]()
        if failed:
            raise KnowledgeFileFailedError(exception="actual_ES_ack_failed")
        return MetadataIndexResult(82, 3, 3)

    monkeypatch.setattr(module, "require_business_action", authorize)
    editor = module.KnowledgeIndexEditApplication(session_factory=sessions, writer=writer)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[], user_name="creator")
    request = ModifyKnowledgeFileMetaDataReq(
        knowledge_file_id=82, user_metadata_list=[{"field_name": "keep", "field_value": "changed"}]
    )
    with Session(moving.sync) as session:
        original = session.get(KnowledgeFile, 81).model_dump()
        history = session.get(KnowledgeFile, 82).model_dump()
    if failed:
        with pytest.raises(KnowledgeFileFailedError):
            await editor.amodify_metadata(user, request)
    else:
        result = await editor.amodify_metadata(user, request)
        assert result["index_update"] == {"completed": True, "milvus_count": 3, "es_count": 3}
    with Session(moving.sync) as session:
        assert session.get(KnowledgeFile, 81).model_dump() == original
        changed = session.get(KnowledgeFile, 82)
        assert changed.object_name == history["object_name"] and changed.status == history["status"]
        if failed:
            assert changed.user_metadata == history["user_metadata"]
        else:
            assert changed.user_metadata["keep"]["field_value"] == "changed"
