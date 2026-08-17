"""T050 — the five state actions: prior-state matrix, concurrency, assets, audit.

Every test here drives ``AppStateService`` against the in-memory database and
the programmable orchestrator stub. Nothing asserts on SQL; what is asserted is
the pair (resulting state, orchestration intent issued) — because that pair is
the contract F055, the卡片 switch and the runtime all read.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import AppAuditAction, AppState
from bisheng.common.errcode.app_factory import (
    AppManageForbiddenError,
    AppNotFoundError,
    AppOnlineCannotDeleteError,
    AppOwnerOnlyError,
    AppStateConflictError,
)

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator", "fake_permission_projection")

ALL_STATES = (
    AppState.DRAFT.value,
    AppState.ONLINE.value,
    AppState.PENDING_CAPACITY.value,
    AppState.STOPPED.value,
    AppState.DELETED.value,
)


async def _state(app_db, app_id) -> str | None:
    from bisheng.database.models.app import AppDao

    async with app_db() as session:
        row = await AppDao.aget(session, app_id)
    return None if row is None else row.state


def _super_admin_payload(user_id: int = 90999):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name="f054-super", user_role=[], tenant_id=1, is_global_super=True)


class TestTransitionMatrix:
    @pytest.mark.parametrize("source", ALL_STATES)
    @pytest.mark.parametrize("action", ("publish", "manual_publish", "stop", "resume", "delete"))
    async def test_transition_matrix_full(self, app_db, app_factory, app_owner, source, action):
        """AC-03 — five actions x five prior states, driven end to end.

        The load-bearing cell is ``online`` x ``delete``: it must be refused
        (16104), so that the container and its host volume are always torn down
        by ``stop`` rather than orphaned by a row that changed state.
        """
        from bisheng.app_runtime.domain.constants import ALLOWED_TRANSITIONS
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=source)
        target = AppState.STOPPED if action == "stop" else AppState.DELETED if action == "delete" else AppState.ONLINE
        legal = target in ALLOWED_TRANSITIONS[AppState(source)]

        method = getattr(AppStateService, action)
        if source == AppState.DELETED.value:
            # A deleted app answers "does not exist" to every action — it is a
            # terminal audit record, not an operable object.
            with pytest.raises(AppNotFoundError):
                await method(app.id, actor=app_owner.payload)
            return
        if legal:
            await method(app.id, actor=app_owner.payload)
            assert await _state(app_db, app.id) == target.value
        else:
            expected = (
                AppOnlineCannotDeleteError if (action == "delete" and source == "online") else AppStateConflictError
            )
            with pytest.raises(expected):
                await method(app.id, actor=app_owner.payload)
            assert await _state(app_db, app.id) == source

    async def test_concurrent_actions_second_gets_16102(self, app_db, app_factory, app_owner, monkeypatch):
        """AC-03 — the compare-and-set is the whole concurrency story.

        Simulated by letting the app move underneath an in-flight action, which
        is exactly what a concurrent "stop" during an "publish finalise" does.
        The loser sees zero affected rows and raises 16102 instead of silently
        overwriting the winner.
        """
        from bisheng.app_runtime.domain.services import app_state_service
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.database.models.app import AppDao

        app, _ = await app_factory(state=AppState.ONLINE.value)

        original = AppStateService._transition

        async def _steal_then_transition(app_id, **kwargs):
            async with app_state_service.get_async_db_session() as session:
                await AppDao.aupdate_state_cas(
                    session, app_id, from_states=(AppState.ONLINE.value,), to_state=AppState.STOPPED.value
                )
                await session.commit()
            return await original(app_id, **kwargs)

        monkeypatch.setattr(AppStateService, "_transition", staticmethod(_steal_then_transition))

        with pytest.raises(AppStateConflictError) as excinfo:
            await AppStateService.stop(app.id, actor=app_owner.payload)
        assert excinfo.value.code == 16102


class TestStart:
    async def test_publish_admission_fail_sets_pending_capacity_with_reason(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """AC-19 / AC-65 — a refused capacity gate parks the app; it never starts
        a "half usable" instance and calls it online."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        snapshot = {"mem_available_mb": 700, "committed_mb": 20480, "total_mb": 32768, "cpu": 8}
        fake_orchestrator.responses["admission"] = {"admitted": False, "reason": "mem_available", "snapshot": snapshot}

        app, _version = await app_factory(state=AppState.DRAFT.value)
        result = await AppStateService.publish(app.id, actor=app_owner.payload)

        assert result.ok is False and result.reason == "mem_available"
        assert result.detail["snapshot"] == snapshot, "AC-65 shows the numbers behind the refusal"
        assert await _state(app_db, app.id) == AppState.PENDING_CAPACITY.value
        assert [name for name, _ in fake_orchestrator.calls] == ["admission"], "nothing was started"

    async def test_publish_probe_fail_sets_pending_with_reason(self, app_db, app_factory, app_owner, fake_orchestrator):
        """AC-65 — "上线失败" is a state plus a cause, not a stack trace."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.common.errcode.app_factory import AppProbeFailedError

        fake_orchestrator.responses["deploy"] = AppProbeFailedError(msg="readiness probe never passed")

        app, _ = await app_factory(state=AppState.DRAFT.value)
        result = await AppStateService.publish(app.id, actor=app_owner.payload)

        assert result.ok is False and "readiness" in result.reason
        assert result.detail["stage"] == "deploy"
        assert await _state(app_db, app.id) == AppState.PENDING_CAPACITY.value

    async def test_manual_publish_from_pending_capacity(self, app_db, app_factory, app_owner, fake_orchestrator):
        """AC-65 — retrying a parked app needs no second approval round."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, version = await app_factory(state=AppState.PENDING_CAPACITY.value)
        result = await AppStateService.manual_publish(app.id, actor=app_owner.payload)

        assert result.ok is True and result.version_id == version.id
        assert await _state(app_db, app.id) == AppState.ONLINE.value
        assert [name for name, _ in fake_orchestrator.calls] == ["admission", "deploy"]

    async def test_resume_runs_admission_first_and_keeps_stopped_on_shortage(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """AC-19 / AC-41 — the operator asked for it to run *now*; a shortage
        leaves it stopped rather than moving it to a third state they did not ask for."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        fake_orchestrator.responses["admission"] = {"admitted": False, "reason": "committed_mb", "snapshot": {}}
        app, _ = await app_factory(state=AppState.STOPPED.value)

        result = await AppStateService.resume(app.id, actor=app_owner.payload)

        assert result.ok is False and result.reason == "committed_mb"
        assert result.state == AppState.STOPPED.value
        assert await _state(app_db, app.id) == AppState.STOPPED.value
        assert [name for name, _ in fake_orchestrator.calls] == ["admission"]

    async def test_resume_uses_pending_version(self, app_db, app_factory, app_owner, fake_orchestrator):
        """AC-04 — the version approved while the app was stopped is the one that starts."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

        app, _first = await app_factory(state=AppState.STOPPED.value)
        async with app_db() as session:
            second = AppVersion(
                app_id=app.id,
                version_no=2,
                kind=VERSION_KIND_ITERATION,
                code_object_key="apps/x/v2/code.tar.gz",
                manifest={"port": 8080},
                capabilities={},
                injections={},
                tier_id="standard",
                runtime="python3.11",
            )
            await AppVersionDao.ainsert(session, second)
            await session.commit()
            second_id = second.id

        await AppStateService.stage_version(app.id, second_id)
        result = await AppStateService.resume(app.id, actor=app_owner.payload)

        assert result.version_id == second_id
        from bisheng.database.models.app import AppDao

        async with app_db() as session:
            row = await AppDao.aget(session, app.id)
        assert row.current_version_id == second_id
        assert row.pending_version_id is None, "a version that started is no longer pending"

    async def test_start_marks_version_terminal_online(self, app_db, app_factory, app_owner):
        """AC-04 — the version that took effect carries the ``online`` outcome."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService
        from bisheng.database.models.app_version import AppVersionDao

        app, version = await app_factory(state=AppState.DRAFT.value)
        await AppStateService.publish(app.id, actor=app_owner.payload)

        async with app_db() as session:
            row = await AppVersionDao.aget(session, app.id, version.id)
        assert row.terminal_state == "online"


class TestStopAndPermissions:
    async def test_stop_recycles_exec_body_only_assets_intact(self, app_db, app_factory, app_owner, fake_orchestrator):
        """AC-39 / AC-40 — stopping reclaims the execution body and nothing else."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        await AppStateService.stop(app.id, actor=app_owner.payload)

        issued = [name for name, _ in fake_orchestrator.calls]
        assert issued == ["stop"]
        assert "destroy" not in issued, "code snapshot / per-app database / attachments survive a stop"

    async def test_no_path_deletes_assets_except_explicit_delete(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """AC-40 — stop, a parked start and a failed start all leave the data alone.

        Only the owner's explicit delete ever sends ``purge_volume=True``.
        """
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        online, _ = await app_factory(state=AppState.ONLINE.value)
        await AppStateService.stop(online.id, actor=app_owner.payload)

        fake_orchestrator.responses["admission"] = {"admitted": False, "reason": "mem_available", "snapshot": {}}
        parked, _ = await app_factory(state=AppState.DRAFT.value)
        await AppStateService.publish(parked.id, actor=app_owner.payload)

        assert all(name != "destroy" for name, _ in fake_orchestrator.calls)

    @pytest.mark.parametrize("who", ("owner", "tenant_admin", "super_admin"))
    async def test_stop_resume_allowed_for_owner_tenant_admin_and_superadmin_proxy(
        self, app_db, app_factory, app_owner, tenant_admins, audit_sink, who
    ):
        """AC-41 — three principals may operate; the audit always names the human
        who pressed the button, never the app's owner."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        if who == "owner":
            actor = app_owner.payload
        elif who == "tenant_admin":
            actor = _super_admin_payload(90888)
            actor.is_global_super = False
            tenant_admins.grant(actor.user_id, app.tenant_id)
        else:
            actor = _super_admin_payload()

        await AppStateService.stop(app.id, actor=actor)

        assert await _state(app_db, app.id) == AppState.STOPPED.value
        stop_rows = [row for row in audit_sink if row["action"] == AppAuditAction.STOP.value]
        assert stop_rows and stop_rows[-1]["operator_id"] == actor.user_id

    async def test_stop_rejected_for_unrelated_user(self, app_db, app_factory, normal_user, tenant_admins):
        """Neither owner nor administrator — a business pre-check, refused before
        the permission runtime gets a chance to short-circuit an admin to ALLOW."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        with pytest.raises(AppManageForbiddenError) as excinfo:
            await AppStateService.stop(app.id, actor=normal_user.payload)
        assert excinfo.value.code == 16106, "16105 means owner-*only*; this action also admits administrators"


class TestDelete:
    async def test_delete_blocked_when_online_16104(self, app_db, app_factory, app_owner):
        """AC-42 — "stop it first"; a running app is never deleted out from under itself."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        with pytest.raises(AppOnlineCannotDeleteError) as excinfo:
            await AppStateService.delete(app.id, actor=app_owner.payload)
        assert excinfo.value.code == 16104
        assert await _state(app_db, app.id) == AppState.ONLINE.value

    @pytest.mark.parametrize("source", (AppState.DRAFT.value, AppState.PENDING_CAPACITY.value, AppState.STOPPED.value))
    async def test_delete_allowed_from_draft_pending_stopped(self, app_db, app_factory, app_owner, source):
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=source)
        await AppStateService.delete(app.id, actor=app_owner.payload)
        assert await _state(app_db, app.id) == AppState.DELETED.value

    @pytest.mark.parametrize("who", ("tenant_admin", "super_admin"))
    async def test_delete_rejected_for_non_owner_16105(self, app_db, app_factory, tenant_admins, who):
        """AC-44 — owner only, and that includes the tenant administrator and the
        platform super admin. Expressing this through F048 is impossible: both
        are short-circuited to ALLOW there."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.STOPPED.value)
        actor = _super_admin_payload()
        if who == "tenant_admin":
            actor.is_global_super = False
            tenant_admins.grant(actor.user_id, app.tenant_id)

        with pytest.raises(AppOwnerOnlyError) as excinfo:
            await AppStateService.delete(app.id, actor=actor)
        assert excinfo.value.code == 16105
        assert await _state(app_db, app.id) == AppState.STOPPED.value

    async def test_delete_purges_assets_and_marks_deleted(
        self, app_db, app_factory, app_owner, fake_orchestrator, fake_permission_projection
    ):
        """AC-43 — the one path that destroys data, and it also retires the grants."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, _ = await app_factory(state=AppState.STOPPED.value)
        await AppStateService.delete(app.id, actor=app_owner.payload)

        destroy_calls = [kwargs for name, kwargs in fake_orchestrator.calls if name == "destroy"]
        assert destroy_calls == [{"app_id": app.id, "purge_volume": True}]
        assert await _state(app_db, app.id) == AppState.DELETED.value
        assert "project_delete" in fake_permission_projection.actions()

    async def test_delete_triggers_on_app_deleted_hook(self, app_db, app_factory, app_owner):
        """AC-43 — F055 cancels the in-flight approval through this seam; F054
        never imports F055 (the dependency points the other way)."""
        from bisheng.app_runtime.domain.services import lifecycle_hooks
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        seen = []

        async def _hook(**kwargs):
            seen.append(kwargs)

        lifecycle_hooks.clear_app_deleted_hooks()
        lifecycle_hooks.register_app_deleted_hook(_hook)
        try:
            app, _ = await app_factory(state=AppState.STOPPED.value)
            await AppStateService.delete(app.id, actor=app_owner.payload)
        finally:
            lifecycle_hooks.clear_app_deleted_hooks()

        assert seen == [{"app_id": app.id, "actor_user_id": app_owner.user_id, "tenant_id": app.tenant_id}]

    async def test_hook_failure_does_not_rollback_delete(self, app_db, app_factory, app_owner, audit_sink):
        """The assets are already gone by the time hooks run; rolling the state
        back would manufacture "the app exists but its data does not"."""
        from bisheng.app_runtime.domain.services import lifecycle_hooks
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        async def _bad_hook(**kwargs):
            raise RuntimeError("approval service is down")

        lifecycle_hooks.clear_app_deleted_hooks()
        lifecycle_hooks.register_app_deleted_hook(_bad_hook)
        try:
            app, _ = await app_factory(state=AppState.STOPPED.value)
            await AppStateService.delete(app.id, actor=app_owner.payload)
        finally:
            lifecycle_hooks.clear_app_deleted_hooks()

        assert await _state(app_db, app.id) == AppState.DELETED.value
        actions = [row["action"] for row in audit_sink]
        assert AppAuditAction.DELETE.value in actions
        assert AppAuditAction.DELETE_HOOK_FAILED.value in actions


class TestAudit:
    async def test_every_action_audited_with_version_and_reason(self, app_db, app_factory, app_owner, audit_sink):
        """AC-65 — each action's execution *and* its result are recorded, carrying
        the version it acted on and the reason it ended that way."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, version = await app_factory(state=AppState.DRAFT.value)
        await AppStateService.publish(app.id, actor=app_owner.payload)
        await AppStateService.stop(app.id, actor=app_owner.payload)
        await AppStateService.resume(app.id, actor=app_owner.payload)
        await AppStateService.stop(app.id, actor=app_owner.payload)
        await AppStateService.delete(app.id, actor=app_owner.payload)

        actions = [row["action"] for row in audit_sink]
        assert actions == [
            AppAuditAction.PUBLISH.value,
            AppAuditAction.STOP.value,
            AppAuditAction.RESUME.value,
            AppAuditAction.STOP.value,
            AppAuditAction.DELETE.value,
        ]
        for row in audit_sink:
            assert row["target_type"] == "app" and row["target_id"] == app.id
            assert "version_id" in row["metadata"] and row["metadata"]["reason"]
        assert audit_sink[0]["metadata"]["version_id"] == version.id
