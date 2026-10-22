"""Bounded, explicitly tenant-scoped digest backfill; caller commits each batch."""

from hashlib import sha256

from sqlalchemy import update
from sqlmodel import select

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.model_audit_status import refresh_audit_status


def backfill_name_digests(session, *, after="", limit=200, apply=False):
    tenant = require_tenant()
    if not 1 <= limit <= 1000:
        raise ValueError("Batch size must be between 1 and 1000")
    rows = session.exec(
        select(DshModelAuditRequest.request_id, DshModelAuditRequest.model_name)
        .where(DshModelAuditRequest.request_id > after, DshModelAuditRequest.model_name_digest.is_(None))
        .order_by(DshModelAuditRequest.request_id)
        .limit(limit + 1)
    ).all()
    updated = 0
    if apply:
        for request_id, name in rows[:limit]:
            # Bulk UPDATE bypasses the SELECT-only tenant hook; scope and CAS are mandatory.
            result = session.exec(
                update(DshModelAuditRequest)
                .where(
                    DshModelAuditRequest.tenant_id == tenant,
                    DshModelAuditRequest.request_id == request_id,
                    DshModelAuditRequest.model_name == name,
                    DshModelAuditRequest.model_name_digest.is_(None),
                )
                .values(model_name_digest=sha256(name.encode("utf8")).hexdigest())
            )
            updated += result.rowcount
    selected = rows[:limit]
    return {
        "tenant_id": tenant,
        "apply": apply,
        "examined": len(selected),
        "updated": updated,
        "after_request_id": selected[-1][0] if selected else after,
        "has_more": len(rows) > limit,
    }


def backfill_audit_presentation(session, *, after="", limit=200, apply=False):
    tenant = require_tenant()
    if not 1 <= limit <= 1000:
        raise ValueError("Batch size must be between 1 and 1000")
    statement = (
        select(DshModelAuditRequest)
        .where(
            DshModelAuditRequest.audit_status.is_(None),
            DshModelAuditRequest.request_id > after,
        )
        .order_by(DshModelAuditRequest.request_id)
        .limit(limit)
    )
    if apply:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    rows = session.exec(statement).all()
    if apply:
        for row in rows:
            refresh_audit_status(row)
            if row.model_name_digest is None:
                row.model_name_digest = sha256(row.model_name.encode("utf8")).hexdigest()
            session.add(row)
    return {
        "tenant_id": tenant,
        "apply": apply,
        "examined": len(rows),
        "updated": len(rows) if apply else 0,
        "after_request_id": rows[-1].request_id if rows else after,
        "has_more": len(rows) == limit,
    }
