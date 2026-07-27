"""只读检查 F059 单实体发布/分享上线前不变量。

从 ``src/backend`` 执行:

    PYTHONPATH=./ .venv/bin/python \
      scripts/knowledge_document_distribution_preflight.py

脚本只读取数据库与当前对象路径规则, 不修改业务数据、不访问 MinIO。
发现租户归属不确定、重复物理版本关系、旧复制发布痕迹、空间相关对象键或
F059 入口不变量异常时返回退出码 2, 用于阻断 writer 开关。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.services.knowledge_utils import (  # noqa: E402
    KnowledgeUtils,
)

MAX_SAMPLES = 20


def _row_mapping(row) -> dict[str, Any]:
    return dict(row._mapping)


def _sample_ids(rows: Iterable, field: str) -> list[int]:
    samples: list[int] = []
    for row in rows:
        value = row._mapping.get(field)
        if value is not None:
            samples.append(int(value))
        if len(samples) >= MAX_SAMPLES:
            break
    return samples


def _metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def run_preflight(connection: Connection) -> dict[str, Any]:
    """Run read-only checks against one existing schema."""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    issues: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {}

    required_tables = {
        "knowledge",
        "knowledgefile",
        "knowledge_document",
        "knowledge_document_version",
    }
    missing_tables = sorted(required_tables - table_names)
    checks["required_tables"] = {
        "status": "pass" if not missing_tables else "block",
        "missing": missing_tables,
    }
    if missing_tables:
        issues.append(
            {
                "code": "missing_required_tables",
                "count": len(missing_tables),
                "samples": missing_tables,
            }
        )
        return {
            "feature": "F059",
            "status": "block",
            "checked_at": datetime.now().isoformat(),
            "checks": checks,
            "issues": issues,
        }

    duplicate_rows = list(
        connection.execute(
            text(
                """
                SELECT knowledge_file_id,
                       COUNT(*) AS relation_count,
                       COUNT(DISTINCT document_id) AS document_count
                FROM knowledge_document_version
                GROUP BY knowledge_file_id
                HAVING COUNT(*) > 1
                """
            )
        )
    )
    checks["unique_version_file"] = {
        "status": "pass" if not duplicate_rows else "block",
        "count": len(duplicate_rows),
    }
    if duplicate_rows:
        issues.append(
            {
                "code": "duplicate_version_file_relation",
                "count": len(duplicate_rows),
                "samples": _sample_ids(
                    duplicate_rows,
                    "knowledge_file_id",
                ),
            }
        )

    document_columns = {
        item["name"]
        for item in inspector.get_columns("knowledge_document")
    }
    document_tenant_expr = (
        "d.tenant_id" if "tenant_id" in document_columns else "NULL"
    )
    tenant_rows = list(
        connection.execute(
            text(
                f"""
                SELECT d.id AS document_id,
                       {document_tenant_expr} AS document_tenant_id,
                       COUNT(DISTINCT COALESCE(f.tenant_id, k.tenant_id))
                           AS inferred_tenant_count,
                       MIN(COALESCE(f.tenant_id, k.tenant_id))
                           AS inferred_tenant_id
                FROM knowledge_document d
                LEFT JOIN knowledge_document_version v
                       ON v.document_id = d.id
                LEFT JOIN knowledgefile f
                       ON f.id = v.knowledge_file_id
                LEFT JOIN knowledge k
                       ON k.id = f.knowledge_id
                GROUP BY d.id, {document_tenant_expr}
                HAVING COUNT(
                           DISTINCT COALESCE(f.tenant_id, k.tenant_id)
                       ) <> 1
                    OR SUM(
                        CASE
                            WHEN v.id IS NULL
                              OR f.id IS NULL
                              OR k.id IS NULL
                              OR f.knowledge_id <> d.knowledge_id
                              OR f.tenant_id IS NULL
                              OR k.tenant_id IS NULL
                              OR f.tenant_id <> k.tenant_id
                            THEN 1
                            ELSE 0
                        END
                    ) > 0
                    OR (
                        {document_tenant_expr} IS NOT NULL
                        AND {document_tenant_expr}
                            <> MIN(COALESCE(f.tenant_id, k.tenant_id))
                    )
                """
            )
        )
    )
    checks["deterministic_document_tenant"] = {
        "status": "pass" if not tenant_rows else "block",
        "count": len(tenant_rows),
    }
    if tenant_rows:
        issues.append(
            {
                "code": "document_tenant_not_deterministic",
                "count": len(tenant_rows),
                "samples": _sample_ids(tenant_rows, "document_id"),
            }
        )

    file_columns = {
        item["name"] for item in inspector.get_columns("knowledgefile")
    }
    metadata_rows = connection.execute(
        text(
            """
            SELECT id, knowledge_id, user_metadata
            FROM knowledgefile
            WHERE user_metadata IS NOT NULL
            """
        ).execution_options(stream_results=True)
    )
    legacy_copy_ids: list[int] = []
    space_key_ids: list[int] = []
    for row in metadata_rows:
        payload = _metadata_text(row._mapping["user_metadata"])
        file_id = int(row._mapping["id"])
        if "shougang_portal_publish" in payload:
            legacy_copy_ids.append(file_id)
        knowledge_id = row._mapping["knowledge_id"]
        if (
            knowledge_id is not None
            and f"knowledge/images/{int(knowledge_id)}/" in payload
        ):
            space_key_ids.append(file_id)

    stable_probe = KnowledgeUtils.get_knowledge_file_image_dir(
        "file-probe",
        991337,
    )
    image_rule_is_stable = "991337" not in stable_probe
    if not image_rule_is_stable:
        space_key_ids.append(0)
    checks["legacy_copy_publish"] = {
        "status": "pass" if not legacy_copy_ids else "block",
        "count": len(legacy_copy_ids),
    }
    if legacy_copy_ids:
        issues.append(
            {
                "code": "legacy_copy_publish_data",
                "count": len(legacy_copy_ids),
                "samples": legacy_copy_ids[:MAX_SAMPLES],
            }
        )
    checks["space_independent_object_keys"] = {
        "status": "pass" if not space_key_ids else "block",
        "count": len(space_key_ids),
        "image_path_probe": stable_probe,
    }
    if space_key_ids:
        issues.append(
            {
                "code": "space_dependent_object_key",
                "count": len(space_key_ids),
                "samples": space_key_ids[:MAX_SAMPLES],
            }
        )

    distribution_columns = {
        "reference_document_id",
        "entry_type",
        "entry_status",
    }
    if distribution_columns.issubset(file_columns):
        manager_rows = list(
            connection.execute(
                text(
                    """
                    SELECT reference_document_id AS document_id
                    FROM knowledgefile
                    WHERE reference_document_id IS NOT NULL
                    GROUP BY reference_document_id
                    HAVING
                        SUM(
                            CASE
                                WHEN entry_status = 'active' THEN 1
                                ELSE 0
                            END
                        ) > 0
                        AND SUM(
                            CASE
                                WHEN entry_type = 'manager'
                                 AND entry_status = 'active'
                                THEN 1
                                ELSE 0
                            END
                        ) <> 1
                    """
                )
            )
        )
        duplicate_entry_rows = list(
            connection.execute(
                text(
                    """
                    SELECT reference_document_id AS document_id,
                           knowledge_id
                    FROM knowledgefile
                    WHERE reference_document_id IS NOT NULL
                      AND entry_status IN ('preparing', 'active', 'deleting')
                    GROUP BY reference_document_id, knowledge_id
                    HAVING COUNT(*) > 1
                    """
                )
            )
        )
        physical_predicates = [
            "object_name IS NOT NULL",
            "preview_file_object_name IS NOT NULL",
            "bbox_object_name IS NOT NULL AND bbox_object_name <> ''",
            "thumbnails IS NOT NULL AND thumbnails <> ''",
            "COALESCE(file_size, 0) <> 0",
            "md5 IS NOT NULL",
        ]
        logical_physical_rows = list(
            connection.execute(
                text(
                    """
                    SELECT id
                    FROM knowledgefile
                    WHERE entry_type IN (
                        'publish',
                        'share',
                        'projection_tombstone'
                    )
                      AND (
                    """
                    + " OR ".join(physical_predicates)
                    + ")"
                )
            )
        )
        checks["single_active_manager"] = {
            "status": "pass" if not manager_rows else "block",
            "count": len(manager_rows),
        }
        checks["single_entry_per_space"] = {
            "status": "pass" if not duplicate_entry_rows else "block",
            "count": len(duplicate_entry_rows),
        }
        checks["logical_entry_has_no_physical_payload"] = {
            "status": "pass" if not logical_physical_rows else "block",
            "count": len(logical_physical_rows),
        }
        for code, rows, field in (
            ("invalid_active_manager_count", manager_rows, "document_id"),
            (
                "duplicate_document_entry_in_space",
                duplicate_entry_rows,
                "document_id",
            ),
            (
                "logical_entry_contains_physical_payload",
                logical_physical_rows,
                "id",
            ),
        ):
            if rows:
                issues.append(
                    {
                        "code": code,
                        "count": len(rows),
                        "samples": _sample_ids(rows, field),
                    }
                )
    else:
        checks["distribution_columns"] = {
            "status": "not_installed",
            "missing": sorted(distribution_columns - file_columns),
        }

    return {
        "feature": "F059",
        "status": "pass" if not issues else "block",
        "checked_at": datetime.now().isoformat(),
        "checks": checks,
        "issues": issues,
    }


async def _run() -> dict[str, Any]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            async_connection = await session.connection()
            return await async_connection.run_sync(run_preflight)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report = asyncio.run(_run())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "feature": "F059",
                    "status": "error",
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
