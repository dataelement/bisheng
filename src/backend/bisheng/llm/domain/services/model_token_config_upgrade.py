"""Portable, transactional upgrade of legacy model token settings.

The CLI in scripts/migrate_model_token_configs.py owns operational execution.
All JSON transformations run in Python for MySQL/DM8 compatibility.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

BACKUP_FORMAT = "bisheng-model-token-config-v1"


def transform_token_config(config: dict | None, provider: str) -> dict | None:
    """Preserve the formerly effective limit and every unrelated parameter."""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("config_not_object")
    if "max_tokens" not in config:
        return None
    params = config.get("user_kwargs")
    if params is None or params == "":
        params = {}
    elif isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            raise ValueError("advanced_json_invalid") from None
    if not isinstance(params, dict):
        raise ValueError("advanced_json_not_object")
    result = deepcopy(config)
    params = deepcopy(params)
    limit = result.pop("max_tokens")
    if limit is not None and limit != "" and limit != 0:
        if isinstance(limit, str) and limit.isdecimal():
            limit = int(limit)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("legacy_limit_invalid")
        # Legacy fields used to override the same key in advanced parameters.
        params["num_ctx" if provider == "ollama" else "max_tokens"] = limit
        result["user_kwargs"] = json.dumps(params, ensure_ascii=False, allow_nan=False)
    return result


def _read_backup(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise ValueError("backup_format_invalid")
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ValueError("backup_rows_invalid")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "tenant_id", "server_id", "before", "after"}:
            raise ValueError("backup_row_invalid")
        if type(row["id"]) is not int or row["id"] in ids:
            raise ValueError("backup_identity_invalid")
        if not isinstance(row["before"], dict) or not isinstance(row["after"], dict):
            raise ValueError("backup_config_invalid")
        ids.add(row["id"])
    return rows


def _write_backup(path: str, rows: list[dict]) -> None:
    """Create a private, durable file before any database write."""
    payload = json.dumps({"format": BACKUP_FORMAT, "rows": rows}, ensure_ascii=False, allow_nan=False)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(payload + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(str(Path(path).parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


async def migrate_model_token_configs(
    *,
    apply: bool = False,
    tenant_ids: list[int] | None = None,
    backup_file: str | None = None,
    restore_backup: str | None = None,
) -> dict:
    """Plan every row first; any anomaly blocks the entire transaction.

    Restore compares the current configuration with the recorded post-upgrade
    value, preserving configurations edited after the migration.
    """
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.llm.domain.models import LLMModel, LLMServer

    if apply and not backup_file:
        raise ValueError("backup_file_required")
    if tenant_ids is not None and (not tenant_ids or any(type(x) is not int or x < 1 for x in tenant_ids)):
        raise ValueError("tenant_scope_invalid")
    restoring = _read_backup(restore_backup) if restore_backup else None
    report = {
        "apply": apply,
        "mode": "restore" if restoring is not None else "upgrade",
        "scanned": 0,
        "planned": 0,
        "migrated": 0,
        "errors": [],
        "rows": [],
    }
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            statement = select(LLMModel).where(LLMModel.model_type == "llm").order_by(LLMModel.id)
            if tenant_ids is not None:
                statement = statement.where(LLMModel.tenant_id.in_(tenant_ids))
            if restoring is not None:
                statement = statement.where(LLMModel.id.in_([r["id"] for r in restoring]))
            if apply:
                statement = statement.with_for_update()
            models = (await session.exec(statement)).all()
            servers = (await session.exec(select(LLMServer))).all()
            providers = {row.id: row for row in servers}
            restore_rows = {row["id"]: row for row in restoring or []}
            changes = []
            for model in models:
                report["scanned"] += 1
                identity = {"id": model.id, "tenant_id": model.tenant_id, "server_id": model.server_id}
                try:
                    if restoring is None and isinstance(model.config, dict) and "max_tokens" not in model.config:
                        continue
                    if restoring is None and model.config is None:
                        continue
                    provider = providers.get(model.server_id)
                    if provider is None or provider.tenant_id != model.tenant_id:
                        raise ValueError("provider_identity_invalid")
                    if restoring is not None:
                        entry = restore_rows[model.id]
                        if any(entry[key] != identity[key] for key in identity):
                            raise ValueError("backup_identity_mismatch")
                        if model.config == entry["before"]:
                            continue
                        if model.config != entry["after"]:
                            raise ValueError("configuration_changed_after_upgrade")
                        updated = deepcopy(entry["before"])
                    else:
                        updated = transform_token_config(model.config, provider.type)
                    if updated is not None:
                        changes.append((model, {**identity, "before": deepcopy(model.config), "after": updated}))
                        report["rows"].append(identity)
                except (ValueError, TypeError):
                    # Config contents can contain secrets; report identifiers only.
                    report["errors"].append({**identity, "reason": "configuration_requires_review"})
            if restoring is not None:
                present = {model.id for model in models}
                for row in restoring:
                    if tenant_ids is not None and row["tenant_id"] not in tenant_ids:
                        continue
                    if row["id"] not in present:
                        report["errors"].append({"id": row["id"], "reason": "backup_model_missing"})
            report["planned"] = len(changes)
            if report["errors"]:
                await session.rollback()
                return report
            if apply and changes:
                _write_backup(backup_file, [entry for _, entry in changes])
                for model, entry in changes:
                    model.config = entry["after"]
                    session.add(model)
                await session.flush()
                for model, entry in changes:
                    await session.refresh(model, attribute_names=["config"])
                    if model.config != entry["after"]:
                        raise RuntimeError("configuration_persistence_mismatch")
                await session.commit()
                report["migrated"] = len(changes)
    return report
