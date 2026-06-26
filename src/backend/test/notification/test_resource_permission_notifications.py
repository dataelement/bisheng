from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_admin_grant_notifies_despite_openfga_read_after_write_lag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the post-grant ``can_manage`` snapshot must read with strong
    consistency.

    OpenFGA checks default to ``MINIMIZE_LATENCY`` (eventually consistent), so a
    snapshot taken ~80ms after the grant write returns the *stale* pre-grant
    ``False``. The assignment notification only fires on a ``False -> True``
    transition, so the stale read silently suppressed the in-site message for
    every admin/owner grant. The after-snapshot now requests HIGHER_CONSISTENCY.
    """
    message_service = _FakeMessageService()
    seen_consistency: list[str | None] = []

    async def _affected_user_ids_for_subject(
        _cls,
        subject_type: str,
        subject_id: int,
        include_children: bool = True,
    ) -> set[int]:
        return {subject_id}

    async def _can_manage(*, user_id: int, resource_type: str, resource_id: str, consistency=None) -> bool:
        seen_consistency.append(consistency)
        # Model OpenFGA read-after-write lag: the freshly written manager tuple is
        # only visible under HIGHER_CONSISTENCY; a default (stale) read still sees
        # the pre-grant state where the user could not manage.
        return consistency == "HIGHER_CONSISTENCY"

    async def _can_read(**_kwargs) -> bool:
        return False

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
        resource_id=33,
        grants=[
            SimpleNamespace(
                relation="manager",
                subject_type="user",
                subject_id=6,
                include_children=False,
            )
        ],
        revokes=[],
    )

    await ResourcePermissionNotificationService.dispatch_after_authorize(
        context=context,
        operator_user_id=1,
        operator_user_name="owner",
    )

    # The before-snapshot tolerates the default (stale) read; the after-snapshot
    # must force HIGHER_CONSISTENCY so the just-written grant is observed.
    assert "HIGHER_CONSISTENCY" in seen_consistency
    assert len(message_service.calls) == 1
    call = message_service.calls[0]
    assert call["receiver_user_ids"] == [6]
    assert call["action_code"] == "assigned_knowledge_space_admin"
