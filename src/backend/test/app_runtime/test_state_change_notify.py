"""F056 T032 — owner is told when an administrator stops / resumes their app.

AC-43: tenant admin (or super admin acting) stop / resume → one station message
to the owner; the owner acting on their own app gets nothing.
AC-45: a failed send never changes the outcome of the state action.

The sender is ``ApprovalNotificationService.notify_users`` (the same channel
F055 uses for its parked-state messages); it is captured here rather than
driven, because what F056 owes is *when* and *to whom* a message goes, not the
inbox row itself.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from bisheng.app_runtime.domain.constants import AppState
from bisheng.app_runtime.domain.services.state_change_notify import (
    ACTION_RESUMED_BY_ADMIN,
    ACTION_STOPPED_BY_ADMIN,
    notify_owner_of_admin_state_change,
)

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator", "fake_permission_projection", "audit_sink")


def _super_admin_payload(user_id: int = 90999):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name="f056-super", user_role=[], tenant_id=1, is_global_super=True)


def _tenant_admin_payload(user_id: int = 90888):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name="f056-tenant-admin", user_role=[], tenant_id=1, is_global_super=False)


@pytest.fixture()
def sent(monkeypatch):
    """Capture ``ApprovalNotificationService.notify_users`` keyword calls.

    ``sent.fail = True`` makes the sender raise, to drive AC-45.
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    box = SimpleNamespace(calls=[], fail=False)

    async def _capture(**kwargs: Any) -> None:
        if box.fail:
            raise RuntimeError("message service is down")
        box.calls.append(kwargs)

    monkeypatch.setattr(ApprovalNotificationService, "notify_users", staticmethod(_capture))
    return box


async def _state(app_db, app_id) -> str | None:
    from bisheng.database.models.app import AppDao

    async with app_db() as session:
        row = await AppDao.aget(session, app_id)
    return None if row is None else row.state


class TestWhoGetsTold:
    async def test_owner_stopping_own_app_sends_nothing(self, app_db, app_factory, app_owner, sent):
        """AC-43 — "owner 本人执行时不发"."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        await AppStateService.stop(app.id, actor=app_owner.payload)
        await AppStateService.resume(app.id, actor=app_owner.payload)

        assert sent.calls == []

    async def test_tenant_admin_stop_sends_one_message_to_owner(
        self, app_db, app_factory, app_owner, tenant_admins, sent
    ):
        """AC-43 — exactly one message, to the owner, naming the app and the actor."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        actor = _tenant_admin_payload()
        tenant_admins.grant(actor.user_id, app.tenant_id)

        result = await AppStateService.stop(app.id, actor=actor)

        assert result.state == AppState.STOPPED.value
        assert len(sent.calls) == 1
        call = sent.calls[0]
        assert call["receiver_user_ids"] == [app_owner.user_id]
        assert call["sender"] == actor.user_id
        assert call["action_code"] == ACTION_STOPPED_BY_ADMIN
        assert call["business_name"] == app.name

    async def test_super_admin_resume_sends_one_message_to_owner(self, app_db, app_factory, app_owner, sent):
        """AC-43 — a super admin acting through the tenant view counts as an administrator."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.STOPPED.value)
        actor = _super_admin_payload()

        result = await AppStateService.resume(app.id, actor=actor)

        assert result.ok is True and result.state == AppState.ONLINE.value
        assert [call["action_code"] for call in sent.calls] == [ACTION_RESUMED_BY_ADMIN]
        assert sent.calls[0]["receiver_user_ids"] == [app_owner.user_id]
        assert sent.calls[0]["sender"] == actor.user_id

    async def test_resume_that_stays_stopped_sends_nothing(self, app_db, app_factory, fake_orchestrator, sent):
        """A resume that lost the capacity gate (AC-41) changed nothing the owner needs to hear about."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        fake_orchestrator.responses["admission"] = {"admitted": False, "reason": "committed_mb", "snapshot": {}}
        app, _ = await app_factory(state=AppState.STOPPED.value)

        result = await AppStateService.resume(app.id, actor=_super_admin_payload())

        assert result.ok is False and result.state == AppState.STOPPED.value
        assert sent.calls == []

    @pytest.mark.parametrize("action", ("publish", "manual_publish"))
    async def test_publish_paths_send_nothing(self, app_db, app_factory, sent, action):
        """决议-11 — publish / manual publish belong to F055's pipeline; a second
        message from here would double what the approval engine already sends."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        source = AppState.DRAFT.value if action == "publish" else AppState.PENDING_CAPACITY.value
        app, _ = await app_factory(state=source)

        result = await getattr(AppStateService, action)(app.id, actor=_super_admin_payload())

        assert result.state == AppState.ONLINE.value
        assert sent.calls == []


class TestSendFailureIsSideEffectFree:
    async def test_stop_completes_when_sender_raises(self, app_db, app_factory, tenant_admins, sent, audit_sink):
        """AC-45 — the stop stands, is audited, and reports success."""
        from bisheng.app_runtime.domain.constants import AppAuditAction
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        actor = _tenant_admin_payload()
        tenant_admins.grant(actor.user_id, app.tenant_id)
        sent.fail = True

        result = await AppStateService.stop(app.id, actor=actor)

        assert result.ok is True and result.state == AppState.STOPPED.value
        assert await _state(app_db, app.id) == AppState.STOPPED.value
        assert [row["action"] for row in audit_sink] == [AppAuditAction.STOP.value]

    async def test_resume_completes_when_sender_raises(self, app_db, app_factory, sent):
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, version = await app_factory(state=AppState.STOPPED.value)
        sent.fail = True

        result = await AppStateService.resume(app.id, actor=_super_admin_payload())

        assert result.ok is True and result.state == AppState.ONLINE.value
        assert result.version_id == version.id
        assert await _state(app_db, app.id) == AppState.ONLINE.value


@pytest.fixture()
def message_sink(app_db, monkeypatch):
    """Let the real ``notify_users → send_generic_notify → send_message`` chain run.

    Only ``InboxMessageRepository.save`` is replaced (precedent:
    ``test/app_publish/test_publish_notification.py``), so ``message_type``,
    ``status`` and the content blocks are produced by production code — the
    ``sent`` fixture above proves *when* a message goes, this proves *what*
    lands in the inbox. ``notify_users`` swallows every exception it meets, so
    each test asserts the sink is non-empty before reading it.
    """
    from bisheng.approval.domain.services import approval_notification_service
    from bisheng.message.api import dependencies as message_dependencies
    from bisheng.message.domain.services.message_service import MessageService

    saved: list = []

    class _RecordingRepository:
        async def save(self, message):
            message.id = len(saved) + 1
            saved.append(message)
            return message

    service = MessageService(message_repository=_RecordingRepository(), message_read_repository=None)

    async def _get_message_service(session=None):
        return service

    # The approval service binds ``get_async_db_session`` by name at import
    # time and is not in the app_runtime conftest's patch list.
    monkeypatch.setattr(approval_notification_service, "get_async_db_session", app_db)
    monkeypatch.setattr(message_dependencies, "get_message_service", _get_message_service)
    return saved


class TestMessageShape:
    """What the owner's inbox row is: a NOTIFY statement, never something to approve.

    The client shows an 同意/驳回 pair whenever ``message_type`` is ``request``
    or ``approve`` regardless of action code, so the guarantee has to hold on
    the sending side and on the real path, not on the mocked one.
    """

    @pytest.mark.parametrize(
        ("source_state", "method", "expected_code"),
        [
            (AppState.ONLINE.value, "stop", ACTION_STOPPED_BY_ADMIN),
            (AppState.STOPPED.value, "resume", ACTION_RESUMED_BY_ADMIN),
        ],
    )
    async def test_lands_as_a_neutral_notify_statement(
        self, app_db, app_factory, app_owner, tenant_admins, message_sink, source_state, method, expected_code
    ):
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum

        app, _ = await app_factory(state=source_state)
        actor = _tenant_admin_payload()
        tenant_admins.grant(actor.user_id, app.tenant_id)

        result = await getattr(AppStateService, method)(app.id, actor=actor)

        assert result.ok is True
        assert len(message_sink) == 1, "the notification never reached the message service"
        message = message_sink[0]
        assert message.message_type == MessageTypeEnum.NOTIFY
        assert message.message_type != MessageTypeEnum.APPROVE
        assert message.status == MessageStatusEnum.APPROVED
        assert message.action_code == expected_code
        assert message.sender == actor.user_id
        assert list(message.receiver) == [app_owner.user_id]

        content = message.content
        assert content
        types = [str(block.get("type")) for block in content]
        # The action code rides in ``system_text`` (that is what the client maps
        # to copy) and the app name is the ``{{target}}`` it interpolates.
        assert "system_text" in types
        assert next(b for b in content if b.get("type") == "system_text")["content"] == expected_code
        assert any(str(b.get("content") or "").lstrip("-—").strip() == app.name for b in content)
        assert "agree_reject_button" not in types
        for block in content:
            metadata = block.get("metadata") or {}
            assert "button_action_code" not in metadata
            assert "action_code" not in metadata, "an action code inside metadata is what renders a button"


class TestHookContract:
    async def test_unknown_action_is_refused_without_sending(self, sent):
        app = SimpleNamespace(id="app-x", name="X", owner_user_id=1)
        actor = SimpleNamespace(user_id=2)

        assert await notify_owner_of_admin_state_change(app=app, actor=actor, action="delete") is False
        assert sent.calls == []

    async def test_missing_owner_sends_nothing(self, sent):
        app = SimpleNamespace(id="app-x", name="X", owner_user_id=None)
        actor = SimpleNamespace(user_id=2)

        assert await notify_owner_of_admin_state_change(app=app, actor=actor, action="stop") is False
        assert sent.calls == []

    async def test_returns_true_only_when_handed_to_sender(self, sent):
        app = SimpleNamespace(id="app-x", name="X", owner_user_id=1)
        actor = SimpleNamespace(user_id=2)

        assert await notify_owner_of_admin_state_change(app=app, actor=actor, action="stop") is True
        sent.fail = True
        assert await notify_owner_of_admin_state_change(app=app, actor=actor, action="resume") is False
        assert [call["action_code"] for call in sent.calls] == [ACTION_STOPPED_BY_ADMIN]
