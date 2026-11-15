"""Idempotent upgrade backfill: give pre-3.0 workbench configs a daily-mode default.

Before 3.0 there was no ``chat_default_model_id``: with no saved pick the client
started daily chat on the **last** model of the workbench ``models`` list
(``v2.6.0:useChatModelMemo.ts``). 3.0 added the field, so an upgraded config has no
default — the admin page shows it empty and, with DSH enabled, the catalog falls
back to the first allowed model instead of the one users had.

Per own ``linsight_llm`` row (inheriting tenants have no row and keep inheriting):
- the default is absent or ``None`` and models are listed -> set it to the last
  model id;
- otherwise -> skip.

An empty value is filled even when the key exists: 3.0 writes the whole config on
every save (``model_dump()``), including saves no admin made for this field (e.g.
auto-filling the title model when a model is added), so a ``None`` does not mean
an admin cleared the default. Filling it is behaviour-neutral for an admin who did
clear it: with no default the client already falls back to the last model.

Runs on startup (``main.lifespan``) and as a CLI
(``scripts/backfill_workbench_upgrade.py``). JSON is parsed in Python for
MySQL/DM8 compatibility.
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
from bisheng.llm.domain.services.linsight_default_model_backfill import _model_ids

FIELD = "chat_default_model_id"


def transform_chat_default(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Pure transform. Returns ``(new_payload, action)``: ``skip`` / ``last``."""
    ids = _model_ids(payload)
    if payload.get(FIELD) not in (None, "") or not ids:
        return payload, "skip"
    return {**payload, FIELD: ids[-1]}, "last"


async def backfill_chat_default_model(apply: bool = True) -> dict[str, Any]:
    """Fill ``chat_default_model_id`` on every own ``linsight_llm`` row that has none."""
    rows_summary: list[dict[str, Any]] = []
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            rows = (
                await session.exec(
                    select(TenantSystemModelConfig)
                    .where(TenantSystemModelConfig.key == ConfigKeyEnum.LINSIGHT_LLM.value)
                    .order_by(TenantSystemModelConfig.tenant_id.asc())
                )
            ).all()
            for row in rows:
                try:
                    payload = json.loads(row.value) if row.value else None
                except (TypeError, ValueError) as exc:
                    rows_summary.append(
                        {"tenant_id": row.tenant_id, "action": "error", "reason": f"invalid json: {exc}"}
                    )
                    continue
                if not isinstance(payload, dict):
                    rows_summary.append(
                        {"tenant_id": row.tenant_id, "action": "skip", "reason": "empty or not an object"}
                    )
                    continue
                new_payload, action = transform_chat_default(payload)
                rows_summary.append({"tenant_id": row.tenant_id, "action": action, FIELD: new_payload.get(FIELD)})
                if action != "skip" and apply:
                    row.value = json.dumps(new_payload, ensure_ascii=False)
                    session.add(row)
            if apply:
                await session.commit()

    migrated = sum(1 for row in rows_summary if row["action"] == "last")
    if apply and migrated:
        logger.info("chat default-model backfill set {} config row(s)", migrated)
    return {
        "apply": apply,
        "scanned": len(rows_summary),
        "migrated": migrated,
        "errors": sum(1 for row in rows_summary if row["action"] == "error"),
        "rows": rows_summary,
    }
