"""Background reconciler that repairs stale resource_permission_mode rows.

Finds knowledge_file / folder rows whose ``resource_permission_mode`` parent
disagrees with the business-truth parent computed from ``knowledgefile.file_level_path``
and re-projects via ``project_parent_change``.

Designed to run as a periodic Celery beat task (every 10 minutes) and also
exposed as a one-shot admin API for emergency repair.
"""

from __future__ import annotations

from dataclasses import replace

from loguru import logger
from sqlalchemy import and_, literal, or_, select
from sqlmodel import col

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    set_current_tenant_id,
)
from bisheng.core.context.tenant import (
    current_tenant_id as _tenant_ctx_var,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import StrJoinKey
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.domain.models.grant import ResourcePermissionMode
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)

# System actor used for automated background repairs.  super_admin=True
# bypasses all identity shortcuts, so the concrete user_id is irrelevant
# for authorization; 0 is the canonical "system" sentinel.
_SYSTEM_USER_ID = 0

# ── SQL queries ──────────────────────────────────────────────────────────


def _mismatch_query(*, batch_limit: int, nested: bool):
    """Rows whose permission mirror disagrees with the file's own path.

    Built through SQLAlchemy rather than as raw SQL because the raw version was
    MySQL-only and had never run on DaMeng: ``CAST(kf.id AS CHAR)`` means
    ``CHAR(1)`` there, so every multi-digit id was truncated and the whole
    statement failed with ``[CODE:-6149] Data lose`` — the reconciler had been
    dying on its first query every 10 minutes, leaving every drifted row
    unrepaired. ``SUBSTRING_INDEX`` does not exist on DaMeng either; the last
    path segment is matched with a portable LIKE instead (segments are digits,
    so no wildcard can leak in).
    """
    file_key = StrJoinKey(col(KnowledgeFile.id))
    type_matches = or_(
        and_(KnowledgeFile.file_type == 0, ResourcePermissionMode.resource_type == "folder"),
        and_(KnowledgeFile.file_type == 1, ResourcePermissionMode.resource_type == "knowledge_file"),
    )
    query = (
        select(
            ResourcePermissionMode.id.label("rpm_id"),
            ResourcePermissionMode.resource_type.label("resource_type"),
            ResourcePermissionMode.resource_id.label("resource_id"),
            ResourcePermissionMode.parent_type.label("stored_parent_type"),
            ResourcePermissionMode.parent_id.label("stored_parent_id"),
            KnowledgeFile.knowledge_id.label("knowledge_id"),
            KnowledgeFile.file_level_path.label("file_level_path"),
            KnowledgeFile.tenant_id.label("tenant_id"),
        )
        .select_from(ResourcePermissionMode)
        .join(KnowledgeFile, and_(file_key == ResourcePermissionMode.resource_id, type_matches))
    )
    has_path = and_(
        KnowledgeFile.file_level_path.is_not(None),
        KnowledgeFile.file_level_path != "",
    )
    if nested:
        # The mirror's parent_id must be the last segment of the path.
        last_segment = or_(
            KnowledgeFile.file_level_path == ResourcePermissionMode.parent_id,
            KnowledgeFile.file_level_path.like(literal("%/") + ResourcePermissionMode.parent_id),
        )
        query = query.where(
            has_path,
            or_(ResourcePermissionMode.parent_type != "folder", ~last_segment),
        )
    else:
        # No path: the file sits at the space root, so the space is its parent.
        query = query.join(Knowledge, and_(Knowledge.id == KnowledgeFile.knowledge_id, Knowledge.type == 3)).where(
            ~has_path,
            or_(
                ResourcePermissionMode.parent_type != "knowledge_space",
                ResourcePermissionMode.parent_id != StrJoinKey(col(KnowledgeFile.knowledge_id)),
            ),
        )
    return query.limit(batch_limit)


def _compute_correct_parent(file_level_path: str | None, knowledge_id: int) -> tuple[str, str]:
    """Compute the business-truth parent from knowledgefile columns."""
    segments = [p for p in (file_level_path or "").split("/") if p]
    if segments:
        return "folder", segments[-1]
    return "knowledge_space", str(knowledge_id)


async def _repair_single(
    *,
    resource_type: str,
    resource_id: str,
    stored_parent_type: str,
    stored_parent_id: str,
    tenant_id: int,
    correct_parent_type: str,
    correct_parent_id: str,
) -> bool:
    """Repair one stale projection row. Returns True on success."""
    token = set_current_tenant_id(tenant_id)
    try:
        adapter = await get_f048_resource_adapter(resource_type)
        target = await adapter.load_permission_record(
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if target is None:
            logger.warning(
                "stale_projection_reconciler: resource {}/{} not found, skipping",
                resource_type,
                resource_id,
            )
            return False

        # The drift is between the mirror and the business truth, so that is the
        # pair to compare. This compared the freshly loaded record against the
        # expectation computed from the same `file_level_path` — two readings of
        # the same truth, always equal — and skipped every candidate as "already
        # consistent". The scan found the drift and the repair declined to act
        # on it, for as long as both have existed.
        business_parent = (target.parent_type, target.parent_id)
        correct_parent = (correct_parent_type, correct_parent_id)
        stored_parent = (stored_parent_type, stored_parent_id)
        if business_parent != correct_parent:
            # The file moved again between the scan and now; the next cycle
            # re-reads it with fresh values rather than writing a stale one.
            logger.info(
                "stale_projection_reconciler: resource {}/{} moved since the scan, skipping",
                resource_type,
                resource_id,
            )
            return False
        if stored_parent == correct_parent:
            logger.info(
                "stale_projection_reconciler: resource {}/{} already consistent, skipping",
                resource_type,
                resource_id,
            )
            return False

        source = replace(
            target,
            parent_type=stored_parent_type,
            parent_id=stored_parent_id,
        )

        actor = PermissionActor(
            user_id=_SYSTEM_USER_ID,
            current_tenant_id=tenant_id,
            super_admin=True,
        )

        await adapter.project_move(source=source, target=target, actor=actor)
        logger.info(
            "stale_projection_reconciler: repaired resource={}:{} stored_parent={}:{} -> correct_parent={}:{}",
            resource_type,
            resource_id,
            stored_parent_type,
            stored_parent_id,
            correct_parent_type,
            correct_parent_id,
        )
        emit_metric(
            "permission",
            event="stale_projection_repaired",
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=str(tenant_id),
            stored_parent=f"{stored_parent_type}:{stored_parent_id}",
            correct_parent=f"{correct_parent_type}:{correct_parent_id}",
        )
        return True
    except (PermissionInvalidResourceError, Exception):
        # Best-effort background repair: a single-row failure must not block
        # the rest of the batch.  Known safe cases include:
        #   - PermissionInvalidResourceError: parent already matches (no-op
        #     or fixed by a concurrent reconciler run).
        #   - Transient OpenFGA / DB errors that will be retried next cycle.
        # All failures are logged with full traceback for SRE visibility.
        logger.exception(
            "stale_projection_reconciler: repair failed for resource={}:{}",
            resource_type,
            resource_id,
        )
        return False
    finally:
        _tenant_ctx_var.reset(token)


async def reconcile_stale_parent_projections(*, batch_limit: int = 200) -> int:
    """Find and repair stale ``resource_permission_mode`` rows.

    Returns the count of successfully repaired rows.
    """
    repaired = 0

    # The scan spans every tenant, so it must run outside the tenant filter —
    # the raw SQL it replaced was never intercepted by it.
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            root_rows = (await session.execute(_mismatch_query(batch_limit=batch_limit, nested=False))).mappings().all()
            nested_rows = (
                (await session.execute(_mismatch_query(batch_limit=batch_limit, nested=True))).mappings().all()
            )

    all_rows = list(root_rows) + list(nested_rows)
    if not all_rows:
        logger.debug("stale_projection_reconciler: no stale rows found")
        return 0

    logger.info(
        "stale_projection_reconciler: found {} stale rows (root={}, nested={})",
        len(all_rows),
        len(root_rows),
        len(nested_rows),
    )

    for row in all_rows:
        correct_parent_type, correct_parent_id = _compute_correct_parent(
            row["file_level_path"],
            row["knowledge_id"],
        )
        success = await _repair_single(
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            stored_parent_type=row["stored_parent_type"],
            stored_parent_id=row["stored_parent_id"],
            tenant_id=row["tenant_id"],
            correct_parent_type=correct_parent_type,
            correct_parent_id=correct_parent_id,
        )
        if success:
            repaired += 1

    logger.info(
        "stale_projection_reconciler: repaired {} out of {} stale rows",
        repaired,
        len(all_rows),
    )
    return repaired
