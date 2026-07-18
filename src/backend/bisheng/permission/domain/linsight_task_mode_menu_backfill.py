"""Idempotent backfill: grant WEB_MENU ``linsight_task_mode`` to roles with ``home``.

Before F035 the 任务模式 entry (``/linsight``) shared the ``home`` menu permission
with 日常对话 (``/c``). F035 split it into its own sub-toggle ``linsight_task_mode``
(under 首页), so after upgrade the ``/linsight`` route guard checks the new key —
every existing role that could enter 任务模式 (i.e. already has ``home``) must be
granted it, or those users lose access (regression — PRD §4.7.7 FR-7.11, design §6.7).

This module is the single source of truth for that backfill. It runs automatically
on startup (``main.lifespan``) and is also exposed as a standalone CLI
(``scripts/backfill_linsight_task_mode_web_menu.py``). Idempotent: roles that already
have the key are skipped, so re-runs (and concurrent multi-worker startups) are no-ops.
"""

from __future__ import annotations

from loguru import logger
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.role_access import AccessType, RoleAccess, WebMenuResource

WEB_MENU = AccessType.WEB_MENU.value
HOME = WebMenuResource.HOME.value
LINSIGHT_TASK_MODE = WebMenuResource.LINSIGHT_TASK_MODE.value


def compute_missing_task_mode_grants(
    home_keys: list[tuple[int, int]], existing_keys: set[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Pure: dedup ``(role_id, tenant_id)`` keys that have ``home`` but not yet
    ``linsight_task_mode``. Order-preserving; never returns duplicates."""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for key in home_keys:
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


async def backfill_linsight_task_mode_web_menu(apply: bool = True) -> dict:
    """Grant ``linsight_task_mode`` to every (role, tenant) that has ``home`` but not it.

    ``apply=True`` (the startup/CLI-apply path) writes the missing rows; ``apply=False``
    only previews (CLI dry-run). Returns a summary dict. Safe to call on every startup —
    DB-only, idempotent, and it never raises on a benign empty result.
    """
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            home_rows = (
                await session.exec(
                    select(RoleAccess).where(
                        RoleAccess.type == WEB_MENU,
                        RoleAccess.third_id == HOME,
                    )
                )
            ).all()
            existing_rows = (
                await session.exec(
                    select(RoleAccess).where(
                        RoleAccess.type == WEB_MENU,
                        RoleAccess.third_id == LINSIGHT_TASK_MODE,
                    )
                )
            ).all()

        existing_keys = {(r.role_id, r.tenant_id) for r in existing_rows}
        home_keys = [(r.role_id, r.tenant_id) for r in home_rows]
        to_create = compute_missing_task_mode_grants(home_keys, existing_keys)
        if apply:
            for role_id, tenant_id in to_create:
                session.add(
                    RoleAccess(
                        role_id=role_id,
                        type=WEB_MENU,
                        third_id=LINSIGHT_TASK_MODE,
                        tenant_id=tenant_id,
                    )
                )
            if to_create:
                await session.commit()

    if apply and to_create:
        logger.info("linsight task-mode menu backfill granted {} role(s)", len(to_create))
    return {
        "apply": apply,
        "roles_with_home": len(set(home_keys)),
        "already_had_linsight_task_mode": len(existing_keys),
        "backfilled": len(to_create),
        "backfilled_keys": [{"role_id": rid, "tenant_id": tid} for rid, tid in to_create],
    }
