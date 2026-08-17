"""F056 — write ``app.visibility_change`` when a hosted application's grants change.

This is the business half of the F048 grant-change hook. The permission module
publishes "someone changed the grants of resource X"; naming the event
``app.visibility_change`` and deciding what belongs in it stays here, so
``permission`` never learns the ``app.`` audit namespace and never grows a
per-resource-type branch.

Three rules this file exists to enforce, each of which fails silently if broken:

* **Idempotent replays write nothing.** ``mutate_grants`` is keyed by an
  idempotency key; a retried request returns the same result without changing
  anything. Recording it anyway puts "the visibility was changed three times in
  the same second" in front of an auditor who then has to explain it.
* **No outer transaction.** ``AuditLogDao.ainsert_v2`` opens its own session,
  bypasses the tenant filter and commits by itself.
* **A failure here never fails the mutation.** The grants are already committed
  and projected by the time this runs. The warning it logs is the *only* signal
  that an audit record was lost — grep for it before suspecting the write path.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.app_runtime.domain.constants import AppAuditAction
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao
from bisheng.database.models.audit_log import AuditLogDao

_MUTATING_OPS = ("ADD", "REMOVE", "MOVE")


class HostedAppVisibilityAuditListener:
    """``GrantChangeListenerPort`` for ``resource_type == "app"``."""

    async def on_grants_changed(
        self,
        *,
        actor,
        target,
        request,
        result,
        roster_before,
        roster_complete: bool,
    ) -> None:
        try:
            if getattr(result.projection, "idempotent", False):
                # A replay changed nothing; recording it would invent history.
                return
            await self._write(
                actor=actor,
                target=target,
                request=request,
                roster_before=roster_before,
                roster_complete=roster_complete,
            )
        except Exception:
            logger.opt(exception=True).warning(
                "app.visibility_change audit write failed resource_type={} resource_id={} operator_id={}",
                getattr(target, "resource_type", None),
                getattr(target, "resource_id", None),
                getattr(actor, "user_id", None),
            )

    async def _write(self, *, actor, target, request, roster_before, roster_complete: bool) -> None:
        async with get_async_db_session() as session:
            app = await AppDao.aget(session, target.resource_id)

        metadata: dict[str, Any] = {
            "app_slug": getattr(app, "slug", None),
            "added": _added_subjects(request),
            "removed": _resolved_subjects(request, roster_before, op="REMOVE"),
            "model_keys": _model_keys(request),
        }
        moved = _resolved_subjects(request, roster_before, op="MOVE")
        if moved:
            # A model change (viewer → editor) is a visibility change too; the
            # subject identity behind it is just as unrecoverable afterwards.
            metadata["moved"] = moved
        if not roster_complete:
            # Said out loud rather than papered over: some `removed` entries
            # below could not be named because the roster's first page did not
            # reach them.
            metadata["roster_truncated"] = True

        await AuditLogDao.ainsert_v2(
            tenant_id=int(getattr(app, "tenant_id", 0) or target.tenant_id),
            # The person who made the change, even when that person is a tenant
            # administrator acting for the owner (AC-14).
            operator_id=int(getattr(actor, "user_id", 0) or 0),
            operator_tenant_id=int(getattr(actor, "current_tenant_id", 0) or target.tenant_id),
            action=AppAuditAction.VISIBILITY_CHANGE.value,
            target_type="app",
            target_id=target.resource_id,
            object_name=getattr(app, "name", None),
            metadata=metadata,
        )


def _added_subjects(request) -> list[dict[str, str]]:
    return [
        {"type": change.subject.type, "id": change.subject.id}
        for change in request.changes
        if change.op.value == "ADD" and change.subject is not None
    ]


def _resolved_subjects(request, roster_before, *, op: str) -> list[dict[str, str]]:
    """Name the subjects an assignee-addressed operation touched, via the snapshot."""
    resolved: list[dict[str, str]] = []
    for change in request.changes:
        if change.op.value != op or change.assignee_row_id is None:
            continue
        subject = roster_before.get(change.assignee_row_id)
        if subject is None:
            # Only reachable when the snapshot was truncated — `roster_truncated`
            # in the metadata says so.
            resolved.append({"assignee_id": str(change.assignee_row_id)})
            continue
        entry = {"type": subject[0], "id": subject[1]}
        if change.target_model_key:
            entry["model_key"] = change.target_model_key
        resolved.append(entry)
    return resolved


def _model_keys(request) -> list[str]:
    keys = {
        key
        for change in request.changes
        if change.op.value in _MUTATING_OPS
        for key in (change.model_key, change.target_model_key)
        if key
    }
    return sorted(keys)
