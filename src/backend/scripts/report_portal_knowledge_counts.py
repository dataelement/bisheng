#!/usr/bin/env python3
"""只读统计门户全部知识空间, 导出大类、单库、一级分类及业务域 JSON.

从 src/backend 执行:
    .venv/bin/python scripts/report_portal_knowledge_counts.py --output /tmp/knowledge-counts.json
    .venv/bin/python scripts/report_portal_knowledge_counts.py --config config.yaml --tenant-id 1

只初始化数据库连接, 不启动应用、不写业务数据、不依赖 ES 或首页缓存.
输出文件必须不存在; 不提供 --apply 或覆盖模式.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import traceback
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

GROUPS = {"public": "公共库", "department": "部门库", "team": "团队库", "clinic": "科室库", "personal": "个人库"}
DocumentKey = tuple[str, int]
DimensionValues = tuple[set[str | None], set[str | None]]
Inventory = dict[int, dict[DocumentKey, DimensionValues]]


@dataclass(frozen=True)
class SpaceInfo:
    space_id: int
    name: str
    group: str
    portal_discovery_enabled: bool
    portal_discovery_only: bool
    issue: str | None = None


@dataclass(frozen=True)
class Candidate:
    file_id: int
    space_id: int
    document_key: DocumentKey
    category: str | None
    domain: str | None


class Issues:
    """异常保留总数和有限样本, 避免大型数据集产生无限明细."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, reason: str, identifier: Any) -> None:
        item = self.items.setdefault(reason, {"reason": reason, "count": 0, "samples": []})
        item["count"] += 1
        if len(item["samples"]) < 20:
            item["samples"].append(identifier)

    def build(self) -> list[dict[str, Any]]:
        return [self.items[key] for key in sorted(self.items)]


def enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def classify_space(space: Any, scope: Any, bindings: list[Any], departments: Mapping[int, Any]) -> SpaceInfo:
    """按空间类型分组, 首页资格独立复核有效部门绑定."""
    level = enum_value(getattr(scope, "level", None))
    owner_type = enum_value(getattr(scope, "owner_type", None))
    enabled = bool(getattr(scope, "portal_discovery_enabled", False))
    binding = bindings[0] if len(bindings) == 1 else None
    department = departments.get(int(binding.department_id)) if binding else None
    valid_binding = bool(
        binding
        and int(binding.space_id) == int(space.id)
        and department
        and getattr(department, "status", "active") == "active"
        and not getattr(department, "is_deleted", 0)
        and int(binding.tenant_id) == int(space.tenant_id)
        and int(department.tenant_id) == int(space.tenant_id)
    )
    group = level if level in GROUPS else "unassigned"
    if level == "team_ks" or (level == "team" and owner_type == "user" and binding):
        group = "clinic"
    eligible = level == "public" or (
        valid_binding
        and (
            (level == "department" and owner_type == "department" and int(scope.owner_id) == int(binding.department_id))
            or (level in {"team", "team_ks"} and owner_type == "user")
        )
    )
    issue = None
    if group == "unassigned":
        issue = "missing_or_unknown_space_scope"
    elif group in {"department", "clinic"} and not eligible:
        issue = "invalid_department_binding"
    elif enabled and not eligible:
        issue = "enabled_but_ineligible_space"
    return SpaceInfo(int(space.id), space.name, group, enabled, bool(enabled and eligible), issue)


async def load_spaces(session: Any) -> dict[int, SpaceInfo]:
    from sqlalchemy import or_
    from sqlmodel import select

    from bisheng.database.models.department import Department
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

    spaces = (
        await session.exec(
            select(Knowledge).where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                or_(Knowledge.state.is_(None), Knowledge.state != KnowledgeState.DELETING.value),
            )
        )
    ).all()
    scopes = {int(row.space_id): row for row in (await session.exec(select(KnowledgeSpaceScope))).all()}
    bindings: dict[int, list[Any]] = defaultdict(list)
    for row in (await session.exec(select(DepartmentKnowledgeSpace))).all():
        bindings[int(row.space_id)].append(row)
    departments = {int(row.id): row for row in (await session.exec(select(Department))).all()}
    return {
        int(space.id): classify_space(space, scopes.get(int(space.id)), bindings[int(space.id)], departments)
        for space in spaces
    }


async def iter_candidates(
    session: Any, spaces: Mapping[int, SpaceInfo], issues: Issues, page_size: int = 500
) -> AsyncIterator[Candidate]:
    """分页读取有效入口; 每页批量解析文档身份, 不逐文件查询."""
    from sqlalchemy import or_
    from sqlmodel import col, select

    from bisheng.knowledge.domain.constants import get_business_domain_code_from_file, get_file_category_code_from_file
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import (
        FileType,
        KnowledgeFile,
        KnowledgeFileDao,
        KnowledgeFileStatus,
    )

    if not 1 <= page_size <= 500:
        raise ValueError("page_size 必须介于 1 和 500 之间")
    last_id = 0
    while True:
        statement = (
            select(
                KnowledgeFile.id,
                KnowledgeFile.knowledge_id,
                KnowledgeFile.reference_document_id,
                KnowledgeFile.split_rule,
                KnowledgeFile.file_encoding,
            )
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .where(
                KnowledgeFile.id > last_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                or_(Knowledge.state.is_(None), Knowledge.state != KnowledgeState.DELETING.value),
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                KnowledgeFileDao.active_inventory_predicate(),
                or_(
                    KnowledgeFile.entry_type.is_(None),
                    col(KnowledgeFile.entry_type).in_(["manager", "publish", "share"]),
                ),
                or_(KnowledgeFile.entry_status.is_(None), KnowledgeFile.entry_status == "active"),
            )
            .order_by(KnowledgeFile.id.asc())
            .limit(page_size)
        )
        rows = (await session.exec(statement)).all()
        if not rows:
            return
        versions = {
            int(row.knowledge_file_id): row
            for row in (
                await session.exec(
                    select(KnowledgeDocumentVersion).where(
                        col(KnowledgeDocumentVersion.knowledge_file_id).in_([int(row.id) for row in rows])
                    )
                )
            ).all()
        }
        document_ids = {int(row.reference_document_id) for row in rows if row.reference_document_id}
        document_ids.update(int(version.document_id) for version in versions.values())
        documents = {}
        # 一页最多涉及两倍数量的文档 ID, 分批避免 DM8 的 IN 参数限制.
        sorted_ids = sorted(document_ids)
        for offset in range(0, len(sorted_ids), page_size):
            documents.update(
                {
                    int(row.id): row
                    for row in (
                        await session.exec(
                            select(KnowledgeDocument).where(
                                col(KnowledgeDocument.id).in_(sorted_ids[offset : offset + page_size])
                            )
                        )
                    ).all()
                }
            )
        for row in rows:
            file_id, space_id, reference_id, split_rule, encoding = row
            if int(space_id) not in spaces:
                issues.add("space_changed_during_scan", int(file_id))
                continue
            version = versions.get(int(file_id))
            if version and reference_id and int(version.document_id) != int(reference_id):
                issues.add("document_reference_mismatch", int(file_id))
                continue
            document_id = int(reference_id or (version.document_id if version else 0))
            if document_id:
                document = documents.get(document_id)
                if document is None or document.lifecycle_status != "active":
                    issues.add("missing_or_inactive_document", int(file_id))
                    continue
                if version and document.primary_version_id != version.id:
                    issues.add("primary_version_mismatch", int(file_id))
                    continue
            item = {"split_rule": split_rule, "file_encoding": encoding}
            yield Candidate(
                int(file_id),
                int(space_id),
                ("document", document_id) if document_id else ("file", int(file_id)),
                get_file_category_code_from_file(item),
                get_business_domain_code_from_file(item),
            )
        last_id = int(rows[-1].id)


def aggregate(inventory: Inventory, space_ids: Iterable[int]) -> dict[str, Any]:
    """每个逻辑文档在当前分组仅归入一个维度桶, 冲突单列以保持总数守恒."""
    documents: dict[DocumentKey, dict[str, Any]] = {}
    for space_id in space_ids:
        for key, values in inventory.get(space_id, {}).items():
            document = documents.setdefault(key, {"spaces": 0, "values": (set(), set())})
            document["spaces"] += 1
            for index in (0, 1):
                document["values"][index].update(values[index])
    dimensions = []
    for index in (0, 1):
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for document_key, document in documents.items():
            values = document["values"][index]
            if len(values) != 1:
                kind, code = "conflict", ""
            elif next(iter(values)) is None:
                kind, code = "unclassified", ""
            else:
                kind, code = "value", next(iter(values))
            bucket = buckets.setdefault(
                (kind, code),
                {
                    "kind": kind,
                    "code": code or None,
                    "summed_count": 0,
                    "distinct_count": 0,
                },
            )
            bucket["summed_count"] += document["spaces"]
            bucket["distinct_count"] += 1
            if kind == "conflict":
                samples = bucket.setdefault("document_samples", [])
                if len(samples) < 20:
                    samples.append({"kind": document_key[0], "id": document_key[1]})
        dimensions.append([buckets[key] for key in sorted(buckets)])
    return {
        "summed_count": sum(document["spaces"] for document in documents.values()),
        "distinct_count": len(documents),
        "by_category": dimensions[0],
        "by_business_domain": dimensions[1],
    }


class ReportBuilder:
    def __init__(self, spaces: Mapping[int, SpaceInfo], issues: Issues) -> None:
        self.spaces = spaces
        self.issues = issues
        self.inventory: Inventory = {}
        for space in spaces.values():
            if space.issue:
                issues.add(space.issue, space.space_id)

    def add(self, candidate: Candidate) -> None:
        if candidate.space_id not in self.spaces:
            raise ValueError(f"未知空间: {candidate.space_id}")
        values = self.inventory.setdefault(candidate.space_id, {}).setdefault(candidate.document_key, (set(), set()))
        values[0].add(candidate.category)
        values[1].add(candidate.domain)

    def build(self, tenant_id: int, started_at: str) -> dict[str, Any]:
        groups = []
        labels = {**GROUPS, "unassigned": "未归类空间"}
        for group, name in labels.items():
            spaces = sorted((s for s in self.spaces.values() if s.group == group), key=lambda s: s.space_id)
            if group == "unassigned" and not spaces:
                continue
            counts = aggregate(self.inventory, [s.space_id for s in spaces])
            groups.append(
                {
                    "group": group,
                    "name": name,
                    "space_count": len(spaces),
                    "portal_enabled_space_count": sum(s.portal_discovery_enabled for s in spaces),
                    "portal_discovery_space_count": sum(s.portal_discovery_only for s in spaces),
                    "counts": counts,
                    "spaces": []
                    if group == "personal"
                    else [
                        {
                            "space_id": s.space_id,
                            "name": s.name,
                            "portal_discovery_enabled": s.portal_discovery_enabled,
                            "portal_discovery_only": s.portal_discovery_only,
                            "counts": aggregate(self.inventory, [s.space_id]),
                        }
                        for s in spaces
                    ],
                }
            )
        summary = aggregate(self.inventory, self.spaces)
        report = {
            "schema_version": 1,
            "started_at": started_at,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "tenant_id": tenant_id,
            "counting_rules": {
                "source": "database",
                "scope": "all_current_knowledge_spaces",
                "file_status": "SUCCESS",
                "personal_spaces": "merged",
                "includes_favorite_spaces": True,
                "deduplication": "logical_document_id; legacy files without a document use file_id in a separate namespace",
                "summed_count": "sum of per-space distinct document counts",
                "distinct_count": "distinct document count within the current group",
                "dimensions": "split_rule first, file_encoding fallback; missing values use unclassified",
                "conflicts": "a document with differing dimension values within a group goes to conflict once; summed_count retains its space multiplicity",
                "portal_discovery_only": "effective homepage space eligibility, not a filter on this report",
                "consistency": "one read transaction using database isolation; concurrent changes may affect the scan",
            },
            "summary": {"space_count": len(self.spaces), "counts": summary},
            "groups": groups,
            "anomalies": self.issues.build(),
        }
        validate_report(report)
        return report


def validate_report(report: Mapping[str, Any]) -> None:
    nodes = [report["summary"]["counts"]]
    for group in report["groups"]:
        nodes.append(group["counts"])
        nodes.extend(space["counts"] for space in group["spaces"])
        if (
            group["group"] != "personal"
            and sum(s["counts"]["summed_count"] for s in group["spaces"]) != group["counts"]["summed_count"]
        ):
            raise ValueError("单库数量与大类汇总不一致")
    if sum(g["counts"]["summed_count"] for g in report["groups"]) != report["summary"]["counts"]["summed_count"]:
        raise ValueError("大类数量与全局汇总不一致")
    for counts in nodes:
        if not 0 <= counts["distinct_count"] <= counts["summed_count"]:
            raise ValueError("去重数量不合法")
        for dimension in ("by_category", "by_business_domain"):
            for metric in ("summed_count", "distinct_count"):
                if sum(bucket[metric] for bucket in counts[dimension]) != counts[metric]:
                    raise ValueError(f"{dimension} 的 {metric} 与总数不一致")


def write_report(report: Mapping[str, Any], target: Path) -> None:
    """完整写入临时文件后创建目标链接, 并发情况下也不覆盖已有文件."""
    validate_report(report)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def load_dimension_names(session: Any, tenant_id: int) -> dict[str, dict[str, str]]:
    """只读加载名称字典, 不调用会访问或写入 Redis 缓存的配置接口."""
    import yaml
    from sqlmodel import col, select

    from bisheng.common.models.config import Config, ConfigKeyEnum
    from bisheng.core.config.settings import DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES
    from bisheng.knowledge.domain.constants import BUSINESS_DOMAIN_OPTIONS
    from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_admin_config_repository import (
        portal_admin_config_physical_key,
    )

    def labels(items: Any, field: str) -> dict[str, str]:
        if not isinstance(items, list):
            return {}
        return {
            item["code"].strip().upper(): item[field].strip()
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("code"), str)
            and item["code"].strip()
            and isinstance(item.get(field), str)
            and item[field].strip()
        }

    portal_key = portal_admin_config_physical_key(tenant_id)
    rows = (
        await session.exec(select(Config).where(col(Config.key).in_([portal_key, ConfigKeyEnum.INIT_DB.value])))
    ).all()
    stored = {row.key: row.value for row in rows}
    system_config = yaml.safe_load(stored.get(ConfigKeyEnum.INIT_DB.value) or "{}")
    portal_config = json.loads(stored.get(portal_key) or "{}")
    if not isinstance(system_config, dict) or not isinstance(portal_config, dict):
        raise ValueError("名称字典配置必须是对象")
    portal = portal_config.get("portal") or {}
    encoding = (system_config.get("shougang") or {}).get("file_encoding") or {}
    # 优先级: 内置字典 < 系统配置 < 门户卡片 < 门户文件分类字典.
    categories = labels(DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES, "label")
    categories.update(labels(encoding.get("document_types"), "label"))
    categories.update(labels(portal.get("category_cards"), "name"))
    categories.update(labels(portal.get("document_types"), "label"))
    domains = dict(BUSINESS_DOMAIN_OPTIONS)
    domains.update(labels(portal.get("domains"), "name"))
    return {"by_category": categories, "by_business_domain": domains}


def attach_dimension_names(report: dict[str, Any], names: Mapping[str, Mapping[str, str]]) -> None:
    """为全局、大类及单库的每个统计项补充名称, 保留原编码和计数."""
    nodes = [report["summary"]["counts"]]
    for group in report["groups"]:
        nodes.append(group["counts"])
        nodes.extend(space["counts"] for space in group["spaces"])
    for counts in nodes:
        for dimension, title in (("by_category", "分类"), ("by_business_domain", "业务域")):
            for bucket in counts[dimension]:
                if bucket["kind"] == "unclassified":
                    name = "未分类" if dimension == "by_category" else "未指定业务域"
                elif bucket["kind"] == "conflict":
                    name = f"{title}冲突"
                else:
                    code = bucket["code"]
                    name = names[dimension].get(code, f"未知{title} ({code})")
                bucket["name"] = name


async def generate_report(session: Any, tenant_id: int, page_size: int) -> dict[str, Any]:
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    issues = Issues()
    spaces = await load_spaces(session)
    builder = ReportBuilder(spaces, issues)
    async for candidate in iter_candidates(session, spaces, issues, page_size):
        builder.add(candidate)
    report = builder.build(tenant_id, started_at)
    attach_dimension_names(report, await load_dimension_names(session, tenant_id))
    return report


async def run(args: argparse.Namespace) -> Path:
    # 配置参数必须在首次导入项目模块前生效.
    if args.config:
        os.environ["config"] = args.config
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import (
        DEFAULT_TENANT_ID,
        current_tenant_id,
        set_current_tenant_id,
        strict_tenant_filter,
    )
    from bisheng.core.database import get_async_db_session
    from bisheng.core.database.manager import get_database_connection
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    if args.tenant_id is None and settings.multi_tenant.enabled:
        raise ValueError("多租户环境必须显式指定 --tenant-id")
    tenant_id = args.tenant_id or DEFAULT_TENANT_ID
    if not settings.multi_tenant.enabled and tenant_id != DEFAULT_TENANT_ID:
        raise ValueError("单租户环境只能统计默认租户")
    target = Path(args.output).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"输出文件已存在: {target}")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在: {target.parent}")
    token = set_current_tenant_id(tenant_id)
    connection = None
    try:
        register_tenant_filter_events()
        connection = await get_database_connection()
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                report = await generate_report(session, tenant_id, args.page_size)
                await session.rollback()
        write_report(report, target)
        counts = report["summary"]["counts"]
        print(
            f"统计完成: summed_count={counts['summed_count']}, distinct_count={counts['distinct_count']}, output={target}"
        )
        return target
    finally:
        current_tenant_id.reset(token)
        if connection is not None:
            await connection.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="配置文件名或路径, 默认沿用 config 环境变量")
    parser.add_argument("--tenant-id", type=int, help="租户 ID; 多租户模式必填")
    parser.add_argument("--page-size", type=int, default=500, help="每批读取文件数量, 1-500")
    parser.add_argument("--output", default="portal_knowledge_counts.json", help="JSON 输出路径, 不覆盖已有文件")
    args = parser.parse_args(argv)
    if not 1 <= args.page_size <= 500:
        parser.error("--page-size 必须介于 1 和 500 之间")
    if args.tenant_id is not None and args.tenant_id <= 0:
        parser.error("--tenant-id 必须是正整数")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(run(args))
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
