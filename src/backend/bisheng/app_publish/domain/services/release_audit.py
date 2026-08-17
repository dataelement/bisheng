"""One writer for the ``app.release.*`` audit family (design §4.2 ⑥ / D12).

Small on purpose: it exists so that every release event carries the same
``target_type`` / ``target_id`` / metadata shape, because AC-01's "the audit page
must be filterable by application" is only true if every row in the family
agrees on where the application id lives.

Two facts worth knowing before calling it:

* **The approval module's own audit rows are not a substitute.** Their
  ``target_type`` is always ``approval_instance`` / ``approval_task``, so
  filtering by application finds nothing in them (design 坑 20). That is why
  this family exists next to them rather than instead of them.
* **``AuditLogDao.ainsert_v2`` brings its own session, bypass and commit.** The
  caller must not wrap it in a transaction. It can raise, and an audit failure
  must not take the publish down with it — hence the narrow best-effort
  swallow, in the shape ``approval_outbox_service`` already uses.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import RELEASE_AUDIT_TARGET_TYPE, AppReleaseAuditAction
from bisheng.database.models.audit_log import AuditLogDao


async def write_release_audit(
    action: AppReleaseAuditAction | str,
    *,
    deployment,
    version_no: int | None = None,
    operator_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    """Record one release event against the version it is about.

    ``operator_id`` defaults to the acting subject of the submission (the
    service account); pass the owner explicitly for events a person triggered.
    """
    payload: dict[str, Any] = {
        "app_id": deployment.app_id,
        "deployment_id": deployment.id,
        "version_no": version_no,
    }
    payload.update(metadata or {})
    try:
        await AuditLogDao.ainsert_v2(
            tenant_id=deployment.tenant_id,
            operator_id=operator_id if operator_id is not None else deployment.submitted_by_user_id,
            operator_tenant_id=deployment.tenant_id,
            action=str(action),
            target_type=RELEASE_AUDIT_TARGET_TYPE,
            target_id=deployment.version_id,
            reason=reason,
            metadata=payload,
        )
    except Exception:
        # Best effort by design: an unwritten audit row must not fail a publish
        # that otherwise succeeded (same shape as approval_outbox_service).
        logger.exception(f"app_publish.audit_failed action={action} deployment_id={deployment.id}")
