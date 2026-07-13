# ruff: noqa: RUF001, RUF002
"""诊断用户通过部门授权访问知识空间失败的只读链路。

从 BiSheng 后端根目录执行：

    PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_space_access.py \
      --user-id 123 --space-id 3569

脚本仅读取业务数据库和 OpenFGA：不会写入数据库、Redis 或 OpenFGA tuple。
输出 JSON 包含用户部门归属、空间授权 tuple、OpenFGA member/check/
list-objects 结果，以及可用于定位部门授权链路断点的诊断结论。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from bisheng.common.models.space_channel_member import SpaceChannelMemberDao  # noqa: E402
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.openfga.client import FGAClient  # noqa: E402
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao  # noqa: E402
from bisheng.knowledge.domain.models.department_knowledge_space import (  # noqa: E402
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao  # noqa: E402
from bisheng.user.domain.models.user import UserDao  # noqa: E402

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_DEPENDENCY_ERROR = 3


@dataclass(frozen=True)
class FgaContext:
    client: FGAClient
    store_id: str
    model_id: str


def _safe_value(value: Any) -> Any:
    """将 ORM enum、datetime 等值转换为可 JSON 序列化的形式。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raw_value = getattr(value, "value", None)
    if raw_value is not None:
        return _safe_value(raw_value)
    return str(value)


def _tuple_key(value: Any) -> dict[str, str]:
    """兼容 OpenFGA client 返回的 tuple key 与 API 原始 tuple 包装。"""
    raw = value.get("key", value) if isinstance(value, dict) else {}
    return {
        "user": str(raw.get("user") or ""),
        "relation": str(raw.get("relation") or ""),
        "object": str(raw.get("object") or ""),
    }


def _department_id_from_userset(subject: str) -> int | None:
    prefix = "department:"
    suffix = "#member"
    if not subject.startswith(prefix) or not subject.endswith(suffix):
        return None
    raw_id = subject[len(prefix) : -len(suffix)]
    try:
        return int(raw_id)
    except ValueError:
        return None


def _department_record(department: Any, membership: Any | None = None) -> dict[str, Any]:
    return {
        "id": int(getattr(department, "id", 0) or 0),
        "external_id": str(getattr(department, "dept_id", "") or ""),
        "name": str(getattr(department, "name", "") or ""),
        "path": str(getattr(department, "path", "") or ""),
        "parent_id": getattr(department, "parent_id", None),
        "status": _safe_value(getattr(department, "status", None)),
        "membership": (
            {
                "is_primary": bool(getattr(membership, "is_primary", False)),
                "source": str(getattr(membership, "source", "") or ""),
                "create_time": _safe_value(getattr(membership, "create_time", None)),
            }
            if membership is not None
            else None
        ),
    }


async def _create_read_only_fga_context() -> tuple[FgaContext | None, str | None]:
    """构造仅查询的 FGA client，绝不触发 store 或 model 的自动创建。"""
    config = getattr(settings, "openfga", None)
    if config is None or not bool(getattr(config, "enabled", False)):
        return None, "OpenFGA 未启用，无法执行 OpenFGA 链路核验。"

    api_url = str(getattr(config, "api_url", "") or "").strip()
    store_id = str(getattr(config, "store_id", "") or "").strip()
    model_id = str(getattr(config, "model_id", "") or "").strip()
    if not api_url or not store_id or not model_id:
        return None, "OpenFGA 配置缺少 api_url、store_id 或 model_id；为保证只读，脚本不会自动创建或探测它们。"

    timeout = float(getattr(config, "timeout", 10) or 10)
    return FgaContext(
        client=FGAClient(api_url=api_url, store_id=store_id, model_id=model_id, timeout=timeout),
        store_id=store_id,
        model_id=model_id,
    ), None


async def _collect_database_data(user_id: int, space_id: int) -> dict[str, Any]:
    """读取定位部门授权所需的业务数据库事实。"""
    with bypass_tenant_filter():
        user_rows, space, scope, binding, memberships, user_departments = await asyncio.gather(
            UserDao.aget_user_by_ids([user_id]),
            KnowledgeDao.aquery_by_id(space_id),
            KnowledgeSpaceScopeDao.aget_by_space_id(space_id),
            DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id),
            SpaceChannelMemberDao.async_get_user_space_members(user_id),
            UserDepartmentDao.aget_user_departments(user_id),
        )

        user = next((row for row in (user_rows or []) if int(getattr(row, "user_id", 0) or 0) == user_id), None)
        department_ids = sorted(
            {int(row.department_id) for row in user_departments if getattr(row, "department_id", None)}
        )
        departments = await DepartmentDao.aget_by_ids(department_ids) if department_ids else []

    department_map = {int(row.id): row for row in departments}
    department_rows = [
        _department_record(
            department_map[department_id],
            next(
                (membership for membership in user_departments if int(membership.department_id) == department_id),
                None,
            ),
        )
        for department_id in department_ids
        if department_id in department_map
    ]
    direct_space_memberships = [
        {
            "business_id": str(getattr(member, "business_id", "") or ""),
            "business_type": _safe_value(getattr(member, "business_type", None)),
            "user_role": _safe_value(getattr(member, "user_role", None)),
            "status": _safe_value(getattr(member, "status", None)),
            "membership_source": str(getattr(member, "membership_source", "") or ""),
        }
        for member in memberships
        if str(getattr(member, "business_id", "")) == str(space_id)
    ]

    return {
        "user": {
            "id": user_id,
            "exists": user is not None,
            "account": str(getattr(user, "user_name", "") or "") if user is not None else "",
            "tenant_id": getattr(user, "tenant_id", None) if user is not None else None,
            "department_memberships": department_rows,
        },
        "space": {
            "id": space_id,
            "exists": space is not None,
            "name": str(getattr(space, "name", "") or "") if space is not None else "",
            "type": _safe_value(getattr(space, "type", None)) if space is not None else None,
            "is_knowledge_space": bool(
                space is not None and int(getattr(space, "type", 0) or 0) == KnowledgeTypeEnum.SPACE.value
            ),
            "tenant_id": getattr(space, "tenant_id", None) if space is not None else None,
            "scope": (
                {
                    "level": _safe_value(getattr(scope, "level", None)),
                    "owner_type": _safe_value(getattr(scope, "owner_type", None)),
                    "owner_id": getattr(scope, "owner_id", None),
                }
                if scope is not None
                else None
            ),
            "department_binding": (
                {
                    "department_id": int(getattr(binding, "department_id", 0) or 0),
                    "created_by": getattr(binding, "created_by", None),
                    "approval_enabled": bool(getattr(binding, "approval_enabled", False)),
                }
                if binding is not None
                else None
            ),
            "direct_user_memberships": direct_space_memberships,
        },
    }


async def _collect_fga_data(fga: FgaContext, user_id: int, space_id: int, database: dict[str, Any]) -> dict[str, Any]:
    """读取实际 OpenFGA tuple、check 与 list-objects 结果。"""
    user_key = f"user:{user_id}"
    space_key = f"knowledge_space:{space_id}"
    resource_tuples_raw, user_member_tuples_raw, can_read, viewer, objects = await asyncio.gather(
        fga.client.read_tuples(object=space_key),
        fga.client.read_tuples(user=user_key, relation="member"),
        fga.client.check(user=user_key, relation="can_read", object=space_key),
        fga.client.check(user=user_key, relation="viewer", object=space_key),
        fga.client.list_objects(user=user_key, relation="can_read", type="knowledge_space"),
    )
    resource_tuples = [_tuple_key(item) for item in resource_tuples_raw]
    user_member_tuples = [_tuple_key(item) for item in user_member_tuples_raw]
    department_viewer_ids = sorted(
        {
            department_id
            for item in resource_tuples
            if item["relation"] == "viewer"
            for department_id in [_department_id_from_userset(item["user"])]
            if department_id is not None
        }
    )
    direct_viewer_users = sorted(
        {item["user"] for item in resource_tuples if item["relation"] == "viewer" and item["user"].startswith("user:")}
    )
    member_department_ids = sorted(
        {
            int(item["object"].split(":", 1)[1])
            for item in user_member_tuples
            if item["object"].startswith("department:")
            and item["relation"] == "member"
            and item["object"].split(":", 1)[1].isdigit()
        }
    )
    database_department_ids = {
        int(item["id"]) for item in database["user"]["department_memberships"] if int(item.get("id") or 0) > 0
    }
    listed_space_ids = sorted(
        {
            int(item.split(":", 1)[1])
            for item in objects
            if item.startswith("knowledge_space:") and item.split(":", 1)[1].isdigit()
        }
    )

    return {
        "connected": True,
        "store_id": fga.store_id,
        "model_id": fga.model_id,
        "resource_tuples": resource_tuples,
        "department_viewer_grant_ids": department_viewer_ids,
        "direct_viewer_users": direct_viewer_users,
        "user_department_member_tuple_ids": member_department_ids,
        "user_database_department_ids": sorted(database_department_ids),
        "missing_member_tuple_department_ids": sorted(database_department_ids - set(member_department_ids)),
        "granted_departments_matched_in_database": sorted(database_department_ids & set(department_viewer_ids)),
        "granted_departments_matched_in_fga": sorted(set(member_department_ids) & set(department_viewer_ids)),
        "checks": {"can_read": can_read, "viewer": viewer},
        "list_objects": {
            "relation": "can_read",
            "object_type": "knowledge_space",
            "target_included": space_id in listed_space_ids,
            "count": len(listed_space_ids),
            "space_ids": listed_space_ids,
        },
    }


def _diagnose(database: dict[str, Any], fga: dict[str, Any] | None, fga_error: str | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not database["user"]["exists"]:
        findings.append({"code": "USER_NOT_FOUND", "severity": "error", "message": "用户不存在于业务数据库。"})
    if not database["space"]["exists"]:
        findings.append({"code": "SPACE_NOT_FOUND", "severity": "error", "message": "目标空间不存在于业务数据库。"})
    elif not database["space"]["is_knowledge_space"]:
        findings.append({"code": "NOT_KNOWLEDGE_SPACE", "severity": "error", "message": "目标资源不是知识空间。"})
    if fga_error:
        findings.append({"code": "OPENFGA_UNAVAILABLE", "severity": "error", "message": fga_error})
        return findings
    if fga is None:
        return findings

    if not fga["department_viewer_grant_ids"] and not fga["direct_viewer_users"]:
        findings.append(
            {
                "code": "RESOURCE_VIEWER_TUPLE_MISSING",
                "severity": "error",
                "message": "目标空间不存在部门或用户 viewer 授权 tuple。",
            }
        )
    if fga["granted_departments_matched_in_database"] and not fga["granted_departments_matched_in_fga"]:
        findings.append(
            {
                "code": "DEPARTMENT_MEMBER_TUPLE_MISSING",
                "severity": "error",
                "message": "用户在业务数据库中属于已获授权部门，但 OpenFGA 缺少对应 user→department member tuple。",
                "department_ids": fga["granted_departments_matched_in_database"],
            }
        )
    if fga["department_viewer_grant_ids"] and not fga["granted_departments_matched_in_database"]:
        findings.append(
            {
                "code": "DEPARTMENT_GRANT_DOES_NOT_COVER_USER",
                "severity": "warning",
                "message": "目标空间的部门 viewer 授权未覆盖用户数据库中的任何直接部门归属。",
            }
        )
    if fga["checks"]["can_read"] and not fga["list_objects"]["target_included"]:
        findings.append(
            {
                "code": "LIST_OBJECTS_INCONSISTENT_WITH_CHECK",
                "severity": "error",
                "message": "OpenFGA check 已允许 can_read，但 list_objects 未返回目标空间。",
            }
        )
    if not fga["checks"]["can_read"]:
        findings.append(
            {
                "code": "CAN_READ_DENIED",
                "severity": "error",
                "message": "OpenFGA 对目标空间的 can_read check 返回 false。",
            }
        )
    if fga["list_objects"]["target_included"]:
        findings.append(
            {
                "code": "OPENFGA_ACCESSIBLE",
                "severity": "info",
                "message": "目标空间已在 OpenFGA can_read list_objects 结果中。",
            }
        )
    return findings


async def _run(user_id: int, space_id: int) -> tuple[dict[str, Any], int]:
    database = await _collect_database_data(user_id, space_id)
    fga_context, fga_error = await _create_read_only_fga_context()
    fga_data: dict[str, Any] | None = None
    exit_code = EXIT_OK
    try:
        if fga_context is not None:
            try:
                fga_data = await _collect_fga_data(fga_context, user_id, space_id, database)
            except Exception as exc:
                fga_error = f"OpenFGA 查询失败：{type(exc).__name__}: {exc}"
                exit_code = EXIT_DEPENDENCY_ERROR
        else:
            exit_code = EXIT_DEPENDENCY_ERROR
    finally:
        if fga_context is not None:
            await fga_context.client.close()

    if not database["user"]["exists"] or not database["space"]["exists"]:
        exit_code = EXIT_INPUT_ERROR
    report = {
        "script": "diagnose_department_space_access",
        "mode": "read_only",
        "input": {"user_id": user_id, "space_id": space_id},
        "database": database,
        "openfga": fga_data if fga_data is not None else {"connected": False, "error": fga_error},
        "findings": _diagnose(database, fga_data, fga_error),
    }
    return report, exit_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读诊断用户通过部门授权访问知识空间的 OpenFGA 链路。")
    parser.add_argument("--user-id", type=int, required=True, help="待诊断的业务用户 ID，必须大于 0。")
    parser.add_argument("--space-id", type=int, required=True, help="待诊断的知识空间 ID，必须大于 0。")
    args = parser.parse_args()
    if args.user_id <= 0 or args.space_id <= 0:
        parser.error("--user-id 和 --space-id 必须为正整数。")
    return args


def main() -> int:
    args = _parse_args()
    report, exit_code = asyncio.run(_run(args.user_id, args.space_id))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=_safe_value))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
