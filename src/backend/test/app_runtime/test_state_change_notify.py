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
