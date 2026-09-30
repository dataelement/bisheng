#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""只读统计非个人知识空间的一级分类知识数及历史预览/下载覆盖率。

在 src/backend 执行：
    .venv/bin/python scripts/export_portal_category_usage.py --tenant-id 1
读取项目数据库及看板 ES 的知识空间内容统计数据集，不写数据库、不创建索引、不触发浏览埋点。
输出到新的本地目录，不覆盖已有结果；详见 scripts/README.md。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

HEADERS = ["知识分类", "知识总数", "被系统化调用数量", "调用比例"]
DATASET_INDEX = "mid_knowledge_space_content_stat"
NON_PERSONAL_LEVELS = ["public", "department", "team", "team_ks"]
BATCH_SIZE = 400


class UsageRepository:
    """只读查询入口，所有租户表由项目严格租户上下文过滤。"""

    def __init__(self, session: Any) -> None:
        from bisheng.common.models.config import Config
        from bisheng.database.models.department import Department, UserDepartment
        from bisheng.knowledge.domain.models.knowledge import Knowledge
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

        self.session = session
        self.Config, self.Space, self.Scope = Config, Knowledge, KnowledgeSpaceScope
        self.File, self.Version, self.FileDao = KnowledgeFile, KnowledgeDocumentVersion, KnowledgeFileDao
        self.Department, self.UserDepartment = Department, UserDepartment

    def department_scope(self, department_id: int) -> dict:
        """校验组织并记录同租户子树，避免空路径或模糊名称扩大统计范围。"""
        from sqlalchemy import select

        department = self.Department
        root = (
            self.session.execute(
                select(department.id, department.name, department.path).where(department.id == department_id)
            )
            .mappings()
            .one_or_none()
        )
        if root is None:
            raise ValueError("指定组织不存在或不属于当前租户")
        path = root["path"] or ""
        if not re.fullmatch(r"/(?:[1-9][0-9]*/)+", path) or not path.endswith(f"/{department_id}/"):
            raise ValueError("指定组织的层级路径无效，无法可靠识别子组织")
        departments = self.session.execute(
            select(department.id, department.name).where(department.path.like(f"{path}%")).order_by(department.id)
        ).mappings()
        return {**dict(root), "departments": [dict(row) for row in departments]}

    def categories(self, tenant_id: int) -> list[dict]:
        from sqlalchemy import select

        from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_admin_config_repository import (
            portal_admin_config_physical_key,
        )

        value = self.session.execute(
            select(self.Config.value).where(self.Config.key == portal_admin_config_physical_key(tenant_id))
        ).scalar_one_or_none()
        if not value:
            raise ValueError("未找到指定租户的门户分类配置，不能猜测分类名称")
        categories = json.loads(value).get("portal", {}).get("document_types", [])
        result = []
        seen = set()
        for item in categories:
            code = str(item.get("code") or "").strip().upper()
            label = str(item.get("label") or "").strip()
            if not code or not label or code in seen:
                raise ValueError("门户一级分类配置存在空编码、空名称或重复编码")
            seen.add(code)
            result.append({"code": code, "label": label})
        if not result:
            raise ValueError("门户未配置一级分类")
        return result

    def file_statement(self, *, inventory: bool) -> Any:
        from sqlalchemy import func, or_, select

        file, space, scope = self.File, self.Space, self.Scope
        statement = (
            select(
                file.id,
                func.coalesce(file.reference_document_id, self.version_document()).label("document_id"),
                file.file_encoding,
                file.split_rule,
            )
            .join(space, space.id == file.knowledge_id)
            .join(scope, scope.space_id == space.id)
            .where(
                space.type == 3,
                scope.level.in_(NON_PERSONAL_LEVELS),
                file.file_type == 1,
            )
        )
        if inventory:
            statement = statement.where(
                or_(space.state.is_(None), space.state != 5),
                space.is_favorite.is_(False),
                file.status == 2,
                self.FileDao.active_inventory_predicate(),
            )
        return statement

    def version_document(self) -> Any:
        from sqlalchemy import select

        return (
            select(self.Version.document_id)
            .where(self.Version.knowledge_file_id == self.File.id)
            .correlate(self.File)
            .scalar_subquery()
        )

    def inventory(self, department_scope: dict | None = None) -> list[dict]:
        from sqlalchemy import select

        statement = self.file_statement(inventory=True)
        if department_scope is not None:
            membership = self.UserDepartment
            # 只限定库存上传人；后续查历史入口时不加组织条件，以保留跨组织调用。
            # 子查询不依赖租户钩子递归注入，只使用已在顶层查询校验过租户的组织 ID。
            uploaders = select(membership.user_id).where(
                membership.is_primary == 1,
                membership.department_id.in_([row["id"] for row in department_scope["departments"]]),
            )
            statement = statement.where(self.File.user_id.in_(uploaders))
        return [dict(row) for row in self.session.execute(statement).mappings()]

    def historical_aliases(self, inventory: list[dict]) -> dict[int, tuple[str, int]]:
        """找回保留在非个人空间的旧版本和旧引用，避免仅查当前入口漏计。"""
        aliases = {int(row["id"]): identity(row) for row in inventory}
        documents = {int(row["document_id"]) for row in inventory if row["document_id"]}
        if not documents:
            return aliases
        # 流式扫描一次，避免每批文档都重新扫描全量历史入口。
        statement = self.file_statement(inventory=False).execution_options(yield_per=1000)
        for row in self.session.execute(statement).mappings():
            if row["document_id"] in documents:
                aliases[int(row["id"])] = identity(row)
        return aliases


def identity(row: Any) -> tuple[str, int]:
    from bisheng.knowledge.domain.document_identity import document_identity

    # 文档 ID 和独立文件 ID 使用不同命名空间，避免整数碰撞。
    kind, value = document_identity(row["id"], row["document_id"]).split(":")
    return kind, int(value)


def trace(message: str, *, enabled: bool) -> None:
    if enabled:
        print(f"[统计诊断] {message}", file=sys.stderr, flush=True)


def es_nodes(client: Any) -> str:
    # 仅打印节点主机和端口，禁止输出含账号密码的 URL 或请求头。
    return ", ".join(f"{node.config.host}:{node.config.port}" for node in client.transport.node_pool.all())


def create_dashboard_es_client(settings: Any) -> Any:
    from bisheng.core.search.elasticsearch.es_connection import ESConnection

    # 与应用启动时看板注册的 ES 一致，避免独立脚本的懒加载回退到原始埋点 ES。
    config = settings.get_search_conf()
    if not config.elasticsearch_url:
        raise ValueError("未配置看板 ES：vector_stores.elasticsearch.url")
    return ESConnection(config.elasticsearch_url, **config.ssl_verify).sync_es_connection


def called_file_ids(client: Any, index: str, file_ids: list[int], *, verbose: bool = False) -> set[int]:
    """合并看板预览、下载日统计，只返回任一累计次数大于零的文件 ID。"""
    trace(f"准备检查数据集索引={index} 候选文件数={len(file_ids)}", enabled=verbose)
    if not client.indices.exists(index=index):
        raise ValueError("知识空间内容统计数据集索引不存在；无法把缺少数据解释为从未调用")
    trace("已收到 ES 响应：索引存在", enabled=verbose)
    called = set()
    for offset in range(0, len(file_ids), BATCH_SIZE):
        batch = file_ids[offset : offset + BATCH_SIZE]
        filters = [
            {"terms": {"record_type": ["preview_daily", "download_daily"]}},
            {"terms": {"space_level": NON_PERSONAL_LEVELS}},
            {"terms": {"file_id": [str(file_id) for file_id in batch]}},
        ]
        batch_no = offset // BATCH_SIZE + 1
        trace(f"准备查询 ES 批次={batch_no} 文件数={len(batch)}", enabled=verbose)
        response = client.search(
            index=index,
            size=0,
            allow_partial_search_results=False,
            query={"bool": {"filter": filters}},
            aggs={
                "files": {
                    "terms": {"field": "file_id", "size": len(batch), "shard_size": len(batch)},
                    "aggs": {
                        "preview": {
                            "filter": {"term": {"record_type": "preview_daily"}},
                            "aggs": {"count": {"sum": {"field": "preview_count"}}},
                        },
                        "download": {
                            "filter": {"term": {"record_type": "download_daily"}},
                            "aggs": {"count": {"sum": {"field": "download_count"}}},
                        },
                    },
                }
            },
        )
        if (
            response.get("timed_out")
            or response.get("terminated_early")
            or response.get("_shards", {}).get("failed", 0)
        ):
            raise ValueError("统计 ES 查询超时、提前终止或分片失败，结果不完整")
        aggregation = response["aggregations"]["files"]
        if aggregation.get("sum_other_doc_count", 0) or aggregation.get("doc_count_error_upper_bound", 0):
            raise ValueError("统计 ES 聚合被截断，结果不完整")
        used = {
            int(bucket["key"])
            for bucket in aggregation["buckets"]
            if (bucket["preview"]["count"]["value"] or 0) > 0 or (bucket["download"]["count"]["value"] or 0) > 0
        }
        trace(
            f"已收到 ES 响应：批次={batch_no} 有统计记录文件数={len(aggregation['buckets'])} 已调用文件数={len(used)}",
            enabled=verbose,
        )
        called.update(used)
    trace(f"ES 查询结束：去重命中文件数={len(called)}", enabled=verbose)
    return called


def summarize(categories: list[dict], inventory: list[dict], called: set[tuple[str, int]]) -> list[list]:
    from bisheng.knowledge.domain.constants import get_file_category_code_from_file

    labels = {item["code"]: item["label"] for item in categories}
    groups: dict[str, set] = {code: set() for code in labels}
    document_categories: dict[tuple[str, int], str] = {}
    for item in inventory:
        code = get_file_category_code_from_file(item) or ""
        key = identity(item)
        if key in document_categories and document_categories[key] != code:
            raise ValueError("同一知识的有效引用存在一级分类冲突，请核对分类字段及文件编码后重试")
        document_categories[key] = code
        if code not in labels:
            labels[code] = f"未配置分类（{code}）" if code else "未分类"
        groups.setdefault(code, set()).add(key)
    rows = []
    for code, keys in groups.items():
        total, used = len(keys), len(keys & called)
        rows.append([labels[code], total, used, f"{used / total:.2%}" if total else "0.00%"])
    return rows


def markdown(rows: list[list]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    return "\n".join(
        ["| " + " | ".join(HEADERS) + " |", "| ---- | ---- | -------- | ---- |"]
        + ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    )


def write_report(directory: Path, rows: list[list], metadata: dict) -> None:
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    marker = directory / "未完成.txt"
    marker.write_text("导出未完成，请勿使用部分结果。", encoding="utf-8")
    with (directory / "知识分类调用统计.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        for label, total, used, ratio in rows:
            if label.lstrip().startswith(("=", "+", "-", "@")):
                label = "'" + label
            writer.writerow([label, total, used, ratio])
    (directory / "知识分类调用统计.md").write_text(markdown(rows) + "\n", encoding="utf-8")
    (directory / "统计口径.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    marker.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True, help="统计租户 ID，必须明确指定")
    parser.add_argument(
        "--department-id",
        type=int,
        help="按上传人当前主组织筛选，包含此组织及全部子组织；填写 department.id，省略时统计全租户",
    )
    parser.add_argument("--config", help="项目配置文件名，与后端 config 环境变量含义一致")
    parser.add_argument("--es-index", default=DATASET_INDEX, help="知识空间内容统计数据集索引或别名")
    parser.add_argument("--verbose", action="store_true", help="显示脚本路径、ES 节点、每批查询与返回数量")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs") / f"portal-category-usage-{datetime.now():%Y%m%d-%H%M%S-%f}"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.tenant_id <= 0:
        parser.error("租户 ID 必须为正整数")
    if args.department_id is not None and args.department_id <= 0:
        parser.error("组织 ID 必须为正整数")
    try:
        trace(f"执行脚本={Path(__file__).resolve()}", enabled=args.verbose)
        if args.output_dir.exists():
            raise ValueError("输出目录已存在，请指定新目录")
        if args.config:
            os.environ["config"] = args.config
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
        from bisheng.core.database import get_sync_db_session
        from bisheng.core.database.tenant_filter import register_tenant_filter_events

        started = datetime.now().astimezone()
        repository = UsageRepository(None)
        register_tenant_filter_events()
        token = set_current_tenant_id(args.tenant_id)
        try:
            with strict_tenant_filter(), get_sync_db_session() as session:
                repository.session = session
                try:
                    categories = repository.categories(args.tenant_id)
                    department_scope = (
                        repository.department_scope(args.department_id) if args.department_id is not None else None
                    )
                    if department_scope is not None:
                        trace(
                            f"上传人组织={department_scope['name']} ID={department_scope['id']} "
                            f"包含组织数={len(department_scope['departments'])}（含本组织）",
                            enabled=args.verbose,
                        )
                    inventory = repository.inventory(department_scope)
                    aliases = repository.historical_aliases(inventory)
                finally:
                    session.rollback()
            trace(f"数据库有效入口数={len(inventory)} 历史与当前入口数={len(aliases)}", enabled=args.verbose)
            client = create_dashboard_es_client(settings)
            try:
                if args.verbose:
                    trace(f"实际看板 ES 节点={es_nodes(client)}", enabled=True)
                ids = called_file_ids(client, args.es_index, sorted(aliases), verbose=args.verbose)
            finally:
                client.close()
        finally:
            current_tenant_id.reset(token)
        rows = summarize(categories, inventory, {aliases[file_id] for file_id in ids})
        metadata = {
            "开始时间": started.isoformat(),
            "完成时间": datetime.now().astimezone().isoformat(),
            "租户ID": args.tenant_id,
            "组织筛选": department_scope,
            "组织口径": (
                "按文件 user_id 对应上传人的当前主组织，包含指定组织及全部子组织；"
                "不按原始上传人、上传时组织或兼职组织；不按组织启停状态排除；无主组织的上传人不计入组织报表"
                if department_scope is not None
                else "未指定组织，统计当前租户全部非个人知识空间"
            ),
            "调用组织范围": "入选知识在当前租户全部非个人空间中的调用，包含其他组织的引用及历史入口",
            "调用来源": "知识空间内容统计数据集，包含已纳入看板的门户及毕昇工作台等来源",
            "数据集索引": args.es_index,
            "ES配置": "vector_stores.elasticsearch",
            "统计单位": "知识文件；同一文档的版本、发布和分享引用去重，独立上传不按名称或内容去重",
            "库存范围": "指定租户全部非个人知识空间；当前解析成功、未软删除的有效知识，排除历史版本及退役空间",
            "发现范围": "不按某个用户权限或空间 portal_discovery_enabled 开关过滤",
            "调用口径": "preview_daily 的 preview_count 累计大于 0，或 download_daily 的 download_count 累计大于 0 即计 1；同一知识最多计 1",
            "统计时间": "查询时数据集已落库的全部历史日统计，不按日期筛选，无法提供秒级截止快照",
            "个人库排除": "排除个人空间中的库存与调用入口；个人知识发布到非个人空间后，公开引用可计入",
            "分类口径": "与看板一致，优先 split_rule.file_category_code，缺失时解析文件编码；汇总全部二级分类",
            "比例": "被系统化调用知识数 / 知识总数；两位小数百分比；分母为零输出 0.00%",
            "有效入口数": len(inventory),
            "历史与当前入口数": len(aliases),
            "知识总数": sum(row[1] for row in rows),
            "被系统化调用数量": sum(row[2] for row in rows),
            "限制": [
                "只能识别数据集已落库的统计，未采集、未同步、已清理或上报失败的调用无法还原",
                "预览和下载日统计已合并来源，不再单独限定 shougang_portal",
                "被调用指系统记录成功提供预览或下载，不代表用户已读完或实际保存完成",
                "历史入口已物理删除或迁入个人空间时，该入口日统计不能关联计入",
                "数据库和 ES 无跨系统一致快照；建议在低峰期运行，ES 刷新延迟可能影响刚发生的调用",
            ],
        }
        write_report(args.output_dir, rows, metadata)
        print(markdown(rows))
        print(f"\n输出目录：{args.output_dir.resolve()}")
        return 0
    except Exception as exc:
        # 完整连接异常可能包含凭据，不输出连接串。
        print(f"统计失败：{type(exc).__name__}；未生成可用的新报告。", file=sys.stderr)
        if isinstance(exc, (ValueError, FileExistsError)):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
