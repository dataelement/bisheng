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
from sqlalchemy import text

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import (
    current_tenant_id as _tenant_ctx_var,
)
from bisheng.core.context.tenant import (
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.access import get_f048_resource_adapter
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)

# System actor used for automated background repairs.  super_admin=True
# bypasses all identity shortcuts, so the concrete user_id is irrelevant
# for authorization; 0 is the canonical "system" sentinel.
_SYSTEM_USER_ID = 0

# ── SQL queries ──────────────────────────────────────────────────────────

_ROOT_MISMATCH_SQL = """
    SELECT rpm.id            AS rpm_id,
           rpm.resource_type AS resource_type,
           rpm.resource_id   AS resource_id,
           rpm.parent_type   AS stored_parent_type,
           rpm.parent_id     AS stored_parent_id,
           kf.knowledge_id   AS knowledge_id,
           kf.file_level_path,
           kf.tenant_id      AS tenant_id
      FROM resource_permission_mode rpm
      JOIN knowledgefile kf ON CAST(kf.id AS CHAR) = rpm.resource_id
                            AND ((kf.file_type = 0 AND rpm.resource_type = 'folder')
                              OR (kf.file_type = 1 AND rpm.resource_type = 'knowledge_file'))
      JOIN knowledge k ON k.id = kf.knowledge_id AND k.type = 3
     WHERE (kf.file_level_path IS NULL OR kf.file_level_path = '')
       AND (rpm.parent_type <> 'knowledge_space'
            OR rpm.parent_id <> CAST(kf.knowledge_id AS CHAR))
     LIMIT :batch_limit
"""

_NESTED_MISMATCH_SQL = """
    SELECT rpm.id            AS rpm_id,
           rpm.resource_type AS resource_type,
           rpm.resource_id   AS resource_id,
           rpm.parent_type   AS stored_parent_type,
           rpm.parent_id     AS stored_parent_id,
           kf.knowledge_id   AS knowledge_id,
           kf.file_level_path,
           kf.tenant_id      AS tenant_id
      FROM resource_permission_mode rpm
      JOIN knowledgefile kf ON CAST(kf.id AS CHAR) = rpm.resource_id
                            AND ((kf.file_type = 0 AND rpm.resource_type = 'folder')
                              OR (kf.file_type = 1 AND rpm.resource_type = 'knowledge_file'))
     WHERE kf.file_level_path <> '' AND kf.file_level_path IS NOT NULL
       AND (rpm.parent_type <> 'folder'
            OR rpm.parent_id <> SUBSTRING_INDEX(kf.file_level_path, '/', -1))
     LIMIT :batch_limit
"""


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

        actual_parent = (target.parent_type, target.parent_id)
        expected_parent = (correct_parent_type, correct_parent_id)
        if actual_parent == expected_parent:
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

    async with get_async_db_session() as session:
        # ── root-level mismatch (SPACE) ──
        root_result = await session.execute(
            text(_ROOT_MISMATCH_SQL),
            {"batch_limit": batch_limit},
        )
        root_rows = root_result.mappings().all()

        # ── nested mismatch ──
        nested_result = await session.execute(
            text(_NESTED_MISMATCH_SQL),
            {"batch_limit": batch_limit},
        )
        nested_rows = nested_result.mappings().all()

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
