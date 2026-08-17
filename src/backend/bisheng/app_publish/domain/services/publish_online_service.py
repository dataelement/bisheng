"""Bringing an approved version online, and the retry after it parked (design D9 / AC-31 / AC-32 / AC-36).

Two entry points over one body:

* :meth:`PublishOnlineService.bring_online` — the approval outbox's ``on_approved``.
* :meth:`PublishOnlineService.manual_publish` — the owner pressing "手动上线"
  after the app parked. **No second approval round**: the decision already
  exists, what failed was the machine.

They share ``_settle`` because the interesting part is identical — what does a
start attempt mean, and what does the version record say afterwards — and two
copies of that would answer "did it go online" differently the first time
either side changed.

**The return-vs-raise boundary is the whole reason this file is careful.** The
approval outbox judges success purely by "did the callback raise": a normal
return marks the instance ``executed``, an exception marks it ``execute_failed``,
files an exception record and pages the administrators. But "待上线" — approved,
did not start — is a *product terminal state* (AC-31): the approval stands, the
app has a state, the owner has a button. Raising there would tell everybody the
approval failed.

The rule, in one sentence: **will the application get better on its own or with
one human click? then return. Is something actually broken? then raise.**

* return — capacity refused the start; the start or probe failed; the app was
  deleted while the request was in flight; the app is stopped so the version is
  only staged.
* raise — the orchestrator is unreachable, the version record is missing, the
  state machine refuses the transition. Those need an administrator, and the
  outbox's exception record is exactly how one is summoned.

F055 never writes ``app.state``. Every transition goes through F054's
``AppStateService``, which is the single writer (决议-8) and the only place the
compare-and-set against a concurrent stop lives.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.models.app_deployment import (
    STAGE_ONLINE,
    STAGE_PENDING_ONLINE,
    STATUS_SUCCEEDED,
    AppDeploymentDao,
)
from bisheng.app_publish.domain.services import publish_notification_service
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.common.errcode.app_publish import (
    AppCapacityInsufficientError,
    AppStartupProbeFailedError,
    AppVersionNotFoundError,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao
from bisheng.database.models.app_version import TERMINAL_STATE_ONLINE

#: Outcomes of one start attempt. Returned to the outbox as ``{"status": ...}``
#: so the approval-handler audit trail records *which* branch was taken rather
#: than only "it returned".
STATUS_ONLINE = "online"
STATUS_PENDING_CAPACITY = "pending_capacity"
STATUS_PENDING_DEPLOY_FAILED = "pending_deploy_failed"
STATUS_STAGED_ONLY = "staged_only"
STATUS_APP_DELETED = "app_deleted"

#: ``ActionResult.detail["stage"]`` values F054 sets when it parks an app. This
#: is the only discriminator between "no room" and "it crashed", and the two
#: need different copy and a different action code.
_STAGE_ADMISSION = "admission"

#: Codes carried by a parked release's failure tuple. Referenced from the
#: error classes rather than written as literals so the "one code, one meaning"
#: split (16226 = no capacity, 16225 = scenario not seeded) cannot drift here.
CODE_CAPACITY_INSUFFICIENT = AppCapacityInsufficientError.Code
CODE_STARTUP_PROBE_FAILED = AppStartupProbeFailedError.Code

_APP_STATE_STOPPED = "stopped"
_APP_STATE_DELETED = "deleted"


class PublishOnlineService:
    """Approved → running, and everything that happens when it does not get there."""

    # ------------------------------------------------------------------
    # entry points
    # ------------------------------------------------------------------

    @classmethod
    async def bring_online(cls, instance_id: int, payload_snapshot: dict) -> dict[str, Any]:
        """The approval outbox's business execution (AC-31 / AC-36).

        Order: load → stage → dispatch on the application state. Staging first
        matters — ``pending_version_id`` is what makes "approved while stopped,
        takes effect on resume" (AC-36) true without a sixth application state,
        so it is written even on the branch that deliberately does not start
        anything.
        """
        app_id = str(payload_snapshot.get("app_id") or "")
        version_id = str(payload_snapshot.get("version_id") or "")

        app = await cls._load_app(app_id)
        if app is None:
            # The application was deleted while the request was in flight.
            # Deleting cancels the request, so this is the losing side of a
            # race, not an error: return and let the outbox mark it executed.
            logger.info(f"app_publish.on_approved app_id={app_id} vanished; treating as cancelled")
            return {"status": STATUS_APP_DELETED, "app_id": app_id}

        version = await VersionService.get_version(app_id, version_id)
        if version is None:
            # A missing version record is a broken system, not a product state:
            # there is nothing to publish now or later.
            raise AppVersionNotFoundError(
                msg="版本记录不存在, 无法上线",
                details={"app_id": app_id, "version_id": version_id},
                hints=["请重新执行 bisheng deploy 提交一次发布"],
            )

        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        await AppStateService.stage_version(app_id, version_id)

        if app.state == _APP_STATE_STOPPED:
            # AC-36: approval landing on a stopped application records the
            # version and stops. Auto-restarting an app somebody deliberately
            # stopped would undo an operator action nobody asked us to undo;
            # ``resume`` picks ``pending_version_id`` up later.
            await write_release_audit(
                AppReleaseAuditAction.APPROVED,
                deployment=await cls._deployment_ref(payload_snapshot, app),
                version_no=version.version_no,
                operator_id=int(app.owner_user_id or 0),
                metadata={"status": STATUS_STAGED_ONLY, "app_state": app.state},
            )
            return {"status": STATUS_STAGED_ONLY, "app_id": app_id, "version_id": version_id}

        return await cls._settle(
            app,
            version,
            payload_snapshot,
            action=AppStateService.publish,
            audit_action=AppReleaseAuditAction.APPROVED,
            instance_id=instance_id,
        )

    @classmethod
    async def manual_publish(cls, app_id: str, *, actor) -> dict[str, Any]:
        """Retry a parked application (AC-32). Owner-only, checked by the caller.

        No new approval request and **no new version record** — the same version
        simply gets another attempt, and a success latches ``terminal_state``
        exactly as the automatic path would (决议-6).
        """
        app = await cls._load_app(app_id)
        if app is None:
            raise AppVersionNotFoundError(
                msg="应用不存在或已删除",
                details={"app_id": app_id, "reason": "app_missing"},
                hints=["请刷新页面确认应用是否已被删除"],
            )
        version_id = app.pending_version_id or app.current_version_id
        version = await VersionService.get_version(app_id, str(version_id or ""))
        if version is None:
            raise AppVersionNotFoundError(
                msg="该应用没有可上线的版本",
                details={"app_id": app_id, "version_id": version_id},
                hints=["请先通过 bisheng deploy 提交一个版本并完成审批"],
            )

        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        payload = {
            "app_id": app_id,
            "version_id": version.id,
            "version_no": version.version_no,
            "owner_user_id": app.owner_user_id,
            "app_name": app.name,
        }
        return await cls._settle(
            app,
            version,
            payload,
            action=AppStateService.manual_publish,
            audit_action=AppReleaseAuditAction.MANUAL_PUBLISH,
            instance_id=None,
            actor=actor,
        )

    # ------------------------------------------------------------------
    # the shared body
    # ------------------------------------------------------------------

    @classmethod
    async def _settle(
        cls,
        app,
        version,
        payload_snapshot: dict,
        *,
        action,
        audit_action: AppReleaseAuditAction,
        instance_id: int | None,
        actor=None,
    ) -> dict[str, Any]:
        """Run one start attempt and record whichever of the three outcomes happened.

        ``action`` is F054's ``publish`` or ``manual_publish``. Both answer with
        an ``ActionResult`` whose ``ok=False`` means "handled, and here is why"
        rather than "error" — a distinction this method exists to preserve all
        the way to the publish face. Anything that *raises* out of them is a
        system failure and is deliberately not caught.
        """
        deployment = await cls._deployment_ref(payload_snapshot, app)
        result = await action(app.id, actor=actor if actor is not None else cls._owner_actor(app))

        if result.ok:
            # The one authorised UPDATE of app_version, and the only place a
            # release becomes "online" in the version list.
            await VersionService.mark_terminal_state(app.id, version.id, TERMINAL_STATE_ONLINE)
            await cls._advance_deployment(deployment, stage=STAGE_ONLINE)
            await write_release_audit(
                AppReleaseAuditAction.ONLINE,
                deployment=deployment,
                version_no=version.version_no,
                operator_id=int(app.owner_user_id or 0),
                metadata={"status": STATUS_ONLINE, "trigger": str(audit_action), "app_state": result.state},
            )
            logger.info(f"app_publish.online app_id={app.id} version_id={version.id} state={result.state}")
            return {"status": STATUS_ONLINE, "app_id": app.id, "version_id": version.id, "app_state": result.state}

        # Parked. terminal_state stays NULL on purpose: "待上线" is derived from
        # app.state + app.pending_version_id, not stored as a fourth outcome —
        # the version-outcome line and the availability line stay orthogonal.
        reason_kind = "capacity" if cls._is_capacity(result) else "deploy_failed"
        status = STATUS_PENDING_CAPACITY if reason_kind == "capacity" else STATUS_PENDING_DEPLOY_FAILED
        await cls._advance_deployment(
            deployment,
            stage=STAGE_PENDING_ONLINE,
            failure=cls._parked_failure(reason_kind, result),
        )
        await write_release_audit(
            AppReleaseAuditAction.PENDING_ONLINE,
            deployment=deployment,
            version_no=version.version_no,
            operator_id=int(app.owner_user_id or 0),
            reason=result.reason,
            metadata={
                "status": status,
                "reason_kind": reason_kind,
                "app_state": result.state,
                "detail": result.detail,
            },
        )
        await publish_notification_service.notify_pending_online(
            tenant_id=int(app.tenant_id or 0),
            owner_user_id=int(app.owner_user_id or 0),
            business_name=str(payload_snapshot.get("app_name") or app.name),
            instance_id=int(instance_id or 0),
            reason_kind=reason_kind,
            reason=result.reason,
        )
        logger.info(
            f"app_publish.pending_online app_id={app.id} version_id={version.id} "
            f"reason_kind={reason_kind} state={result.state}"
        )
        return {
            "status": status,
            "app_id": app.id,
            "version_id": version.id,
            "app_state": result.state,
            "reason": result.reason,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_capacity(result) -> bool:
        """Capacity refused it, as opposed to it having failed to start.

        F054 tags the parking reason in ``detail["stage"]``. Falling back to the
        state name keeps the two apart even if that key ever goes missing —
        guessing "deploy_failed" for a capacity shortage would tell an owner to
        debug code that is fine.
        """
        detail = result.detail if isinstance(result.detail, dict) else {}
        return str(detail.get("stage") or "") == _STAGE_ADMISSION

    @staticmethod
    def _owner_actor(app):
        """Act as the owner.

        F054's operator check passes the owner, a tenant administrator or a
        super admin. Publishing after approval is done *for* the owner, so
        borrowing their identity keeps the audit trail truthful — an
        ``is_global_super`` shortcut would record the platform as the actor and
        would also skip the very check we want exercised.
        """
        return SimpleNamespace(
            user_id=int(app.owner_user_id or 0),
            tenant_id=int(app.tenant_id or 0),
            is_global_super=False,
        )

    @staticmethod
    async def _load_app(app_id: str):
        """The app row, or ``None`` when it is gone or tombstoned."""
        if not app_id:
            return None
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
        if row is None or row.state == _APP_STATE_DELETED:
            return None
        return row

    @staticmethod
    async def _deployment_ref(payload_snapshot: dict, app):
        """The ``app_deployment`` row this release came from, or a stand-in.

        The audit writer reads ``id`` / ``app_id`` / ``tenant_id`` /
        ``version_id`` / ``submitted_by_user_id`` off it. A manual publish has
        no deployment at all, and an old release's row may have been swept, so
        a namespace with the same five attributes keeps the audit family
        complete instead of dropping the event.
        """
        deployment_id = str(payload_snapshot.get("deployment_id") or "")
        if deployment_id:
            async with get_async_db_session() as session:
                row = await AppDeploymentDao.aget(session, deployment_id)
            if row is not None:
                return row
        return SimpleNamespace(
            id=deployment_id or None,
            app_id=app.id,
            tenant_id=int(app.tenant_id or 0),
            version_id=str(payload_snapshot.get("version_id") or ""),
            submitted_by_user_id=int(app.owner_user_id or 0),
            stage=None,
        )

    @staticmethod
    def _parked_failure(reason_kind: str, result) -> dict[str, Any]:
        """The five-tuple explaining a parked release.

        Written even though the attempt is ``succeeded``: the pipeline did
        everything it was asked to, and the owner still needs to know why the
        application is not serving. It is also the only durable record of
        *which* of the two causes it was — the publish face derives
        ``pending_reason`` from ``code`` rather than re-deriving it from audit
        rows, which are best-effort.
        """
        if reason_kind == "capacity":
            return {
                "stage": STAGE_PENDING_ONLINE,
                "code": CODE_CAPACITY_INSUFFICIENT,
                "message": "运行环境容量不足, 应用已进入待上线",
                "details": {"reason": "capacity", "app_reason": result.reason, **_detail_dict(result)},
                "hints": ["等待运行环境释放资源后在发布面点击「手动上线」", "或联系管理员为该环境扩容"],
            }
        return {
            "stage": STAGE_PENDING_ONLINE,
            "code": CODE_STARTUP_PROBE_FAILED,
            "message": "应用启动失败, 已进入待上线",
            "details": {"reason": "deploy_failed", "app_reason": result.reason, **_detail_dict(result)},
            "hints": [
                "查看运行日志定位启动失败原因",
                "修复后可重新执行 bisheng deploy, 或在发布面点击「手动上线」重试",
            ],
        }

    @staticmethod
    async def _advance_deployment(deployment, *, stage: str, failure: dict[str, Any] | None = None) -> None:
        """Move the attempt to its terminal stage. Both outcomes are ``succeeded``.

        "待上线" is a successful *pipeline* outcome — everything the pipeline was
        asked to do happened, and what remains is capacity or a code fix. The
        CLI reads ``stage`` for that distinction, not ``status``.
        """
        if not getattr(deployment, "id", None):
            return
        async with get_async_db_session() as session:
            await AppDeploymentDao.aadvance_stage(
                session, deployment.id, stage=stage, status=STATUS_SUCCEEDED, failure=failure
            )
            await session.commit()


def _detail_dict(result) -> dict[str, Any]:
    detail = result.detail if isinstance(result.detail, dict) else {}
    return {"park_stage": detail.get("stage")}
