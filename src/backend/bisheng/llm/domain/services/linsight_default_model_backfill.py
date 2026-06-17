"""Idempotent backfill: migrate ``linsight_llm`` config to ``linsight_default_model_id``.

F035 Track E. The deepagents migration removes ``task_model`` (a full ``WSModel``)
and ``linsight_executor_mode`` (deepagents owns the execution mode); the execution
model is now a single id picked from the row's ``models`` list:
``linsight_default_model_id``.

This module rewrites the JSON ``value`` of every **own** ``tenant_system_model_config``
row whose ``key = 'linsight_llm'`` (inherited-only tenants have no row and are
correctly skipped). It is the single source of truth for that transform: it runs
automatically on startup (``main.lifespan``) and is also exposed as a standalone CLI
(``scripts/migrate_linsight_task_model_to_default.py``).

Per-row transform:
- legacy ``task_model.id`` still present in ``models`` -> ``linsight_default_model_id``
  keeps it;
- otherwise -> first id in ``models`` (or empty when ``models`` is empty/absent);
- the legacy ``task_model`` / ``linsight_executor_mode`` keys are always dropped.

Idempotent: a row without ``task_model`` is treated as already migrated and skipped,
so re-runs (and concurrent multi-worker startups) are no-ops. JSON is parsed in Python
(no ``JSON_EXTRACT``) for DM8/MySQL dual-DB compatibility.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlmodel import select

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig


def _model_ids(payload: dict[str, Any]) -> list[str]:
    """Return the list of model ids (as strings) declared in ``models``."""
    models = payload.get("models")
    if not isinstance(models, list):
        return []
    ids: list[str] = []
    for m in models:
        if isinstance(m, dict) and m.get("id") is not None:
            ids.append(str(m["id"]))
    return ids


def transform_linsight_llm_config(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Pure transform. Returns ``(new_payload, action)`` where action is one of
    ``skip`` / ``kept`` / ``first`` / ``empty``. Input is not mutated."""
    # Idempotency: nothing to do once task_model is gone.
    if "task_model" not in payload:
        return payload, "skip"

    new_payload = dict(payload)
    legacy_model = new_payload.pop("task_model", None)
    new_payload.pop("linsight_executor_mode", None)

    valid_ids = _model_ids(new_payload)
    legacy_id = None
    if isinstance(legacy_model, dict) and legacy_model.get("id") is not None:
        legacy_id = str(legacy_model["id"])

    if legacy_id is not None and legacy_id in valid_ids:
        new_payload["linsight_default_model_id"] = legacy_id
        action = "kept"
    elif valid_ids:
        new_payload["linsight_default_model_id"] = valid_ids[0]
        action = "first"
    else:
        new_payload["linsight_default_model_id"] = None
        action = "empty"
    return new_payload, action


async def backfill_linsight_default_model(apply: bool = True) -> dict:
    """Rewrite every own ``linsight_llm`` config row to the new single-model shape.

    ``apply=True`` (startup/CLI-apply) persists; ``apply=False`` previews (CLI dry-run).
    Returns a summary dict. Safe to call on every startup — idempotent and benign on
    empty/invalid rows (they are reported, not raised).
    """
    key = ConfigKeyEnum.LINSIGHT_LLM.value
    rows_summary: list[dict[str, Any]] = []

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            rows = (
                await session.exec(
                    select(TenantSystemModelConfig)
                    .where(TenantSystemModelConfig.key == key)
                    .order_by(TenantSystemModelConfig.tenant_id.asc())
                )
            ).all()

            for row in rows:
                if not row.value:
                    rows_summary.append({"tenant_id": row.tenant_id, "action": "skip", "reason": "empty value"})
                    continue
                try:
                    payload = json.loads(row.value)
                except (TypeError, ValueError) as exc:
                    rows_summary.append(
                        {"tenant_id": row.tenant_id, "action": "error", "reason": f"invalid json: {exc}"}
                    )
                    continue
                if not isinstance(payload, dict):
                    rows_summary.append(
                        {"tenant_id": row.tenant_id, "action": "error", "reason": "value is not an object"}
                    )
                    continue

                new_payload, action = transform_linsight_llm_config(payload)
                rows_summary.append(
                    {
                        "tenant_id": row.tenant_id,
                        "action": action,
                        "linsight_default_model_id": new_payload.get("linsight_default_model_id"),
                    }
                )
                if action == "skip":
                    continue
                if apply:
                    row.value = json.dumps(new_payload, ensure_ascii=False)
                    session.add(row)

            if apply:
                await session.commit()

    migrated = sum(1 for s in rows_summary if s["action"] in ("kept", "first", "empty"))
    errors = sum(1 for s in rows_summary if s["action"] == "error")
    if apply and migrated:
        logger.info("linsight default-model backfill migrated {} config row(s)", migrated)
    return {
        "apply": apply,
        "scanned": len(rows_summary),
        "migrated": migrated,
        "skipped": sum(1 for s in rows_summary if s["action"] == "skip"),
        "errors": errors,
        "rows": rows_summary,
    }
