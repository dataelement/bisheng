"""Submitting a release to the approval centre (design D6 / D7 / K2 / AC-03 / AC-23).

This module **is** the approval port ``VersionService.record_version`` takes:
three module-level coroutines, no class. ``record_version`` owns the "gate
first, INSERT second, compensate explicitly" invariant and receives the port as
a parameter, so the ordering is enforced by the function that owns it rather
than by whoever remembers to call things in the right sequence.

Three things the gate does *not* do, which is why this module exists:

* **It does not refuse a duplicate — it silently returns the existing one.**
  ``find_duplicate_active_instance`` answers a repeat submission with the
  instance already on file, so a second ``bisheng deploy`` would print "提交成功"
  having submitted nothing (design K2 ① / 坑 8). :func:`assert_submittable`
  therefore asks *before* the gate is ever constructed, and raises 16251 /
  16252 with the two remedies spelled out.
* **It does not notify the first node's approvers.** The gate creates the task
  rows and the audit row and stops; all three shipped scenarios send the
  station message from their own side (design 坑 5). Skipping it means approvers
  only find work by going to look for it.
* **It cannot carry the self-approval flag back.** ``resolve_approvers`` returns
  ``list[int]`` and ``ApprovalGateResult`` has four fixed fields, so the handler
  records it on itself and we read it here. That only works because
  :func:`_build_publish_approval_gate` builds a **fresh registry and a fresh
  handler for every request** — the engine has no global registry, this is the
  established pattern, and caching either would let two concurrent releases
  swap flags.

Error mapping: ``ApprovalScenarioDisabledError`` becomes **16225**, and 16225
means only that. Capacity shortage is 16226. The two remedies are opposite
("ask an administrator to seed the scenario" vs "wait for memory or publish
manually"), so a shared code guarantees one of the two copy strings is wrong
wherever it appears.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.services import publish_notification_service
from bisheng.app_publish.domain.services.app_publish_scenario_handler import (
    RELEASE_KIND_INITIAL,
    RELEASE_KIND_ITERATION,
    SCENARIO_CODE,
    AppPublishScenarioHandler,
)
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
    ApprovalGateRequest,
    ApprovalGateResult,
)
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.common.errcode.app_publish import (
    AppApprovalInFlightError,
    AppApprovalScenarioDisabledError,
    AppPendingOnlineError,
)
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao
from bisheng.database.models.app_version import AppVersionDao

#: Application state meaning "approved but parked" — a new submission on top of
#: it would leave two versions competing for one slot.
_APP_STATE_PENDING_CAPACITY = "pending_capacity"

#: Deployment statuses that mean an attempt still owns this application.
_ACTIVE_DEPLOYMENT_STATUSES = ("running", "waiting_approval")


def _build_publish_approval_gate() -> tuple[ApprovalGate, AppPublishScenarioHandler]:
    """A gate and its handler, built fresh for this one request.

    The pattern is the engine's, not a choice: there is no global handler
    registry, ``ApprovalGate(registry=...)`` takes one as a constructor
    argument, and the shipped scenarios assemble theirs per call the same way.

    Returning the handler alongside the gate is what makes the self-approval
    flag readable afterwards. Do not hoist either to module scope: two
    concurrent releases would then share one handler and one flag.
    """
    registry = ApprovalRegistry.with_default_presets()
    handler = AppPublishScenarioHandler()
    registry.register_handler(SCENARIO_CODE, handler)
    return ApprovalGate(registry=registry), handler


# ---------------------------------------------------------------------------
# The port: assert_submittable / submit / cancel
# ---------------------------------------------------------------------------


async def assert_submittable(app_id: str) -> None:
    """AC-03's two gates, asked before the approval gate sees anything.

    Order matters only in that both run before the gate; between themselves the
    in-flight check comes first because it is the common case (someone ran
    ``deploy`` twice).
    """
    from bisheng.app_publish.domain.models.app_deployment import AppDeploymentDao

    async with get_async_db_session() as session:
        active = await AppDeploymentDao.aget_active_by_app(session, app_id)
        app = await AppDao.aget(session, app_id)

    if active is not None and active.status in _ACTIVE_DEPLOYMENT_STATUSES:
        raise AppApprovalInFlightError(
            msg="该应用已有一次发布正在进行中",
            details={
                "app_id": app_id,
                "deployment_id": active.id,
                "stage": active.stage,
                "status": active.status,
                "reason": "deployment_in_flight",
            },
            hints=[
                "等待上一次发布完成, 或在发布面撤回在途的审批单后重试",
                "bisheng deploy --wait 可以等到上一次发布出终态",
            ],
        )

    if app is not None:
        instance = await ApprovalInstanceRepository.find_active_instance_by_resource(
            tenant_id=int(app.tenant_id or 0),
            scenario_code=SCENARIO_CODE,
            business_resource_type="app",
            business_resource_id=str(app_id),
        )
        if instance is not None:
            # Reached when the deployment row was swept but the request is
            # still open. Without this the gate would silently hand back the
            # existing instance and the CLI would report success.
            raise AppApprovalInFlightError(
                msg="该应用已有一个在途的发布审批单",
                details={"app_id": app_id, "approval_instance_id": instance.id, "reason": "approval_in_flight"},
                hints=["在发布面或审批中心撤回该审批单后再重新提交"],
            )

        if app.state == _APP_STATE_PENDING_CAPACITY:
            raise AppPendingOnlineError(
                msg="该应用处于待上线状态, 请先处理后再提交新版本",
                details={"app_id": app_id, "app_state": app.state, "reason": "pending_online"},
                hints=["在发布面点击「手动上线」重试, 或等待运行环境释放资源"],
            )


async def submit(deployment, **kwargs: Any) -> ApprovalGateResult:
    """Create the approval request for one deployment attempt.

    Raises 16225 when the scenario is not enabled in this deployment — and
    raises it *before* anything is written, which is exactly why
    ``record_version`` calls the gate first: a failure here leaves no version
    row behind (design D6).
    """
    app_id = str(deployment.app_id or "")
    async with get_async_db_session() as session:
        app = await AppDao.aget(session, app_id)
        previous_version_no = await AppVersionDao.amax_version_no(session, app_id)
    if app is None:
        raise AppApprovalScenarioDisabledError(
            msg="应用不存在, 无法提交发布审批",
            details={"app_id": app_id, "reason": "app_missing"},
        )

    owner_user_id = int(app.owner_user_id or deployment.owner_user_id or 0)
    owner_name = await _owner_user_name(owner_user_id)
    department_id = await _primary_department_id(owner_user_id)
    payload = await _build_payload(
        deployment,
        app=app,
        owner_user_id=owner_user_id,
        owner_user_name=owner_name,
        version_no=previous_version_no + 1,
        release_kind=RELEASE_KIND_INITIAL if previous_version_no == 0 else RELEASE_KIND_ITERATION,
        has_department=department_id is not None,
    )

    gate, handler = _build_publish_approval_gate()
    request = ApprovalGateRequest(
        tenant_id=int(deployment.tenant_id or app.tenant_id or 0),
        scenario_code=SCENARIO_CODE,
        # One publish attempt is one request. Using app_id instead would make
        # every retry look like a duplicate of the first.
        business_key=str(deployment.id),
        # Both are required with no default — a missing one is a ValidationError
        # at construction, not a silent empty string.
        business_resource_type="app",
        business_resource_id=app_id,
        business_name=app.name,
        # The natural person who owns the app, never the service account that
        # ran the CLI: a service account has no department of its own (it is
        # swept into the guest one), so resolving approvers from it would find
        # people with no relation to this application (design 坑 28 / INV-29).
        applicant_user_id=owner_user_id,
        applicant_user_name=owner_name,
        applicant_department_id=department_id,
        payload_snapshot=payload,
    )

    try:
        result = await gate.request_or_pass(request)
    except ApprovalScenarioDisabledError as exc:
        raise AppApprovalScenarioDisabledError(
            msg="本环境未启用「应用发布」审批场景, 无法提交发布",
            details={"app_id": app_id, "scenario_code": SCENARIO_CODE, "reason": "scenario_disabled"},
            hints=[
                "请管理员在审批中心启用「应用发布」场景后重试",
                "该提示与「运行环境容量不足」(16226) 无关, 不必等待资源",
            ],
        ) from exc
    except KeyError as exc:
        # The registry could not produce a handler. Impossible with the gate
        # built above, but a KeyError escaping as a 500 would hide the cause.
        raise AppApprovalScenarioDisabledError(
            msg="「应用发布」审批场景未注册处理器",
            details={"app_id": app_id, "scenario_code": SCENARIO_CODE, "reason": "handler_missing"},
        ) from exc

    await _after_gate(deployment, app=app, payload=payload, result=result, handler=handler)
    return result


async def cancel(instance_id: int, *, reason: str = "") -> None:
    """Cancel a request we created but could not finish attaching a version to.

    The compensation half of ``record_version``'s two phases. Routed through the
    approval module's own API rather than writing its tables from here: this is
    the same call the deletion hook makes, and it notifies the approvers.
    """
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    await ApprovalCenterService.cancel_instance_by_business(
        instance_id=int(instance_id),
        reason=reason or "版本记录写入失败, 已取消该发布审批单",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _after_gate(deployment, *, app, payload: dict, result: ApprovalGateResult, handler) -> None:
    """Everything the gate leaves to the caller: notification, self-approval audit."""
    if result.decision == ApprovalGateDecision.PENDING and result.task_ids:
        approver_ids = await _approver_ids(result.task_ids)
        await publish_notification_service.notify_approvers_of_new_task(
            tenant_id=int(deployment.tenant_id or 0),
            applicant_user_id=int(payload.get("owner_user_id") or 0),
            approver_user_ids=approver_ids,
            business_name=str(payload.get("app_name") or app.name),
            instance_id=int(result.instance_id),
            task_id=result.task_ids[0] if result.task_ids else None,
        )

    if getattr(handler, "last_self_approval", False):
        # AC-17: allowed, but never silent. This audit row is the only record
        # that a release was decided by the person who submitted it.
        await write_release_audit(
            AppReleaseAuditAction.SELF_APPROVAL,
            deployment=deployment,
            version_no=payload.get("version_no"),
            operator_id=int(payload.get("owner_user_id") or 0),
            metadata={
                "approval_instance_id": result.instance_id,
                "reason": "applicant_is_only_candidate",
            },
        )
        logger.info(
            f"app_publish.self_approval deployment_id={deployment.id} instance_id={result.instance_id} "
            f"owner_user_id={payload.get('owner_user_id')}"
        )


async def _build_payload(
    deployment,
    *,
    app,
    owner_user_id: int,
    owner_user_name: str,
    version_no: int,
    release_kind: str,
    has_department: bool,
) -> dict[str, Any]:
    """The payload snapshot: what the card renders *and* what the callbacks read.

    One structure rather than two because the outbox hands ``on_approved`` only
    ``(instance_id, payload_snapshot)``. Anything a terminal callback needs and
    this dict lacks would have to be re-derived from the approval module's own
    tables, which F055 has no business reading.

    ``version_no`` is the number the INSERT is *about to* use. It is computed
    here rather than after the fact because the gate runs first (design D6) and
    the card has to name the version; concurrent submissions are already refused
    by :func:`assert_submittable`, and ``UNIQUE(app_id, version_no)`` is the
    second net.
    """
    manifest = deployment.manifest if isinstance(deployment.manifest, dict) else {}
    return {
        "app_id": app.id,
        "app_name": app.name,
        "app_slug": app.slug,
        "tenant_id": int(deployment.tenant_id or app.tenant_id or 0),
        "version_id": deployment.version_id,
        "version_no": version_no,
        "deployment_id": deployment.id,
        "release_kind": release_kind,
        "owner_user_id": owner_user_id,
        "owner_user_name": owner_user_name,
        "source": "cli",
        "submitted_at": (deployment.create_time or datetime.now()).isoformat(),
        "tier": await _tier_payload(deployment.tier_code or manifest.get("tier") or "light"),
        # Capability declarations are a deferred wave; the key is present and
        # empty so the client panel's shape never changes when they land.
        "capabilities": [],
        "visibility_snapshot": [],
        "schema_change": None,
        # AC-16: says *why* the request went straight past the department
        # administrators, so an approver is not left wondering.
        "approver_note": None if has_department else "no_department_admin_source",
    }


async def _tier_payload(tier_code: str) -> dict[str, Any]:
    """The tier as the card shows it. A retired tier still renders — the release already picked it."""
    from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService

    try:
        tier = await ResourceTierService.resolve_spec(tier_code)
    except Exception:
        # The card must not fail to render because a tier row is missing; the
        # precheck already refused an unusable tier with 16223.
        logger.warning(f"app_publish.tier_payload_unresolved tier_code={tier_code}")
        return {"code": tier_code, "name": tier_code, "cpu_millicores": None, "memory_mb": None}
    return {
        "code": tier.code,
        "name": tier.name,
        "cpu_millicores": tier.cpu_millicores,
        "memory_mb": tier.memory_mb,
    }


async def _owner_user_name(owner_user_id: int) -> str:
    from bisheng.user.domain.models.user import UserDao

    try:
        user = await UserDao.aget_user(owner_user_id)
    except Exception:
        logger.warning(f"app_publish.owner_lookup_failed owner_user_id={owner_user_id}")
        user = None
    return (user.user_name if user else None) or str(owner_user_id)


async def _primary_department_id(owner_user_id: int) -> int | None:
    """The owner's **primary** department, with no walk up the tree (AC-14).

    A parent department's administrator is not automatically an approver here.
    That is the product rule; making it inherit would quietly widen who decides
    on every release in a deep organisation.
    """
    from bisheng.database.models.department import UserDepartmentDao

    try:
        row = await UserDepartmentDao.aget_user_primary_department(owner_user_id)
    except Exception:
        logger.warning(f"app_publish.primary_department_lookup_failed owner_user_id={owner_user_id}")
        return None
    return int(row.department_id) if row is not None else None


async def _approver_ids(task_ids: list[int]) -> list[int]:
    ids: list[int] = []
    for task_id in task_ids:
        task = await ApprovalInstanceRepository.get_task(task_id)
        if task is not None and task.approver_user_id and task.approver_user_id not in ids:
            ids.append(int(task.approver_user_id))
    return ids
