"""The original raw retry response still accepts TIMEOUT through the native Plan."""

from unittest.mock import MagicMock

from sqlalchemy import insert, select

from bisheng import worker as worker_module
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from test.knowledge_unification import test_kn_batch as native

deletion_tenant, db, batch = native.deletion_tenant, native.db, native.batch


async def test_batch_retry_accepts_timeout_file(batch, monkeypatch):
    async with batch.db.sessions() as session, session.begin():
        await session.execute(
            insert(KnowledgeFile).values(
                id=17,
                tenant_id=101,
                knowledge_id=1,
                user_id=7,
                file_name="timeout.pdf",
                file_type=1,
                file_level_path="",
                status=6,
                object_name="obj/17",
            )
        )
    app = batch.application()
    app.dispatcher = None
    service = KnowledgeSpaceService(request=None, login_user=batch.user)
    service.batch_application_factory = lambda: app

    async def records(ids):
        async with batch.db.sessions() as session:
            return (await session.execute(select(KnowledgeFile).where(KnowledgeFile.id.in_(ids)))).scalars().all()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids", records
    )
    task = MagicMock()
    monkeypatch.setattr(worker_module, "retry_knowledge_file_celery", task)
    assert await service.batch_retry_failed_files(1, [17]) is True
    task.delay.assert_called_once_with(17)
    assert any(call[0] == "knowledge_file" and 17 in call[1] and call[2] == ("rename",) for call in batch.calls)
    assert not any("visible" in call[2] or "edit" in call[2] for call in batch.calls)
    async with batch.db.sessions() as session:
        file = await session.get(KnowledgeFile, 17)
        assert file.status == KnowledgeFileStatus.WAITING and file.remark == "batch_retry_failed_files"
