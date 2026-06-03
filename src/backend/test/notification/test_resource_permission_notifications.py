from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.services import resource_permission_notification_service as service_module
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.permission.domain.services.resource_permission_notification_service import (
    ResourcePermissionNotificationService,
)


class _FakeAsyncSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeMessageService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_generic_notify(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id=len(self.calls))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("after_can_read", "expected_count"),
    [(False, 1), (True, 0)],
)
async def test_knowledge_space_viewer_revoke_notifies_when_effective_read_is_lost(
    monkeypatch: pytest.MonkeyPatch,
    after_can_read: bool,
    expected_count: int,
) -> None:
    message_service = _FakeMessageService()
    read_checks = [True, after_can_read]

    async def _affected_user_ids_for_subject(
        _cls,
        subject_type: str,
        subject_id: int,
        include_children: bool = True,
    ) -> set[int]:
        assert subject_type == "user"
        assert include_children is True
        return {subject_id}

    async def _can_manage(**_kwargs) -> bool:
        return False

    async def _can_read(**_kwargs) -> bool:
        return read_checks.pop(0)

    async def _get_resource_name(_resource_type: str, _resource_id: str) -> str:
        return "Space A"

    async def _get_message_service(_session):
        return message_service

    monkeypatch.setattr(
        PermissionService,
        "_affected_user_ids_for_subject",
        classmethod(_affected_user_ids_for_subject),
    )
    monkeypatch.setattr(ResourcePermissionNotificationService, "_can_manage", staticmethod(_can_manage))
    monkeypatch.setattr(ResourcePermissionNotificationService, "_can_read", staticmethod(_can_read))
    monkeypatch.setattr(ResourcePermissionNotificationService, "_get_resource_name", staticmethod(_get_resource_name))
    monkeypatch.setattr(service_module, "get_async_db_session", lambda: _FakeAsyncSessionContext())
    monkeypatch.setattr("bisheng.message.api.dependencies.get_message_service", _get_message_service)

    context = await ResourcePermissionNotificationService.build_context(
        resource_type="knowledge_space",
        resource_id=42,
        grants=[],
        revokes=[
            SimpleNamespace(
                relation="viewer",
                subject_type="user",
                subject_id=740,
                include_children=True,
            )
        ],
    )

    await ResourcePermissionNotificationService.dispatch_after_authorize(
        context=context,
        operator_user_id=693,
        operator_user_name="operator",
    )

    assert len(message_service.calls) == expected_count
    if expected_count:
        call = message_service.calls[0]
        assert call["sender"] == 693
        assert call["receiver_user_ids"] == [740]
        assert call["action_code"] == "removed_knowledge_space_member"
        assert call["content_item_list"][1]["content"] == "removed_knowledge_space_member"
