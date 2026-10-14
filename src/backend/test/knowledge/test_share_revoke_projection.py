"""旧清理正在执行时新分享必须在独立入口上收敛。"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlmodel import SQLModel

from bisheng.approval.domain.models.approval_instance import ApprovalActionLog, ApprovalInstance
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.document_projection_batch_service import DocumentProjectionBatchService
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import ShareKnowledgeDocumentCommand
from test.knowledge.test_document_projection_batch import batch_environment as _environment
from test.knowledge.test_document_projection_batch import make_writer
from test.knowledge.test_document_projection_batch_worker import worker as _worker
from test.knowledge.test_knowledge_document_distribution_share import _service

batch_environment = _environment
worker = _worker


async def test_old_cleanup_then_new_projection_preserves_recipient_membership(batch_environment, worker, monkeypatch):
    factory, _ = batch_environment
    async with factory() as repository:
        async with repository.session.bind.begin() as connection:
            await connection.run_sync(
                lambda bind: SQLModel.metadata.create_all(
                    bind,
                    tables=[ApprovalInstance.__table__, ApprovalActionLog.__table__],
                )
            )
        repository.session.add_all(
            [Knowledge(id=id_, tenant_id=7, name=f"空间{id_}", type=KnowledgeTypeEnum.SPACE.value) for id_ in (20, 30)]
        )
        await repository.session.commit()
        await _service(repository.session).remove_share_entry(
            tenant_id=7,
            document_id=91,
            share_entry_id=102,
            actor_entry_id=100,
        )

    @asynccontextmanager
    async def db():
        async with factory() as repository:
            yield repository.session

    monkeypatch.setattr(worker, "get_async_db_session", db)
    delete_permissions = AsyncMock()
    delete_fulltext = AsyncMock()
    monkeypatch.setattr(worker, "_delete_entry_permissions", delete_permissions)
    monkeypatch.setattr(worker, "request_file_delete_intents", delete_fulltext)
    state = {"new_id": None, "knowledge_ids": None}

    async def old_write(plans, *, guard):
        await guard()
        assert plans[0].membership.knowledge_ids == (10, 20)
        # 模拟旧任务已经读取快照但尚未完成索引及最终删除。
        async with factory() as repository:
            new = await _service(repository.session).share_approved(
                ShareKnowledgeDocumentCommand(
                    tenant_id=7,
                    approval_instance_id=8002,
                    document_id=91,
                    source_entry_id=100,
                    target_space_id=30,
                    allow_download=True,
                )
            )
            state["new_id"] = new.share_entry_id
        async with factory() as repository:
            blocked = await repository.claim_batch([state["new_id"]], "new-too-early", 4)
            assert not blocked.claimed
        state["knowledge_ids"] = plans[0].membership.knowledge_ids
        return {}

    old_writer = make_writer(apply_projection_batch=AsyncMock(side_effect=old_write))
    old_service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=old_writer,
        finalizer=worker._finalize_deleting_entry,
    )
    assert await old_service.run(7, [102], "old-cleanup") == {102: "cleaned"}
    async with factory() as repository:
        assert await repository.find_by_id(102) is None
        assert (await repository.find_by_id(state["new_id"])).entry_status == "active"
    delete_permissions.assert_awaited_once_with(102)
    assert delete_fulltext.await_args.args[1][0].file_id == 102

    async def new_write(plans, *, guard):
        await guard()
        state["knowledge_ids"] = plans[0].membership.knowledge_ids
        return {}

    new_writer = make_writer(apply_projection_batch=AsyncMock(side_effect=new_write))
    new_service = DocumentProjectionBatchService(
        repository_factory=factory,
        writer=new_writer,
        finalizer=worker._finalize_deleting_entry,
    )
    assert await new_service.run(7, [state["new_id"]], "new-projection") == {state["new_id"]: "ready"}
    assert state["knowledge_ids"] == (10, 20, 30)
    async with factory() as repository:
        assert (await repository.find_by_id(100)).entry_status == "active"
        assert (await repository.find_by_id(101)).entry_status == "active"
