#!/usr/bin/env python3
"""F035 Track E: migrate ``linsight_llm`` config from ``task_model`` /
``linsight_executor_mode`` to the new single ``linsight_default_model_id``.

Context
-------
The deepagents migration removes ``WorkbenchModelConfig.task_model`` (a full
``WSModel``) and ``linsight_executor_mode`` (deepagents now owns the execution
mode). The execution model is now a single id chosen from the ``models`` list:
``linsight_default_model_id``.

This script rewrites the JSON ``value`` of every **own** row in
``tenant_system_model_config`` whose ``key = 'linsight_llm'`` (one per tenant
that has set its own config; multi-tenant inheritance is resolved at runtime,
so inherited-only tenants have no row here and are correctly skipped).

Per-row transform
-----------------
- If legacy ``task_model.id`` is present AND matches an id in the row's
  ``models`` list  -> ``linsight_default_model_id = task_model.id``.
- Otherwise (missing / not in ``models``) -> first id in ``models`` (or left
  empty if ``models`` is empty/absent).
- Always drop the legacy ``task_model`` and ``linsight_executor_mode`` keys.

Idempotent: a row with no ``task_model`` key is treated as already migrated and
skipped. JSON parsing is done in Python (no ``JSON_EXTRACT``) for DM8/MySQL
dual-DB compatibility.

Run from ``src/backend/`` (DB-only; no app context needed):

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/migrate_linsight_task_model_to_default.py            # dry-run
    python scripts/migrate_linsight_task_model_to_default.py --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.models.config import ConfigKeyEnum  # noqa: E402
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.llm.domain.models.tenant_system_model_config import (  # noqa: E402
    TenantSystemModelConfig,
)


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


def _transform(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Return ``(new_payload, action)``. ``action`` is one of:
    ``skip`` / ``kept`` / ``first`` / ``empty``.
    """
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


async def _run(apply: bool) -> int:
    key = ConfigKeyEnum.LINSIGHT_LLM.value
    summaries: list[dict[str, Any]] = []

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
                    summaries.append({"tenant_id": row.tenant_id, "action": "skip", "reason": "empty value"})
                    continue
                try:
                    payload = json.loads(row.value)
                except (TypeError, ValueError) as exc:
                    summaries.append({"tenant_id": row.tenant_id, "action": "error", "reason": f"invalid json: {exc}"})
                    continue
                if not isinstance(payload, dict):
                    summaries.append(
                        {"tenant_id": row.tenant_id, "action": "error", "reason": "value is not an object"}
                    )
                    continue

                new_payload, action = _transform(payload)
                summary = {
                    "tenant_id": row.tenant_id,
                    "action": action,
                    "linsight_default_model_id": new_payload.get("linsight_default_model_id"),
                }
                summaries.append(summary)

                if action == "skip":
                    continue
                if apply:
                    row.value = json.dumps(new_payload, ensure_ascii=False)
                    session.add(row)

            if apply:
                await session.commit()

    migrated = sum(1 for s in summaries if s["action"] in ("kept", "first", "empty"))
    skipped = sum(1 for s in summaries if s["action"] == "skip")
    errors = sum(1 for s in summaries if s["action"] == "error")

    print("Mode:", "apply" if apply else "dry-run")
    print(f"Rows scanned: {len(summaries)}  migrated: {migrated}  skipped: {skipped}  errors: {errors}")
    print(json.dumps({"dry_run": not apply, "rows": summaries}, ensure_ascii=False))
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply writes. Omit for dry-run preview (default).",
    )
    args = parser.parse_args()

    async def _main() -> int:
        try:
            return await _run(apply=args.apply)
        finally:
            await close_app_context()

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
