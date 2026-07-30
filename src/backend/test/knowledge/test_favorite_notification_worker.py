# ruff: noqa: E402
import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.schemas.favorite_notification_schema import (
    FavoriteChangeEvent,
    FavoriteRecipientSnapshot,
)
from bisheng.knowledge.domain.services import favorite_notify
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessStatus,
)
from bisheng.knowledge.domain.services.favorite_notify import (
    FAVORITE_SOURCE_DELETED,
    FAVORITE_SOURCE_RENAMED,
    FavoriteNotificationService,
)

_BACKEND = Path(__file__).resolve().parents[2]
sys.modules["bisheng.worker"].__path__ = [str(_BACKEND / "bisheng/worker")]
sys.modules["bisheng.worker.knowledge"].__path__ = [
    str(_BACKEND / "bisheng/worker/knowledge")
]
worker_module = importlib.import_module("bisheng.worker.knowledge.favorite_notification")


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


@pytest.mark.parametrize(
    (
        "space_level",
        "user_deleted",
        "expected_sent",
        "expected_permission_calls",
    ),
    [
        (KnowledgeSpaceLevelEnum.PUBLIC, 0, 1, 0),
        (KnowledgeSpaceLevelEnum.TEAM, 0, 0, 1),
        (KnowledgeSpaceLevelEnum.PUBLIC, 1, 0, 0),
    ],
)
async def test_worker_permission_matches_public_space_visibility(
    space_level,
    user_deleted,
    expected_sent,
    expected_permission_calls,
):
    source_file = SimpleNamespace(
        id=20,
        knowledge_id=10,
        tenant_id=1,
        deleted_at=None,
    )
    access_service = SimpleNamespace(
        evaluate_file=AsyncMock(
            return_value=SimpleNamespace(
                status=DepartmentFileAccessStatus.NOT_APPLICABLE
            )
        )
    )
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=object())
    session_context.__aexit__ = AsyncMock(return_value=None)

    class CapturingNotificationService:
        def __init__(self, *, can_view_file, **_kwargs):
            self.can_view_file = can_view_file

        async def consume(self, _events):
            return int(await self.can_view_file(11, source_file))

    with (
        patch.object(
            worker_module,
            "get_async_db_session",
            return_value=session_context,
        ),
        patch.object(worker_module, "KnowledgeFileRepositoryImpl"),
        patch.object(worker_module, "DepartmentFileViewGrantRepositoryImpl"),
        patch.object(
            worker_module,
            "DepartmentFileViewAccessService",
            return_value=access_service,
        ),
        patch(
            "bisheng.message.api.dependencies.get_message_service",
            new=AsyncMock(return_value=object()),
        ),
        patch.object(
            worker_module,
            "FavoriteNotificationService",
            CapturingNotificationService,
        ),
        patch.object(
            favorite_notify.UserDao,
            "aget_user",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    user_id=11,
                    user_name="收藏者",
                    delete=user_deleted,
                )
            ),
        ),
        patch.object(
            favorite_notify.UserRoleDao,
            "aget_user_roles",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            favorite_notify.PermissionService,
            "check",
            new=AsyncMock(return_value=False),
        ) as permission_check,
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope."
            "KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    tenant_id=1,
                    level=space_level,
                )
            ),
        ),
    ):
        sent = await worker_module._consume_async(
            [_event().model_dump(mode="json")]
        )

    assert sent == expected_sent
    assert permission_check.await_count == expected_permission_calls
