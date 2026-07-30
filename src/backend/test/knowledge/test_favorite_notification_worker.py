import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.knowledge.domain.schemas.favorite_notification_schema import (
    FavoriteChangeEvent,
    FavoriteRecipientSnapshot,
)
from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_DELETED,
    FAVORITE_SOURCE_RENAMED,
    FavoriteNotificationService,
)


def test_knowledge_space_service_imports_in_fresh_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from bisheng.knowledge.domain.services.knowledge_space_service "
                "import KnowledgeSpaceService; "
                "assert 'bisheng.worker' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _reference(
    user_id: int,
    favorite_space_id: int,
    *,
    source_file_id: int = 20,
    tenant_id: int = 1,
):
    return SimpleNamespace(
        user_id=user_id,
        knowledge_id=favorite_space_id,
        tenant_id=tenant_id,
        user_metadata={
            "favorite_reference": {
                "source_space_id": 10,
                "source_file_id": source_file_id,
            }
        },
    )


def _event(
    *,
    action_code: str = FAVORITE_SOURCE_RENAMED,
    snapshots: list[FavoriteRecipientSnapshot] | None = None,
):
    return FavoriteChangeEvent(
        tenant_id=1,
        source_space_id=10,
        source_file_id=20,
        file_name="新制度.pdf",
        action_code=action_code,
        before_value="旧制度.pdf",
        after_value="新制度.pdf",
        actor_user_id=7,
        actor_user_name="编辑者",
        recipient_snapshots=snapshots,
    )


async def test_consumer_filters_permission_actor_and_duplicate_reference():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(
            return_value=[
                _reference(11, 101),
                _reference(11, 101),
                _reference(12, 102),
                _reference(7, 107),
            ]
        ),
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=20,
                    knowledge_id=10,
                    tenant_id=1,
                    deleted_at=None,
                )
            ]
        ),
    )
    message_service = SimpleNamespace(send_generic_notify=AsyncMock())
    can_view_file = AsyncMock(side_effect=lambda user_id, _file: user_id == 11)
    service = FavoriteNotificationService(
        file_repository=repository,
        message_service=message_service,
        can_view_file=can_view_file,
    )

    sent = await service.consume([_event()])

    assert sent == 1
    message_service.send_generic_notify.assert_awaited_once()
    call = message_service.send_generic_notify.await_args
    assert call.kwargs["receiver_user_ids"] == [11]
    business_url = next(
        item
        for item in call.kwargs["content_item_list"]
        if item["type"] == "business_url"
    )
    assert business_url["metadata"]["data"]["knowledge_space_id"] == "101"
    change = business_url["metadata"]["data"]["favorite_change"]
    assert change["before_value"] == "旧制度.pdf"
    assert change["after_value"] == "新制度.pdf"
    repository.find_favorite_referrers_by_source_file_ids.assert_awaited_once_with(
        [20]
    )


async def test_consumer_fails_closed_when_permission_check_errors():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(
            return_value=[_reference(11, 101)]
        ),
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=20,
                    knowledge_id=10,
                    tenant_id=1,
                    deleted_at=None,
                )
            ]
        ),
    )
    message_service = SimpleNamespace(send_generic_notify=AsyncMock())
    service = FavoriteNotificationService(
        file_repository=repository,
        message_service=message_service,
        can_view_file=AsyncMock(side_effect=RuntimeError("permission unavailable")),
    )

    assert await service.consume([_event()]) == 0
    message_service.send_generic_notify.assert_not_awaited()


async def test_consumer_skips_event_when_favorite_was_removed():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(return_value=[]),
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=20,
                    knowledge_id=10,
                    tenant_id=1,
                    deleted_at=None,
                )
            ]
        ),
    )
    message_service = SimpleNamespace(send_generic_notify=AsyncMock())
    can_view_file = AsyncMock(return_value=True)
    service = FavoriteNotificationService(
        file_repository=repository,
        message_service=message_service,
        can_view_file=can_view_file,
    )

    assert await service.consume([_event()]) == 0
    can_view_file.assert_not_awaited()
    message_service.send_generic_notify.assert_not_awaited()


async def test_delete_event_uses_snapshot_without_source_lookup_or_permission_check():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(),
        find_by_ids=AsyncMock(),
    )
    message_service = SimpleNamespace(send_generic_notify=AsyncMock())
    can_view_file = AsyncMock()
    service = FavoriteNotificationService(
        file_repository=repository,
        message_service=message_service,
        can_view_file=can_view_file,
    )
    event = _event(
        action_code=FAVORITE_SOURCE_DELETED,
        snapshots=[
            FavoriteRecipientSnapshot(user_id=11, favorite_space_id=101),
            FavoriteRecipientSnapshot(user_id=7, favorite_space_id=107),
        ],
    )

    assert await service.consume([event]) == 1
    repository.find_favorite_referrers_by_source_file_ids.assert_not_awaited()
    repository.find_by_ids.assert_not_awaited()
    can_view_file.assert_not_awaited()
    assert message_service.send_generic_notify.await_args.kwargs[
        "receiver_user_ids"
    ] == [11]


async def test_consumer_continues_after_one_message_fails():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(),
        find_by_ids=AsyncMock(),
    )
    message_service = SimpleNamespace(
        send_generic_notify=AsyncMock(
            side_effect=[RuntimeError("write failed"), SimpleNamespace(id=1)]
        )
    )
    service = FavoriteNotificationService(
        file_repository=repository,
        message_service=message_service,
        can_view_file=AsyncMock(),
    )
    event = _event(
        action_code=FAVORITE_SOURCE_DELETED,
        snapshots=[
            FavoriteRecipientSnapshot(user_id=11, favorite_space_id=101),
            FavoriteRecipientSnapshot(user_id=12, favorite_space_id=102),
        ],
    )

    assert await service.consume([event]) == 1
    assert message_service.send_generic_notify.await_count == 2


async def test_consumer_ignores_cross_tenant_source_and_references():
    repository = SimpleNamespace(
        find_favorite_referrers_by_source_file_ids=AsyncMock(
            return_value=[
                _reference(11, 101, tenant_id=1),
                _reference(12, 102, tenant_id=2),
            ]
        ),
        find_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=20,
                    knowledge_id=10,
                    tenant_id=1,
                    deleted_at=None,
                )
            ]
        ),
    )
    message_service = SimpleNamespace(send_generic_notify=AsyncMock())
    service = FavoriteNotificationService(
        file_repository=repository,
        message_service=message_service,
        can_view_file=AsyncMock(return_value=True),
    )

    assert await service.consume([_event()]) == 1
    assert message_service.send_generic_notify.await_args.kwargs[
        "receiver_user_ids"
    ] == [11]

    repository.find_by_ids.return_value = [
        SimpleNamespace(
            id=20,
            knowledge_id=10,
            tenant_id=2,
            deleted_at=None,
        )
    ]
    message_service.send_generic_notify.reset_mock()

    assert await service.consume([_event()]) == 0
    message_service.send_generic_notify.assert_not_awaited()
