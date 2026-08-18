"""The five state actions — the sole writer of ``app.state`` (决议-8).

F055 calls these; it never writes the column itself. That is not a style
preference: approval, capacity admission and the operator's stop button all
race each other, and a single writer with a compare-and-set is the only version
of this that stays correct without row locks.

The shape of every action is the same, and the order matters:

1. load the app and check the **business** rules (owner-only delete, owner  or
   tenant admin or super admin for the rest). These cannot be F048 checks — the
   permission runtime short-circuits administrators to ALLOW, so "owner only"
   is inexpressible there (constitution C4 note).
2. ask capacity **before** claiming the transition. AC-41 wants a resume that
   loses the capacity gate to stay ``stopped``, and it cannot stay ``stopped``
   if we already wrote ``online``.
3. claim the transition with ``AppDao.aupdate_state_cas`` — ``WHERE id = :id
   AND state IN (allowed)``. Zero rows means a concurrent action got there
   first: 16102, not a silent overwrite.
4. issue the orchestration intent, and on a start failure park the app in
   ``pending_capacity`` with the reason instead of leaving a half-usable
   instance running (spec §3).
5. audit — every action, its outcome, the version and the reason (AC-65). The
   audit trail *is* the state history; there is no history table (D8).

Version selection is one rule, in one place: ``pending_version_id ??
current_version_id``. It is what makes "approved while stopped, takes effect on
resume" (AC-04) true without a sixth state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from bisheng.app_runtime.domain.constants import (
    DEFAULT_TIER_ID,
    AppAuditAction,
    AppState,
    allowed_sources,
    default_tier,
    is_transition_allowed,
)
from bisheng.app_runtime.domain.services import lifecycle_hooks
from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client
from bisheng.common.errcode.app_factory import (
    AppCapacityInsufficientError,
    AppManageForbiddenError,
    AppNotFoundError,
    AppOnlineCannotDeleteError,
    AppOwnerOnlyError,
    AppProbeFailedError,
    AppStateConflictError,
)
from bisheng.common.permission_identity import check_tenant_admin
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.database.models.app_instance import PHASE_RUNNING, PHASE_STOPPED, AppInstanceDao
from bisheng.database.models.app_version import TERMINAL_STATE_ONLINE, AppVersion, AppVersionDao
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.domain.services.permission_action_service import PermissionActor

#: Health probe defaults when the manifest declares none. Mirrors
#: runtime-manager's ``HealthIn`` so an omitted block means the same thing on
#: both sides rather than two different "defaults".
_DEFAULT_HEALTH: dict[str, Any] = {"path": "/", "interval": 10, "timeout": 3, "retries": 3, "start_period": 20}


@dataclass(slots=True)
class ActionResult:
    """What an action did, in the words the caller has to show a human.

    ``ok=False`` is a *handled* outcome (parked for capacity, start failed), not
    an exception: the app is in a defined state and the reason is the copy the
    detail page and the CLI both render (AC-65).
    """

    app_id: str
    state: str
    ok: bool = True
    reason: str = ""
    version_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class AppStateService:
    """Five actions plus ``stage_version``. Nothing else writes ``app.state``."""

    # ------------------------------------------------------------------
    # version staging & selection
    # ------------------------------------------------------------------

    @classmethod
    async def stage_version(cls, app_id: str, version_id: str) -> None:
        """Record an approved-but-not-yet-running version (AC-04).

        Called by F055 the moment approval passes. It writes
        ``app.pending_version_id`` and **leaves the state alone** — that is the
        whole point: a stopped app that gets a new version approved stays
        stopped until somebody resumes it, and then starts the new one.

        Written through the same compare-and-set as a real transition (target
        state = current state) so a concurrent stop cannot be papered over by a
        blind UPDATE.
        """
        app = await cls._load(app_id)
        async with get_async_db_session() as session:
            won = await AppDao.aupdate_state_cas(
                session,
                app_id,
                from_states=(app.state,),
                to_state=app.state,
                pending_version_id=version_id,
            )
            await session.commit()
        if not won:
            raise AppStateConflictError(msg="应用状态已变化, 请刷新后重试", app_id=app_id, action="stage_version")
        logger.info("app_runtime.stage_version app_id={} version_id={} state={}", app_id, version_id, app.state)

    @staticmethod
    def _pick_version(app: App) -> str | None:
        """``pending_version_id ?? current_version_id`` — the single取版 rule (AC-04)."""
        return app.pending_version_id or app.current_version_id

    # ------------------------------------------------------------------
    # the five actions
    # ------------------------------------------------------------------

    @classmethod
    async def publish(cls, app_id: str, *, actor) -> ActionResult:
        """Go online after approval: capacity gate → start → cut traffic over."""
        return await cls._start(
            app_id,
            actor=actor,
            audit_action=AppAuditAction.PUBLISH,
            shortage_state=AppState.PENDING_CAPACITY,
        )

    @classmethod
    async def manual_publish(cls, app_id: str, *, actor) -> ActionResult:
        """Retry a parked application without a second approval round (F055 AC-32)."""
        return await cls._start(
            app_id,
            actor=actor,
            audit_action=AppAuditAction.MANUAL_PUBLISH,
            shortage_state=AppState.PENDING_CAPACITY,
        )

    @classmethod
    async def resume(cls, app_id: str, *, actor) -> ActionResult:
        """Re-enable a stopped application; capacity is re-checked (AC-41).

        A shortage leaves it ``stopped`` rather than parking it in
        ``pending_capacity``: the operator asked for it to run *now*, and moving
        it to a different state would make the button they pressed look like it
        did something else.
        """
        return await cls._start(
            app_id,
            actor=actor,
            audit_action=AppAuditAction.RESUME,
            shortage_state=None,
        )

    @classmethod
    async def stop(cls, app_id: str, *, actor) -> ActionResult:
        """Reclaim the execution body. Code snapshot, per-app database and
        attachments stay exactly where they are (AC-39 / AC-40)."""
        app = await cls._load(app_id)
        await cls._require_operator(app, actor)
        if not is_transition_allowed(app.state, AppState.STOPPED.value):
            raise AppStateConflictError(msg="当前状态不支持停运", app_id=app_id, state=app.state)

        won = await cls._transition(app_id, to_state=AppState.STOPPED, from_states=(app.state,))
        if not won:
            raise AppStateConflictError(msg="应用状态已变化, 请刷新后重试", app_id=app_id, action="stop")

        await orchestrator_client.stop(app_id=app_id)
        await cls._set_instance_phase(app_id, PHASE_STOPPED, tenant_id=app.tenant_id)
        await cls._audit(AppAuditAction.STOP, app, actor, version_id=app.current_version_id, reason="stopped by user")
        return ActionResult(app_id=app_id, state=AppState.STOPPED.value, version_id=app.current_version_id)

    @classmethod
    async def delete(cls, app_id: str, *, actor) -> ActionResult:
        """Explicit deletion — the **only** path that destroys an app's data (AC-40).

        Owner-only (AC-44) and blocked while online (AC-42): stopping first is
        what guarantees the container and its host volume are torn down by a
        state action instead of orphaned by a row that disappeared.
        """
        app = await cls._load(app_id)
        await cls._require_owner(app, actor)
        if app.state == AppState.ONLINE.value:
            raise AppOnlineCannotDeleteError(app_id=app_id)
        if not is_transition_allowed(app.state, AppState.DELETED.value):
            raise AppStateConflictError(msg="当前状态不支持删除", app_id=app_id, state=app.state)

        # Assets first: a row that says "deleted" while the volume survives is
        # invisible garbage; a purged volume with the row still present is a
        # visible, retryable failure.
        await orchestrator_client.destroy(app_id=app_id, purge_volume=True)

        won = await cls._transition(app_id, to_state=AppState.DELETED, from_states=(app.state,))
        if not won:
            raise AppStateConflictError(msg="应用状态已变化, 请刷新后重试", app_id=app_id, action="delete")

        await cls._project_delete(app, actor)
        await cls._audit(
            AppAuditAction.DELETE, app, actor, version_id=app.current_version_id, reason="deleted by owner"
        )

        failures = await lifecycle_hooks.on_app_deleted(
            app_id=app_id,
            actor_user_id=int(getattr(actor, "user_id", 0) or 0),
            tenant_id=int(app.tenant_id or 0),
        )
        for failure in failures:
            await cls._audit(
                AppAuditAction.DELETE_HOOK_FAILED,
                app,
                actor,
                version_id=app.current_version_id,
                reason=str(failure),
            )
        return ActionResult(app_id=app_id, state=AppState.DELETED.value, version_id=app.current_version_id)

    # ------------------------------------------------------------------
    # start pipeline shared by publish / manual_publish / resume
    # ------------------------------------------------------------------

    @classmethod
    async def _start(
        cls,
        app_id: str,
        *,
        actor,
        audit_action: AppAuditAction,
        shortage_state: AppState | None,
    ) -> ActionResult:
        app = await cls._load(app_id)
        await cls._require_operator(app, actor)
        if not is_transition_allowed(app.state, AppState.ONLINE.value):
            raise AppStateConflictError(msg="当前状态不支持该操作", app_id=app_id, state=app.state)

        version_id = cls._pick_version(app)
        version = await cls._load_version(app_id, version_id)
        tier = await cls._resolve_tier(version.tier_id)

        verdict = await orchestrator_client.admission(tier=tier, purpose="run")
        if not verdict.get("admitted"):
            return await cls._park(
                app,
                actor,
                version_id=version.id,
                shortage_state=shortage_state,
                reason=str(verdict.get("reason") or "capacity_exhausted"),
                detail={"snapshot": verdict.get("snapshot") or {}, "stage": "admission"},
            )

        try:
            deployed = await orchestrator_client.deploy(**cls._deploy_payload(app, version, tier))
        except (AppProbeFailedError, AppCapacityInsufficientError) as exc:
            # Deliberately *before* the state is claimed: an app that never
            # started must not spend a moment advertising an entry URL that
            # answers 502, and parking from the source state keeps the whole
            # attempt inside the legal transition table.
            logger.warning("app_runtime.start failed app_id={} version={} err={}", app_id, version.id, exc)
            return await cls._park(
                app,
                actor,
                version_id=version.id,
                shortage_state=shortage_state,
                reason=str(exc),
                detail={"stage": "deploy", "code": getattr(exc, "code", None)},
            )

        won = await cls._transition(
            app_id,
            to_state=AppState.ONLINE,
            from_states=(app.state,),
            current_version_id=version.id,
            pending_version_id=None,
        )
        if not won:
            raise AppStateConflictError(msg="应用状态已变化, 请刷新后重试", app_id=app_id, action=audit_action.value)

        await _mark_version_online(app_id, version.id)
        # Going online does NOT grant anyone else access: an app stays owner-only
        # until its owner or an admin authorizes subjects through the platform's
        # permission-management UI (the F048 授权 dialog). Auto-opening every
        # published app to the whole tenant was a shortcut that bypassed that
        # explicit authorization step, so it was removed on purpose.
        await cls._set_instance_phase(
            app_id,
            str(deployed.get("phase") or PHASE_RUNNING),
            tenant_id=app.tenant_id,
            version_id=version.id,
            exec_ref=deployed.get("instance_id"),
        )
        await cls._audit(audit_action, app, actor, version_id=version.id, reason="started", detail=deployed)
        return ActionResult(
            app_id=app_id,
            state=AppState.ONLINE.value,
            version_id=version.id,
            detail={"phase": deployed.get("phase"), "instance_id": deployed.get("instance_id")},
        )

    @classmethod
    async def _park(
        cls,
        app: App,
        actor,
        *,
        version_id: str | None,
        shortage_state: AppState | None,
        reason: str,
        detail: dict[str, Any],
    ) -> ActionResult:
        """Record "it did not start, and here is why" without leaving anything half-up."""
        target = shortage_state.value if shortage_state is not None else app.state
        if shortage_state is not None and app.state != shortage_state.value:
            await cls._transition(app.id, to_state=shortage_state, from_states=(app.state,))
        await cls._audit(
            AppAuditAction.PUBLISH_PENDING,
            app,
            actor,
            version_id=version_id,
            reason=reason,
            detail=detail,
        )
        return ActionResult(
            app_id=app.id,
            state=target,
            ok=False,
            reason=reason,
            version_id=version_id,
            detail=detail,
        )

    @staticmethod
    def _deploy_payload(app: App, version: AppVersion, tier: dict[str, Any]) -> dict[str, Any]:
        manifest = version.manifest if isinstance(version.manifest, dict) else {}
        injections = version.injections if isinstance(version.injections, dict) else {}
        env = injections.get("env") if isinstance(injections.get("env"), dict) else {}
        health = manifest.get("health") if isinstance(manifest.get("health"), dict) else {}
        return {
            "app_id": app.id,
            "slug": app.slug,
            "version_id": version.id,
            "version_no": version.version_no,
            "image_ref": version.image_ref or "",
            "tier": tier,
            "port": int(manifest.get("port") or 8080),
            "env": {str(key): str(value) for key, value in env.items()},
            "health": {**_DEFAULT_HEALTH, **health},
            "platform_api_base": settings.app_runtime.entry_base_url or "",
            # The proxy strips this prefix and the app's framework re-adds it
            # (D5.2); passing it explicitly keeps the value out of the manager's
            # assumptions about URL layout.
            "base_path": f"/apps/{app.slug}",
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _load(app_id: str) -> App:
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
        if row is None or row.state == AppState.DELETED.value:
            raise AppNotFoundError(app_id=app_id)
        set_current_tenant_id(int(row.tenant_id or 0))
        return row

    @staticmethod
    async def _load_version(app_id: str, version_id: str | None) -> AppVersion:
        """Always scoped by ``app_id``: ``app_version`` has no tenant column, so
        the app row the caller already resolved is what keeps this read inside
        the tenant (design K5 ② / pit 31)."""
        if not version_id:
            raise AppStateConflictError(msg="该应用还没有可运行的版本", app_id=app_id, reason="no_version")
        async with get_async_db_session() as session:
            row = await AppVersionDao.aget(session, app_id, version_id)
        if row is None:
            raise AppStateConflictError(msg="该应用还没有可运行的版本", app_id=app_id, reason="version_missing")
        return row

    @staticmethod
    async def _resolve_tier(tier_id: str | None) -> dict[str, Any]:
        """``{cpu: vCPU float, mem: MiB int}`` — the table wins, the constant backs it up.

        F055 owns the ``resource_tier`` rows and seeds them from
        ``DEFAULT_TIERS``, so "not seeded yet" and "just seeded" resolve to the
        same numbers (design D11). Reading the table directly rather than
        through F055's service keeps the dependency pointing F055 → F054.
        """
        code = tier_id or DEFAULT_TIER_ID
        try:
            from bisheng.database.models.resource_tier import ResourceTierDao

            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    row = await ResourceTierDao.aget_by_code(session, code)
            if row is not None:
                return {"cpu": row.cpu_millicores / 1000, "mem": row.memory_mb}
        except Exception as exc:
            logger.debug("app_runtime.resolve_tier table lookup failed code={}: {}", code, exc)
        spec = default_tier(code) or default_tier(DEFAULT_TIER_ID) or {}
        return {"cpu": float(spec.get("cpu", 1.0)), "mem": int(spec.get("memory_mb", 2048))}

    @staticmethod
    async def _transition(
        app_id: str,
        *,
        to_state: AppState,
        from_states: tuple[str, ...] | None = None,
        current_version_id: Any = ...,
        pending_version_id: Any = ...,
    ) -> bool:
        sources = from_states if from_states is not None else allowed_sources(to_state.value)
        kwargs: dict[str, Any] = {}
        if current_version_id is not ...:
            kwargs["current_version_id"] = current_version_id
        if pending_version_id is not ...:
            kwargs["pending_version_id"] = pending_version_id
        async with get_async_db_session() as session:
            won = await AppDao.aupdate_state_cas(
                session, app_id, from_states=sources, to_state=to_state.value, **kwargs
            )
            await session.commit()
        return won

    @staticmethod
    async def _set_instance_phase(
        app_id: str,
        phase: str,
        *,
        tenant_id: int | None = None,
        version_id: str | None = None,
        exec_ref: str | None = None,
    ) -> None:
        # ``tenant_id`` is passed rather than left to the before_flush auto-fill:
        # that listener only exists in a process that installed the tenant filter,
        # and a NULL here is a NOT NULL violation rather than a silent leak.
        fields: dict[str, Any] = {"phase": phase, "tenant_id": tenant_id}
        if version_id:
            fields["version_id"] = version_id
        if exec_ref:
            fields["exec_ref"] = exec_ref
        if phase == PHASE_RUNNING:
            fields["started_at"] = datetime.now()
        async with get_async_db_session() as session:
            await AppInstanceDao.aupsert(session, app_id, **fields)
            await session.commit()

    @staticmethod
    async def _require_owner(app: App, actor) -> None:
        """Owner-only, checked here rather than in F048.

        The permission runtime allows administrators unconditionally, so
        expressing "only the owner" there is impossible — a tenant admin would
        pass. AC-44 says they must not.
        """
        if int(getattr(actor, "user_id", 0) or 0) != int(app.owner_user_id or 0):
            raise AppOwnerOnlyError(app_id=app.id)

    @staticmethod
    async def _require_operator(app: App, actor) -> None:
        """Owner or this tenant's administrator or platform super admin (AC-41)."""
        user_id = int(getattr(actor, "user_id", 0) or 0)
        if user_id == int(app.owner_user_id or 0):
            return
        if bool(getattr(actor, "is_global_super", False)):
            return
        if await check_tenant_admin(user_id, int(app.tenant_id or 0)):
            return
        raise AppManageForbiddenError(app_id=app.id)

    @staticmethod
    async def _project_delete(app: App, actor) -> None:
        adapter = await get_f048_resource_adapter("app")
        record = await adapter.load_permission_record(app.id)
        if record is None:
            return
        await adapter.project_delete(
            record=record,
            actor=PermissionActor(
                user_id=int(getattr(actor, "user_id", 0) or 0),
                current_tenant_id=int(app.tenant_id or 0),
                super_admin=bool(getattr(actor, "is_global_super", False)),
            ),
        )

    @staticmethod
    async def _audit(
        action: AppAuditAction,
        app: App,
        actor,
        *,
        version_id: str | None = None,
        reason: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        await AuditLogDao.ainsert_v2(
            tenant_id=int(app.tenant_id or 0),
            operator_id=int(getattr(actor, "user_id", 0) or 0),
            operator_tenant_id=int(getattr(actor, "tenant_id", 0) or app.tenant_id or 0),
            operator_name=getattr(actor, "user_name", None),
            action=action.value,
            target_type="app",
            target_id=app.id,
            object_name=app.name,
            reason=reason or None,
            metadata={"version_id": version_id, "state": app.state, "reason": reason, **(detail or {})},
        )


async def _mark_version_online(app_id: str, version_id: str) -> None:
    """Latch the approval outcome of the version that just started (design D8).

    A module function rather than a method so that the "only ``terminal_state``
    is ever updated" rule stays visible next to the single call site.
    """
    async with get_async_db_session() as session:
        await AppVersionDao.amark_terminal(session, app_id, version_id, TERMINAL_STATE_ONLINE)
        await session.commit()
