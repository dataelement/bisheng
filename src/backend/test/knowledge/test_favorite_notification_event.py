from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.favorite_notification_schema import (
    FavoriteChangeEvent,
    FavoriteRecipientSnapshot,
)
from bisheng.knowledge.domain.services import favorite_notify
from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_DELETED,
    FAVORITE_SOURCE_RENAMED,
    enqueue_favorite_change_events,
)


def _event(
    source_file_id: int,
    *,
    action_code: str = FAVORITE_SOURCE_RENAMED,
    recipients: list[FavoriteRecipientSnapshot] | None = None,
) -> FavoriteChangeEvent:
    return FavoriteChangeEvent(
        tenant_id=1,
        source_space_id=10,
        source_file_id=source_file_id,
        file_name="制度.pdf",
        action_code=action_code,
        before_value="旧制度.pdf",
        after_value="制度.pdf",
        actor_user_id=7,
        actor_user_name="编辑者",
        recipient_snapshots=recipients,
    )


def test_favorite_change_event_is_json_serializable():
    event = _event(
        20,
        action_code=FAVORITE_SOURCE_DELETED,
        recipients=[FavoriteRecipientSnapshot(user_id=11, favorite_space_id=101)],
    )

    dumped = event.model_dump(mode="json")

    assert dumped["source_file_id"] == 20
    assert dumped["recipient_snapshots"] == [{"user_id": 11, "favorite_space_id": 101}]
    assert dumped["event_id"]


def test_enqueue_skips_empty_event_list():
    with patch.object(favorite_notify, "_get_favorite_notification_task") as task_loader:
        enqueue_favorite_change_events([])

    task_loader.assert_not_called()


def test_enqueue_splits_event_batches():
    events = [_event(file_id) for file_id in range(1, 102)]
    task = MagicMock()
    with patch.object(
        favorite_notify,
        "_get_favorite_notification_task",
        return_value=task,
    ):
        enqueue_favorite_change_events(events)

    assert task.apply_async.call_count == 2
    first_payload = task.apply_async.call_args_list[0].kwargs["args"][0]
    second_payload = task.apply_async.call_args_list[1].kwargs["args"][0]
    assert len(first_payload) == 100
    assert len(second_payload) == 1
    assert task.apply_async.call_args_list[0].kwargs["queue"] == "knowledge_celery"


def test_enqueue_splits_large_delete_recipient_snapshot():
    recipients = [
        FavoriteRecipientSnapshot(user_id=user_id, favorite_space_id=1000 + user_id)
        for user_id in range(1, 202)
    ]
    event = _event(20, action_code=FAVORITE_SOURCE_DELETED, recipients=recipients)
    task = MagicMock()
    with patch.object(
        favorite_notify,
        "_get_favorite_notification_task",
        return_value=task,
    ):
        enqueue_favorite_change_events([event])

    payload_sizes = [
        len(payload["recipient_snapshots"])
        for call in task.apply_async.call_args_list
        for payload in call.kwargs["args"][0]
    ]
    assert payload_sizes == [100, 100, 1]


def test_enqueue_is_best_effort_when_broker_fails():
    task = MagicMock()
    task.apply_async.side_effect = RuntimeError("broker unavailable")
    with patch.object(
        favorite_notify,
        "_get_favorite_notification_task",
        return_value=task,
    ):
        enqueue_favorite_change_events([_event(20)])


async def test_repository_bulk_favorite_lookup_executes_one_candidate_query():
    rows = [
        SimpleNamespace(
            user_metadata={"favorite_reference": {"source_file_id": 20}}
        ),
        SimpleNamespace(
            user_metadata={"favorite_reference": {"source_file_id": "21"}}
        ),
        SimpleNamespace(
            user_metadata={"favorite_reference": {"source_file_id": 99}}
        ),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    repository = KnowledgeFileRepositoryImpl(session)

    matched = await repository.find_favorite_referrers_by_source_file_ids(
        [20, 21]
    )

    assert matched == rows[:2]
    session.execute.assert_awaited_once()
