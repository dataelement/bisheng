"""Rejected / withdrawn / cancelled — the three non-online endings (design D10 / AC-33 / AC-34 / AC-35).

All three do the same three things, which is why they live together: latch the
version's outcome, close the deployment attempt, write the audit row. What
differs is one enum value and one piece of copy.

What they deliberately do **not** do:

* **They never touch the application state.** A rejected first release stays a
  draft; a rejected iteration keeps running whatever it was running. That falls
  out for free rather than being enforced — a release that was not approved
  never wrote ``pending_version_id``, so there is nothing to undo. Reaching for
  ``AppStateService`` here would be inventing a transition nobody asked for.
* **They never notify.** Rejection notifies the applicant and withdrawal
  notifies the approvers, both from inside the approval engine, which knows who
  actually held a task. Cancellation notifies the approvers from
  ``cancel_instance_by_business``. A second message from here would double
  every one of them.
* **Cancellation writes no terminal state.** There is no fourth value and there
  should not be one: cancellation only happens because the application was
  deleted, and a deleted application's version list is not reachable, so the
  value would have no reader (design D6).

The latch itself is idempotent by construction — ``amark_terminal`` carries a
``terminal_state IS NULL`` predicate — which is what stops a repeated withdraw
from overwriting "online" on a version that already shipped (design 坑 4).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.models.app_deployment import STAGE_APPROVED, AppDeploymentDao
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app_version import TERMINAL_STATE_REJECTED, TERMINAL_STATE_WITHDRAWN


class PublishTerminalService:
    """The three terminal callbacks of the publish approval scenario."""

    @classmethod
    async def on_rejected(cls, payload_snapshot: dict, *, reason: str | None) -> None:
        """AC-33. ``reason`` is the approver's comment, kept whole.

        The publish face shows it untruncated: a rejection an owner cannot read
        in full is a rejection they will re-submit unchanged.
        """
        await cls._settle(
            payload_snapshot,
            terminal_state=TERMINAL_STATE_REJECTED,
            audit_action=AppReleaseAuditAction.REJECTED,
            reason=reason,
            message="发布审批被驳回",
            failure_reason="approval_rejected",
        )

    @classmethod
    async def on_withdrawn(cls, payload_snapshot: dict, *, reason: str | None) -> None:
        """AC-34. Owner-only, and the engine has already enforced that.

        ``withdraw_instance`` refuses anybody who is not ``applicant_user_id``,
        and the applicant *is* the owner (AC-16) — so there is no second
        owner check to write here, and writing one would be a second source of
        truth for the same rule.
        """
        await cls._settle(
            payload_snapshot,
            terminal_state=TERMINAL_STATE_WITHDRAWN,
            audit_action=AppReleaseAuditAction.WITHDRAWN,
            reason=reason,
            message="发布申请已被撤回",
            failure_reason="approval_withdrawn",
        )

    @classmethod
    async def on_cancelled(cls, payload_snapshot: dict, *, reason: str | None) -> None:
        """AC-35 — the application was deleted, so its in-flight request was cancelled.

        No terminal state: see the module docstring. The audit row is the whole
        record, and it is what an administrator reads when they wonder where an
        approval task went.
        """
        await cls._settle(
            payload_snapshot,
            terminal_state=None,
            audit_action=AppReleaseAuditAction.CANCELLED,
            reason=reason,
            message="应用已删除, 发布申请已取消",
            failure_reason="app_deleted",
        )

    # ------------------------------------------------------------------

    @classmethod
    async def _settle(
        cls,
        payload_snapshot: dict,
        *,
        terminal_state: str | None,
        audit_action: AppReleaseAuditAction,
        reason: str | None,
        message: str,
        failure_reason: str,
    ) -> None:
        app_id = str(payload_snapshot.get("app_id") or "")
        version_id = str(payload_snapshot.get("version_id") or "")
        version_no = payload_snapshot.get("version_no")

        if terminal_state and app_id and version_id:
            # Scoped by app_id because app_version has no tenant column — the
            # app predicate *is* the tenant boundary here (design 坑 19).
            changed = await VersionService.mark_terminal_state(app_id, version_id, terminal_state)
            if not changed:
                logger.info(
                    f"app_publish.terminal_state_already_set app_id={app_id} version_id={version_id} "
                    f"attempted={terminal_state}"
                )

        deployment = await cls._close_deployment(payload_snapshot, message=message, reason=failure_reason)
        await write_release_audit(
            audit_action,
            deployment=deployment,
            version_no=version_no,
            operator_id=payload_snapshot.get("owner_user_id"),
            reason=reason,
            metadata={"terminal_state": terminal_state, "reason_kind": failure_reason},
        )

    @staticmethod
    async def _close_deployment(payload_snapshot: dict, *, message: str, reason: str) -> Any:
        """Latch the attempt as failed and hand back something the audit writer accepts.

        ``code`` is deliberately ``None``: this attempt did not fail a check, a
        person decided against it. The CLI and the publish face both branch on
        ``failure.code``, and giving a rejection a numeric code would file it
        with the precheck failures.
        """
        deployment_id = str(payload_snapshot.get("deployment_id") or "")
        failure = {
            "stage": STAGE_APPROVED,
            "code": None,
            "message": message,
            "details": {"reason": reason},
            "hints": ["修改后可重新执行 bisheng deploy 提交新的发布"],
        }
        if deployment_id:
            async with get_async_db_session() as session:
                row = await AppDeploymentDao.aget(session, deployment_id)
                if row is not None:
                    await AppDeploymentDao.aset_failed(session, deployment_id, failure=failure, stage=STAGE_APPROVED)
                    await session.commit()
                    return row
        return SimpleNamespace(
            id=deployment_id or None,
            app_id=str(payload_snapshot.get("app_id") or ""),
            tenant_id=int(payload_snapshot.get("tenant_id") or 0),
            version_id=str(payload_snapshot.get("version_id") or ""),
            submitted_by_user_id=int(payload_snapshot.get("owner_user_id") or 0),
            stage=STAGE_APPROVED,
        )
