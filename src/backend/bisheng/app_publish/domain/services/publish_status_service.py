"""The publish face's read model, and the manual-publish action (design D15 / AC-32 / AC-38 / AC-62).

:meth:`PublishStatusService.get_publish_status` is **the** implementation of
"what is happening with this application's release". AC-38 asks that the
publish face and F052's MCP status tool answer identically; that is guaranteed
structurally — there is one function — rather than by two implementations
agreeing to stay in step.

Three rules that are easy to get wrong:

* **It never writes.** Everything here is derived. "待上线" in particular is
  computed from ``app.state`` plus the parked attempt's reason, not stored as a
  fourth ``terminal_state``: the version-outcome line and the availability line
  are orthogonal and merging them into one column is how they stop being so.
* **A caller without permission gets 200 plus a business code, never 403/404.**
  The platform SPA's response interceptor navigates the *whole page* to ``/403``
  on either status, so a non-owner opening somebody's application would lose the
  page rather than see "you cannot act on this" (design K11 ② / 坑 22). Business
  errors ride inside the 200 envelope, which is what makes the refusal
  renderable.
* **Owner-only is a business pre-check, not a permission check.** The permission
  runtime short-circuits administrators to ALLOW, so "only the owner may
  withdraw" is inexpressible there — a tenant administrator would pass. Hence
  ``can`` is computed here, and :meth:`request_manual_publish` re-checks rather
  than trusting the flags it handed out.

The read is deliberately tolerant: a missing deployment row, a swept attempt or
a deleted application all produce a payload rather than an error. A publish face
that cannot render *because* something went wrong is the worst possible answer
to "what went wrong".
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.models.app_deployment import ACTIVE_STATUSES, AppDeploymentDao
from bisheng.app_publish.domain.services.app_publish_scenario_handler import SCENARIO_CODE
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalTaskStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.common.errcode.app_publish import AppPublishOwnerOnlyError
from bisheng.common.permission_identity import check_tenant_admin
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao

#: ``pending_reason`` values. ``None`` means the application is not parked.
PENDING_REASON_CAPACITY = "capacity"
PENDING_REASON_DEPLOY_FAILED = "deploy_failed"

_APP_STATE_PENDING_CAPACITY = "pending_capacity"
_APP_STATE_DELETED = "deleted"

#: Approval instance statuses that still hold the application.
_OPEN_INSTANCE_STATUSES = (
    ApprovalInstanceStatus.PENDING,
    ApprovalInstanceStatus.EXCEPTION,
    ApprovalInstanceStatus.EXECUTE_FAILED,
)


class PublishStatusService:
    """One read model and one action; nothing else answers "what is my release doing"."""

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    @classmethod
    async def get_publish_status(cls, app_id: str, *, actor) -> dict[str, Any]:
        """Design §4.2 ② verbatim. Shared by the publish face and F052's MCP tool."""
        app = await cls._load(app_id)
        await cls._require_viewer(app, actor)

        deployment = await cls._latest_deployment(app.id)
        instance = await cls._latest_instance(app)
        approval = await cls._approval_payload(instance)
        current_version = await VersionService.get_version(app.id, str(app.current_version_id or ""))
        pending_version = await VersionService.get_version(app.id, str(app.pending_version_id or ""))

        is_owner = cls._is_owner(app, actor)
        has_open_approval = instance is not None and instance.status in _OPEN_INSTANCE_STATUSES
        deleted = app.state == _APP_STATE_DELETED

        return {
            "app_id": app.id,
            "app_state": app.state,
            "pending_reason": cls._pending_reason(app, deployment),
            "current_version": cls._version_payload(current_version, app),
            "pending_version": cls._version_payload(pending_version, app),
            "deployment": cls._deployment_payload(deployment),
            "approval": approval,
            "tier": await cls._tier_payload(current_version or pending_version),
            # Capability declarations are a deferred wave. The key is present
            # and empty so neither consumer has to change shape when they land.
            "capabilities": [],
            "schema_change": None,
            "can": {
                # Withdrawing goes through the approval centre's own endpoint,
                # which enforces "applicant only" itself; this flag only decides
                # whether the button is drawn.
                "withdraw": bool(is_owner and has_open_approval and not deleted),
                "manual_publish": bool(is_owner and not deleted and app.state == _APP_STATE_PENDING_CAPACITY),
                # AC-06: an application that arrived through the CLI has no
                # draft workspace on the platform, so there is nothing for a
                # "提交发布" button to submit. It is false for the whole of this
                # release, and the front end explains why rather than hiding it.
                "submit": False,
            },
        }

    # ------------------------------------------------------------------
    # action
    # ------------------------------------------------------------------

    @classmethod
    async def runtime_hint(cls, app_id: str) -> dict[str, Any]:
        """Why an application might have no output right now (F053 T034 write-back 2).

        Returned alongside ``bisheng logs`` so the CLI can distinguish the two
        causes of an empty ``lines``: the app is running and quiet, or it has no
        running instance at all (draft, parked, stopped). Printing only "no
        logs" for both reads as a broken log query and sends the owner off to
        check the wrong thing.

        Deliberately **not** access-checked: the caller has already passed the
        log-access check for this very application, and re-checking here with a
        different actor shape is how the two checks drift apart. It is also
        deliberately silent on failure — a hint that cannot be produced must
        never take down the log response it decorates.
        """
        try:
            app = await cls._load(app_id)
            deployment = await cls._latest_deployment(app.id)
            return {"app_state": app.state, "pending_reason": cls._pending_reason(app, deployment)}
        except Exception:  # a decoration must not break the payload it decorates
            logger.exception(f"app_publish.runtime_hint app_id={app_id} could not be resolved")
            return {"app_state": None, "pending_reason": None}

    @classmethod
    async def request_manual_publish(cls, app_id: str, *, actor) -> dict[str, Any]:
        """Retry a parked release (AC-32). Owner-only, no second approval round.

        The owner check is repeated here rather than trusting ``can`` — that
        flag is advice for rendering, and an action that trusted a value it
        handed to the client would be trusting the client.
        """
        app = await cls._load(app_id)
        if not cls._is_owner(app, actor):
            raise AppPublishOwnerOnlyError(
                msg="仅应用负责人可以手动上线",
                details={"app_id": app_id, "action": "manual_publish", "reason": "owner_only"},
                hints=["请联系该应用的负责人操作"],
            )

        from bisheng.app_publish.domain.services.publish_online_service import PublishOnlineService

        outcome = await PublishOnlineService.manual_publish(app_id, actor=actor)
        await write_release_audit(
            AppReleaseAuditAction.MANUAL_PUBLISH,
            deployment=await cls._audit_ref(app),
            version_no=outcome.get("version_no"),
            operator_id=int(getattr(actor, "user_id", 0) or 0),
            metadata={"status": outcome.get("status"), "app_state": outcome.get("app_state")},
        )
        return outcome

    # ------------------------------------------------------------------
    # access
    # ------------------------------------------------------------------

    @staticmethod
    def _is_owner(app, actor) -> bool:
        return int(getattr(actor, "user_id", 0) or 0) == int(app.owner_user_id or 0)

    @classmethod
    async def _require_viewer(cls, app, actor) -> None:
        """Owner, this tenant's administrator, or a platform super admin.

        Refuses with a **business** error so the response is an HTTP 200 the
        front end can render. Raising ``HTTPException(403)`` here would take the
        whole detail page down to ``/403``.
        """
        if cls._is_owner(app, actor) or bool(getattr(actor, "is_global_super", False)):
            return
        user_id = int(getattr(actor, "user_id", 0) or 0)
        if await check_tenant_admin(user_id, int(app.tenant_id or 0)):
            return
        raise AppPublishOwnerOnlyError(
            msg="没有查看该应用发布状态的权限",
            details={"app_id": app.id, "action": "view_publish_status", "reason": "not_visible"},
            hints=["请联系该应用的负责人或平台管理员"],
        )

    @staticmethod
    async def _load(app_id: str):
        """The app row, including a deleted one.

        A deleted application still answers: the publish face has to be able to
        say "this application was deleted, and its release was cancelled"
        instead of rendering an empty page. That is also the read-side defence
        for a deletion hook that never arrived (design D10).
        """
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
        if row is None:
            raise AppPublishOwnerOnlyError(
                msg="应用不存在或无权访问",
                details={"app_id": app_id, "reason": "not_found"},
                hints=["请确认应用是否已被删除"],
            )
        return row

    # ------------------------------------------------------------------
    # projections
    # ------------------------------------------------------------------

    @staticmethod
    async def _latest_deployment(app_id: str):
        async with get_async_db_session() as session:
            rows = await AppDeploymentDao.alist_by_app(session, app_id, limit=1)
        return rows[0] if rows else None

    @classmethod
    async def _latest_instance(cls, app):
        """The open request if there is one; otherwise the last one this app had.

        Falling back to the finished request is what lets the face show a
        rejection reason after the fact — an owner asking "why is my app not
        live" needs the answer to survive the decision.
        """
        instance = await ApprovalInstanceRepository.find_active_instance_by_resource(
            tenant_id=int(app.tenant_id or 0),
            scenario_code=SCENARIO_CODE,
            business_resource_type="app",
            business_resource_id=str(app.id),
        )
        if instance is not None:
            return instance
        return await ApprovalInstanceRepository.find_active_instance_by_resource(
            tenant_id=int(app.tenant_id or 0),
            scenario_code=SCENARIO_CODE,
            business_resource_type="app",
            business_resource_id=str(app.id),
            active_only=False,
        )

    @staticmethod
    async def _approval_payload(instance) -> dict[str, Any] | None:
        if instance is None:
            return None
        tasks = await ApprovalInstanceRepository.list_tasks(instance.id)
        reject_reason = next(
            (task.comment for task in tasks if task.status == ApprovalTaskStatus.REJECTED and task.comment),
            None,
        )
        decided_at = next(
            (task.acted_at for task in tasks if task.acted_at is not None),
            None,
        )
        names: list[str] = []
        for task in tasks:
            name = await _user_name(task.approver_user_id)
            if name and name not in names:
                names.append(name)
        return {
            "instance_id": instance.id,
            "status": instance.status,
            "submitted_at": instance.create_time,
            "decided_at": decided_at,
            # Never truncated: a rejection an owner cannot read in full is a
            # resubmission of the same thing.
            "reject_reason": reject_reason,
            "approver_names": names,
        }

    @staticmethod
    def _deployment_payload(deployment) -> dict[str, Any] | None:
        if deployment is None:
            return None
        return {
            "id": deployment.id,
            "stage": deployment.stage,
            "status": deployment.status,
            "failure": deployment.failure,
        }

    @staticmethod
    def _version_payload(version, app) -> dict[str, Any] | None:
        if version is None:
            return None
        return {
            "version_id": version.id,
            "version_no": version.version_no,
            "kind": version.kind,
            "submitted_at": version.submitted_at,
            "terminal_state": version.terminal_state,
            "is_current": version.id == app.current_version_id,
            "is_pending": version.id == app.pending_version_id,
        }

    @staticmethod
    def _pending_reason(app, deployment) -> str | None:
        """Why the application is parked — capacity, or it would not start.

        Read off the parked attempt's failure tuple rather than re-derived from
        audit rows, which are best-effort. An application that is not parked has
        no reason at all, even if an old attempt left one behind.
        """
        if app.state != _APP_STATE_PENDING_CAPACITY:
            return None
        failure = deployment.failure if deployment is not None else None
        if isinstance(failure, dict):
            reason = (failure.get("details") or {}).get("reason")
            if reason in (PENDING_REASON_CAPACITY, PENDING_REASON_DEPLOY_FAILED):
                return reason
        # The state says parked but no attempt explains it — an app parked by a
        # path outside the pipeline (F054's resume, say). Capacity is the only
        # thing that reaches this state without our involvement.
        return PENDING_REASON_CAPACITY

    @staticmethod
    async def _tier_payload(version) -> dict[str, Any] | None:
        if version is None:
            return None
        from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService

        try:
            tier = await ResourceTierService.resolve_spec(str(version.tier_id or "light"))
        except Exception:
            # A retired or missing tier must not stop the page rendering; the
            # release already picked one and is running under it.
            logger.warning(f"app_publish.status_tier_unresolved tier={getattr(version, 'tier_id', None)}")
            return {"code": version.tier_id, "name": version.tier_id, "cpu_millicores": None, "memory_mb": None}
        return {
            "code": tier.code,
            "name": tier.name,
            "cpu_millicores": tier.cpu_millicores,
            "memory_mb": tier.memory_mb,
            "enabled": tier.enabled,
        }

    @classmethod
    async def _audit_ref(cls, app):
        deployment = await cls._latest_deployment(app.id)
        if deployment is not None:
            return deployment
        from types import SimpleNamespace

        return SimpleNamespace(
            id=None,
            app_id=app.id,
            tenant_id=int(app.tenant_id or 0),
            version_id=app.pending_version_id or app.current_version_id,
            submitted_by_user_id=int(app.owner_user_id or 0),
        )


async def _user_name(user_id: int | None) -> str | None:
    if not user_id:
        return None
    from bisheng.user.domain.models.user import UserDao

    try:
        user = await UserDao.aget_user(int(user_id))
    except Exception:
        logger.warning(f"app_publish.status_user_lookup_failed user_id={user_id}")
        return None
    return user.user_name if user else None


#: Statuses of an attempt that still owns the application — re-exported so the
#: publish face and the CLI agree on "in flight" without importing the model.
IN_FLIGHT_DEPLOYMENT_STATUSES = ACTIVE_STATUSES
