"""``app_version`` writes: the D6 two-phase unit, and the one column that may be updated.

``app_version`` is INSERT-only except for a single ``terminal_state`` latch
(F054 D8's one authorised exception, exercised from here and nowhere else). That
constraint is what makes *when* the row is written the whole of design D6:

**The gate runs first, the INSERT second, and the compensation is explicit.**
``ApprovalGate`` writes and commits on its own session, so it cannot share a
transaction with the INSERT. Two orderings were possible and only one survives:

* INSERT then gate — the gate raises (scenario never seeded) or resolves no
  approver, and AC-40 forbids deleting the row that was just written. The owner
  is left with a version that has no terminal state and no approval request,
  forever.
* gate then INSERT (chosen) — a gate failure leaves nothing behind, and the far
  rarer "gate succeeded, INSERT failed" is handled by cancelling the request
  that was just created and recording ``app.release.rollback``. Two phases,
  stated as two phases.

:meth:`VersionService.record_version` therefore owns that unit rather than
leaving the ordering to whoever calls it. The approval side arrives as a
**port** (anything with ``submit`` / ``cancel`` coroutines — Wave 3's
``publish_approval_service`` module satisfies it as-is), so the invariant is
testable before the approval wiring exists and this module never imports the
approval gate.

Two more rules with teeth:

* **``EXCEPTION`` still records a version.** An empty approver set is an
  administrator's problem (AC-18); with no version row there is nothing to
  publish once they fix it.
* **"待上线" is derived, not stored.** ``terminal_state`` has exactly three
  non-NULL values. The app-availability line lives on ``app.state`` /
  ``app.pending_version_id``; merging the two lines into one column is how they
  stop being orthogonal (spec §3.0.2).

Every method that starts from a ``version_id`` also takes ``app_id``:
``app_version`` has no ``tenant_id`` column, so the ``app_id`` predicate *is*
the tenant boundary (design 坑 19).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.models.app_deployment import (
    STAGE_APPROVAL_CREATED,
    STAGE_VERSION_RECORDED,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    AppDeployment,
    AppDeploymentDao,
)
from bisheng.app_publish.domain.schemas.failure import failure_from_error
from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao
from bisheng.database.models.app_version import (
    TERMINAL_STATE_ONLINE,
    TERMINAL_STATE_REJECTED,
    TERMINAL_STATE_WITHDRAWN,
    VERSION_KIND_INITIAL,
    VERSION_KIND_ITERATION,
    AppVersion,
    AppVersionDao,
)

#: The three non-NULL values of ``app_version.terminal_state``. NULL — "no
#: outcome yet" — is the fourth state and deliberately not a member here: it is
#: the absence of a decision, not a decision.
TERMINAL_STATES: tuple[str, ...] = (TERMINAL_STATE_ONLINE, TERMINAL_STATE_REJECTED, TERMINAL_STATE_WITHDRAWN)

#: Derived display states (design D6). Not columns.
DISPLAY_PENDING_ONLINE = "pending_online"
DISPLAY_UNDER_APPROVAL = "under_approval"


class ApprovalPort(Protocol):
    """What ``record_version`` needs from the approval side (Wave 3's ``publish_approval_service``).

    ``submit`` returns anything carrying ``decision`` (an
    :class:`ApprovalGateDecision`) and ``instance_id`` — i.e. the gate's own
    ``ApprovalGateResult``, unchanged. It raises a ``BaseErrorCode`` (16225) when
    the scenario is not enabled in this deployment.
    """

    async def submit(self, deployment: AppDeployment, **kwargs: Any) -> Any: ...

    async def cancel(self, instance_id: int, *, reason: str = "") -> None: ...


class VersionService:
    """Version records. One INSERT path, one latch, no delete."""

    # -- the D6 unit ------------------------------------------------------

    @classmethod
    async def record_version(
        cls, deployment: AppDeployment, *, approval: ApprovalPort, image_ref: str | None = None, **submit_kwargs: Any
    ) -> AppVersion:
        """Create the approval request, then the version record. See the module docstring.

        Raises whatever the gate raised (after latching the deployment as
        failed with AC-11's five-tuple), or re-raises an INSERT failure after
        cancelling the request it had already created.
        """
        if deployment.status != STATUS_RUNNING:
            raise ValueError(
                f"deployment {deployment.id} is {deployment.status!r}: a submission that already failed "
                "precheck or the secret scan must never reach the version list (AC-02 / 决议-9)"
            )

        # Phase 1 — the gate. It commits on its own session.
        try:
            outcome = await approval.submit(deployment, **submit_kwargs)
        except BaseErrorCode as exc:
            failure = failure_from_error(exc, stage=STAGE_APPROVAL_CREATED)
            async with get_async_db_session() as session:
                await AppDeploymentDao.aset_failed(
                    session, deployment.id, failure=failure, stage=STAGE_APPROVAL_CREATED
                )
                await session.commit()
            logger.warning(f"app_publish.approval_gate_failed deployment_id={deployment.id} code={failure['code']}")
            raise

        instance_id = getattr(outcome, "instance_id", None)
        decision = getattr(outcome, "decision", ApprovalGateDecision.PENDING)

        # Phase 2 — the version record. Compensate phase 1 if this fails.
        try:
            version = await cls._insert_version(deployment, image_ref=image_ref)
        except Exception:
            logger.exception(f"app_publish.version_insert_failed deployment_id={deployment.id}")
            if instance_id:
                try:
                    await approval.cancel(int(instance_id), reason="version record insert failed")
                except Exception:
                    # Best effort by design: the caller is already failing, and
                    # the audit row below is the trail an administrator follows
                    # to cancel the orphaned request by hand.
                    logger.exception(f"app_publish.compensation_failed instance_id={instance_id}")
            async with get_async_db_session() as session:
                await AppDeploymentDao.aset_failed(
                    session,
                    deployment.id,
                    failure={
                        "stage": STAGE_VERSION_RECORDED,
                        "code": 0,
                        "message": "版本记录写入失败, 已取消刚创建的审批单",
                        "details": {"reason": "version_insert_failed", "approval_instance_id": instance_id},
                        "hints": ["请重试发布; 若反复失败请联系管理员查看后端日志"],
                    },
                    stage=STAGE_VERSION_RECORDED,
                )
                await session.commit()
            await write_release_audit(
                AppReleaseAuditAction.ROLLBACK,
                deployment=deployment,
                metadata={"approval_instance_id": instance_id},
            )
            raise

        deployment.version_id = version.id
        deployment.approval_instance_id = int(instance_id) if instance_id else None
        async with get_async_db_session() as session:
            await AppDeploymentDao.aadvance_stage(
                session,
                deployment.id,
                stage=STAGE_APPROVAL_CREATED,
                status=STATUS_WAITING_APPROVAL,
                version_id=version.id,
                approval_instance_id=deployment.approval_instance_id,
            )
            await session.commit()

        await write_release_audit(
            AppReleaseAuditAction.VERSION_CREATED, deployment=deployment, version_no=version.version_no
        )
        exceptional = decision == ApprovalGateDecision.EXCEPTION
        await write_release_audit(
            AppReleaseAuditAction.APPROVAL_EXCEPTION if exceptional else AppReleaseAuditAction.APPROVAL_CREATED,
            deployment=deployment,
            version_no=version.version_no,
            metadata={"approval_instance_id": instance_id, "decision": str(decision)},
        )
        return version

    @classmethod
    async def _insert_version(cls, deployment: AppDeployment, *, image_ref: str | None = None) -> AppVersion:
        """The INSERT itself: number, kind, and the one snapshot the record freezes.

        Code snapshot, capability declaration, injection config and tier are one
        snapshot — F054 AC-02 forbids any writer from changing one of them
        alone, which is why they are written together here and never patched.
        """
        manifest = deployment.manifest or {}
        async with get_async_db_session() as session:
            previous = await AppVersionDao.amax_version_no(session, deployment.app_id)
            row = AppVersion(
                id=deployment.version_id,
                app_id=deployment.app_id,
                version_no=previous + 1,
                kind=VERSION_KIND_INITIAL if previous == 0 else VERSION_KIND_ITERATION,
                terminal_state=None,
                code_object_key=deployment.code_object_key or "",
                manifest=manifest,
                capabilities=manifest.get("capabilities") or {},
                injections={},
                tier_id=deployment.tier_code or manifest.get("tier") or "light",
                runtime=str(manifest.get("runtime") or ""),
                # The image the build produced. Without it the version row keeps
                # image_ref NULL, and the deploy after approval sends an empty
                # image to the orchestrator — Docker then rejects the create with
                # "no command specified" and the app never comes online.
                image_ref=image_ref,
                submitted_at=deployment.create_time or datetime.now(),
            )
            await AppVersionDao.ainsert(session, row)
            await session.commit()
        return row

    # -- the single latch -------------------------------------------------

    @classmethod
    async def mark_terminal_state(cls, app_id: str, version_id: str, terminal_state: str) -> bool:
        """Latch the approval outcome. The **only** authorised UPDATE of ``app_version``.

        Returns ``False`` when the row already carried a decision — the DAO's
        ``terminal_state IS NULL`` predicate is what makes a repeated
        ``withdraw`` (design 坑 4) unable to overwrite "online".

        There is no "cancelled" value: deleting an application hides its whole
        version list, so the case needs no fifth state (design D6).
        """
        if terminal_state not in TERMINAL_STATES:
            raise ValueError(f"terminal_state must be one of {TERMINAL_STATES}, got {terminal_state!r}")
        async with get_async_db_session() as session:
            changed = await AppVersionDao.amark_terminal(session, app_id, version_id, terminal_state)
            await session.commit()
        return changed

    # -- reads ------------------------------------------------------------

    @classmethod
    def derive_display_state(cls, app, version, *, has_active_approval: bool = False) -> str | None:
        """What the version list shows for this row (AC-39). Computed, never stored."""
        if version.terminal_state:
            return str(version.terminal_state)
        if app is not None and getattr(app, "pending_version_id", None) == version.id:
            return DISPLAY_PENDING_ONLINE
        if has_active_approval:
            return DISPLAY_UNDER_APPROVAL
        return None

    @classmethod
    async def get_version(cls, app_id: str, version_id: str) -> AppVersion | None:
        async with get_async_db_session() as session:
            return await AppVersionDao.aget(session, app_id, version_id)

    @classmethod
    async def list_versions(cls, app_id: str) -> list[AppVersion]:
        async with get_async_db_session() as session:
            return await AppVersionDao.alist_by_app(session, app_id)

    @classmethod
    async def get_snapshot(cls, app_id: str, version_id: str) -> bytes | None:
        """The frozen package of one version (AC-43): review view, preview start-up, future rollback."""
        version = await cls.get_version(app_id, version_id)
        if version is None or not version.code_object_key:
            return None
        return await package_service.fetch_package(version.code_object_key)

    @classmethod
    async def get_app_scoped(cls, app_id: str):
        """The ``app`` row, which is the tenant-filtered handle every version read hangs off."""
        async with get_async_db_session() as session:
            return await AppDao.aget(session, app_id)
