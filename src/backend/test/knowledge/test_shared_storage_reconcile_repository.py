"""真实 ORM 查询覆盖规范文档聚合与既有投影代次登记。"""

from datetime import datetime, timedelta

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument, KnowledgeDocumentRepairState
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.shared_storage_reconcile_repository_impl import (
    SharedStorageReconcileRepositoryImpl,
)


async def test_full_scan_includes_ready_and_rebuild_uses_existing_generations(async_db_session):
    session = async_db_session
    connection = await session.connection()
    await connection.run_sync(lambda conn: KnowledgeDocumentRepairState.__table__.create(conn, checkfirst=True))
    from bisheng.knowledge.domain.models.knowledge_space_shared_storage import KnowledgeSpaceSharedStorageRouting
    await connection.run_sync(lambda conn: KnowledgeSpaceSharedStorageRouting.__table__.create(conn, checkfirst=True))
    now = datetime(2026, 9, 17, 1)
    session.add_all(
        [
            Knowledge(id=71, name="SPACE", type=3, user_id=1, tenant_id=1),
            Knowledge(id=72, name="NORMAL", type=0, user_id=1, tenant_id=1),
            KnowledgeDocument(id=81, tenant_id=1, knowledge_id=71, primary_version_id=91, content_generation=2),
            KnowledgeDocument(id=82, tenant_id=1, knowledge_id=72, primary_version_id=92, content_generation=1),
            KnowledgeDocumentVersion(id=91, document_id=81, knowledge_file_id=101, version_no=1, is_primary=True),
            KnowledgeFile(
                id=101,
                tenant_id=1,
                knowledge_id=71,
                file_name="原文.pdf",
                status=2,
                reference_document_id=81,
                entry_type="manager",
                entry_status="active",
                projection_status="ready",
                applied_content_generation=2,
                desired_content_generation=2,
                abstract="保留摘要",
                create_time=now,
                update_time=now,
            ),
            KnowledgeFile(
                id=102,
                tenant_id=1,
                knowledge_id=73,
                file_name="原文.pdf",
                status=2,
                reference_document_id=81,
                entry_type="share",
                entry_status="active",
                projection_status="ready",
                applied_content_generation=2,
                desired_content_generation=2,
                desired_entry_generation=6,
            ),
        ]
    )
    # 历史物理版本没有入口类型, 默认 pending 不应阻止当前主版本对账。
    session.add(
        KnowledgeFile(
            id=103,
            tenant_id=1,
            knowledge_id=71,
            file_name="历史版本.pdf",
            status=2,
            reference_document_id=81,
            entry_type=None,
            entry_status=None,
            projection_status="pending",
        )
    )
    await session.commit()
    repo = SharedStorageReconcileRepositoryImpl(session)
    assert await repo.upper_bound() == 81
    assert await repo.page_ids(0, 1000, 100) == [81]
    assert await repo.page_ids(81, 1000, 100) == []
    s = (await repo.snapshots([81], lock=True))[81]
    assert not s.skip_reason
    assert s.knowledge_ids == (71, 73)
    assert s.membership_generation == 6
    assert s.metadata["abstract"] == "保留摘要"
    assert await repo.queue_rebuild(s) == 101
    await session.commit()
    await session.refresh(await session.get(KnowledgeFile, 101))
    file = await session.get(KnowledgeFile, 101)
    assert file.projection_status == "pending"
    assert file.desired_content_generation == 2
    assert (await session.get(KnowledgeDocument, 81)).content_generation == 2
    assert (await repo.snapshots([81]))[81].skip_reason == "projection_busy"

    state = await session.get(KnowledgeDocumentRepairState, 81)
    assert state.attempts == 1
    file.projection_retry_count = 3
    await session.flush()
    for attempt in range(1, 8):
        state.next_retry_at = datetime.now() - timedelta(seconds=1)
        file.projection_status = "ready"
        await session.flush()
        snapshot = (await repo.snapshots([81], lock=True))[81]
        assert await repo.queue_rebuild(snapshot) == 101
        assert file.projection_retry_count == 3
    state.next_retry_at = None
    file.projection_status = "ready"
    await session.flush()
    snapshot = (await repo.snapshots([81], lock=True))[81]
    assert await repo.queue_rebuild(snapshot) == 0
    assert state.status == "dead"
    assert state.attempts == 8
    assert (await session.get(KnowledgeDocument, 81)).content_generation == 2
    for _ in range(8):
        assert await repo.claim_content_rebuild(101)
        await session.commit()
    assert not await repo.claim_content_rebuild(101)
    assert state.rebuild_attempts == 8
    file.md5 = "new-content"
    await session.flush()
    assert await repo.claim_content_rebuild(101)
    assert state.rebuild_attempts == 1
