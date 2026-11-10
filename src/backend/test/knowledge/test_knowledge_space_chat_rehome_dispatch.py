from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from test.knowledge_unification import test_kn_space_reference_lifecycle as deletion_native
from test.knowledge_unification import test_move_processing_owner as move_native

store, tenant, business = deletion_native.store, deletion_native.tenant, deletion_native.business
consumer, deletion_consumer = deletion_native.consumer, deletion_native.deletion_consumer
moving, accepted, application = move_native.moving, move_native.accepted, move_native.application


def _service() -> KnowledgeSpaceService:
    return KnowledgeSpaceService(
        request=MagicMock(),
        login_user=SimpleNamespace(user_id=7, user_name="user-7", tenant_id=1),
    )


async def test_batch_delete_normalization_removes_duplicates_and_covered_descendants():
    service = _service()
    rows = [
        SimpleNamespace(id=10, knowledge_id=1, file_level_path=""),
        SimpleNamespace(id=11, knowledge_id=1, file_level_path="/10"),
        SimpleNamespace(id=12, knowledge_id=1, file_level_path="/10/11"),
        SimpleNamespace(id=20, knowledge_id=1, file_level_path="/10/11"),
        SimpleNamespace(id=21, knowledge_id=1, file_level_path=""),
    ]

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=rows,
    ):
        file_ids, folder_ids = await service._normalize_batch_delete_inputs(
            1,
            [20, 20, 21],
            [10, 11, 12, 10],
        )

    assert file_ids == [21]
    assert folder_ids == [10]


async def test_clear_space_dispatches_after_durable_finalize_and_cleanup(deletion_consumer, monkeypatch):
    context, service, _ = deletion_consumer
    await deletion_native.seed(context)
    events = []
    before = deletion_native.state(context)
    original = context.deletion._finalize

    async def finalized(job):
        await original(job)
        # Independent native SQL observes the committed business clear.
        with context.sync.connect() as connection:
            assert (
                connection.scalar(
                    sa.select(sa.func.count()).select_from(KnowledgeFile).where(KnowledgeFile.knowledge_id == 40)
                )
                == 0
            )
        events.append("delete_commit")

    def dispatch(**kwargs):
        deletion_native.assert_completed(context, {"folder:501", "knowledge_file:503"})
        assert context.order[-3:] == [("purge", "minio"), ("purge", "es"), ("purge", "milvus")]
        events.append("dispatch")

    monkeypatch.setattr(context.deletion, "_finalize", finalized)
    service._dispatch_knowledge_chat_rehome = MagicMock(side_effect=dispatch)
    await service.clear_space(40)
    assert events == ["delete_commit", "dispatch"]
    service._dispatch_knowledge_chat_rehome.assert_called_once_with(
        source_space_id=40,
        resources=[("folder", 501), ("knowledge_file", 503)],
        reason="clear_space",
    )
    after = deletion_native.state(context)
    old = next(row for row in before["knowledge"] if row["id"] == 40)
    current = next(row for row in after["knowledge"] if row["id"] == 40)
    assert all(current[key] == old[key] for key in ("model", "index_name", "collection_name"))
    deletion_native.KnowledgeService._init_knowledge_indices_sync.assert_not_called()


async def test_delete_file_dispatches_only_after_hard_delete_commit():
    service = _service()
    events: list[str] = []
    file_record = SimpleNamespace(
        id=20,
        knowledge_id=1,
        file_level_path="/10",
    )
    service._get_file_for_action = AsyncMock(return_value=file_record)
    service._require_action = AsyncMock()
    service._ensure_space_async_task_tenant_consistency = MagicMock()

    async def committed_delete(resource):
        events.append("hard_delete_commit")
        return {
            "fga_resources": [
                {"resource_type": "knowledge_file", "resource_id": 20},
                {"resource_type": "knowledge_file", "resource_id": 21},
            ]
        }

    service._delete_formal_resource = AsyncMock(side_effect=committed_delete)
    service._cleanup_resource_tuples = AsyncMock()
    service.update_folder_update_time = AsyncMock()
    service._dispatch_knowledge_chat_rehome = MagicMock(side_effect=lambda **kwargs: events.append("dispatch"))

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=1),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
    ):
        await service.delete_file(20)

    assert events == ["hard_delete_commit", "dispatch"]
    service._dispatch_knowledge_chat_rehome.assert_called_once_with(
        source_space_id=1,
        resources=[("knowledge_file", 20), ("knowledge_file", 21)],
        reason="delete_file",
    )


@pytest.mark.parametrize("fail_after_ready", [False, True])
async def test_cross_space_move_dispatch_is_after_actual_commit_and_absent_on_failure(
    application, monkeypatch, fail_after_ready
):
    app = application
    events = []
    ready = app.owner.jobs.amark_move_ready
    rehome = app.owner.chat_rehome

    async def marked(*args, **kwargs):
        result = await ready(*args, **kwargs)
        events.append("ready_sql")
        if fail_after_ready:
            raise RuntimeError("actual ready tail failure")
        return result

    def dispatched(**kwargs):
        # The original native fixture independently reads actual File/Job state
        # and rejects any session still holding a transaction at this point.
        rehome(**kwargs)
        events.append("dispatch")

    monkeypatch.setattr(app.owner.jobs, "amark_move_ready", marked)
    app.owner.chat_rehome = dispatched
    if fail_after_ready:
        with pytest.raises(RuntimeError, match="actual ready tail failure"):
            await app.owner.aensure_logical(app.built.lease)
        assert events == ["ready_sql"] and not app.chat
    else:
        assert (await app.owner.aensure_logical(app.built.lease)).state == "running"
        assert events == ["ready_sql", "dispatch"] and len(app.chat) == 1
    async with app.built.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == (10 if fail_after_ready else 11)
        marker = (await session.get(KnowledgeProcessingJob, app.built.job_id)).move_logical_marker
        assert (marker is None) == fail_after_ready
