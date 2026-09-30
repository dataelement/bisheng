#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""只读导出制造部科室知识、登录和问答指标及核对 CSV。

在 src/backend 执行：
    .venv/bin/python scripts/export_office_metrics.py --tenant-id 1 \
        --company-department-id 100 --manufacturing-department-id 200 \
        --output-dir /app/office-metrics --verbose
组织 ID 需替换为真实值。仅读数据库/ES，写入新的本地目录，不存在 apply/迁移模式。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def document_identity(file_id: int, document_id: Any = None) -> str:
    if int(file_id) <= 0 or (document_id is not None and int(document_id) <= 0):
        raise ValueError("知识统计身份必须为正整数")
    return f"document:{int(document_id)}" if document_id is not None else f"file:{int(file_id)}"


OFFICES = (
    "综合管理室(制造)",
    "汽车板室(制造)",
    "热轧产品室(制造)",
    "质量精益室(制造)",
    "铁前室(制造)",
    "生产计划室(制造)",
    "物流管控中心(制造)",
    "生产管控中心(制造)",
    "智能制造室(制造)",
    "低碳管理室(制造)",
)
LEVELS = {"public": "公共库", "department": "部门库", "team_ks": "科室库", "team": "团队库", "personal": "个人库"}
QA = {"smart": "智能问答数", "document": "文档问答", "expert": "专家问答数"}
HEADERS = ["序号", "科室", *LEVELS.values(), "贡献数", "贡献比", "登录次数", "访问比", *QA.values(), "问答比", "备注"]


class ReportError(ValueError):
    """可安全展示的报表校验错误，不携带连接异常原文。"""


def positive(value: Any, label: str) -> int:
    try:
        if isinstance(value, bool) or str(value).strip() != str(int(value)) or int(value) <= 0:
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        raise ReportError(f"{label}必须为正整数") from None


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("（", "(").replace("）", ")"))


class OrganizationScope:
    """按当前父组织关系构建统计路径，不回写数据库或模糊推断人员归属。"""

    def __init__(
        self,
        departments: list[dict],
        memberships: list[dict],
        company_id: int,
        manufacturing_id: int,
        office_map: dict | None = None,
    ) -> None:
        self.departments = {positive(d["id"], "组织ID"): dict(d) for d in departments}
        if len(self.departments) != len(departments):
            raise ReportError("组织 ID 重复")
        self.company_id, self.manufacturing_id = company_id, manufacturing_id
        paths: dict[int, str] = {}
        self.path_differences: list[tuple[int, str, str]] = []
        for org_id in self.departments:
            chain: list[int] = []
            seen: set[int] = set()
            current: int | None = org_id
            while current is not None and current not in paths:
                if current in seen:
                    raise ReportError(f"组织父链存在环：{current}")
                if current not in self.departments:
                    raise ReportError(f"组织父组织不存在于指定租户：{chain[-1]} -> {current}")
                seen.add(current)
                chain.append(current)
                parent = self.departments[current].get("parent_id")
                current = positive(parent, "父组织ID") if parent is not None else None
            path = paths[current] if current is not None else "/"
            for node_id in reversed(chain):
                path += f"{node_id}/"
                paths[node_id] = path
        for org_id, path in paths.items():
            department = self.departments[org_id]
            stored_path = department.get("path") or ""
            if stored_path != path:
                self.path_differences.append((org_id, stored_path, path))
            department["path"] = path
        if company_id not in self.departments or manufacturing_id not in self.departments:
            raise ReportError("公司或制造部组织不存在于指定租户")
        self.company_path = self.departments[company_id]["path"]
        self.manufacturing_path = self.departments[manufacturing_id]["path"]
        if company_id == manufacturing_id or not self.manufacturing_path.startswith(self.company_path):
            raise ReportError("制造部必须是公司下属组织")
        office_map = office_map or {}
        if set(office_map) - set(OFFICES):
            raise ReportError("科室映射含未知表格行名")
        self.office_ids = []
        for name in OFFICES:
            candidates = [
                d["id"]
                for d in self.departments.values()
                if d["path"].startswith(self.manufacturing_path) and normalize_name(d["name"]) == normalize_name(name)
            ]
            org_id = positive(office_map[name], "科室ID") if name in office_map else None
            if org_id is None:
                if len(candidates) != 1:
                    raise ReportError(f"科室无法唯一匹配：{name}；请用 --office-map 指定组织 ID")
                org_id = candidates[0]
            if (
                org_id not in self.departments
                or org_id == manufacturing_id
                or not self.departments[org_id]["path"].startswith(self.manufacturing_path)
            ):
                raise ReportError(f"科室不属于制造部：{name}")
            self.office_ids.append(org_id)
        paths = [self.departments[i]["path"] for i in self.office_ids]
        if any(a.startswith(b) for i, a in enumerate(paths) for j, b in enumerate(paths) if i != j):
            raise ReportError("表中科室组织范围重叠，不能重复归属人员")
        self.names = dict(zip(self.office_ids, OFFICES, strict=True))
        self.members = {}
        for row in memberships:
            uid = positive(row["user_id"], "用户ID")
            if uid in self.members:
                raise ReportError(f"用户主组织不唯一：{uid}")
            self.members[uid] = row

    def locate(self, user_id: int) -> dict:
        member = self.members.get(user_id, {})
        dep = self.departments.get(member.get("department_id"))
        result = {
            "user_id": user_id,
            "user_name": member.get("user_name", ""),
            "department_id": "",
            "department_path": "",
            "group": "",
            "company": 0,
            "manufacturing": 0,
            "reason": "无当前主组织",
        }
        if dep is None:
            return result
        path = dep["path"]
        result.update(department_id=dep["id"], department_path=path, reason="公司范围外")
        if not path.startswith(self.company_path):
            return result
        result.update(company=1, reason="", group="公司其他组织")
        if not path.startswith(self.manufacturing_path):
            return result
        result["manufacturing"] = 1
        for org_id in self.office_ids:
            if path.startswith(self.departments[org_id]["path"]):
                result["group"] = str(org_id)
                return result
        chain = [int(part) for part in path.strip("/").split("/")]
        chain = chain[chain.index(self.manufacturing_id) + 1 :]
        offices = [i for i in chain if self.departments.get(i, {}).get("org_level") == "office"]
        group = offices[-1] if offices else (chain[0] if chain else self.manufacturing_id)
        self.names[group] = self.departments[group]["name"] if chain else "制造部直属人员"
        result["group"] = str(group)
        return result

    def relevant_user(self, user_id: int) -> bool:
        location = self.locate(user_id)
        # 归属未知保留诊断。明确属于其他公司的人员不进入本公司的行为报表。
        return bool(location["company"]) or location["reason"] == "无当前主组织"


@dataclass
class Bucket:
    documents: dict[str, set[str]] = field(default_factory=lambda: {level: set() for level in LEVELS})
    department_documents: set[str] = field(default_factory=set)
    login_count: int = 0
    questions: dict[str, int] = field(default_factory=lambda: dict.fromkeys(QA, 0))

    @property
    def total_documents(self) -> int:
        return len(set().union(*self.documents.values()))

    @property
    def total_questions(self) -> int:
        return sum(self.questions.values())


class Metrics:
    def __init__(self, scope: OrganizationScope, diagnose: Callable | None = None) -> None:
        self.scope = scope
        self.diagnose = diagnose or (lambda *args: None)
        self.buckets: dict[str, Bucket] = defaultdict(Bucket)
        self.department_documents: set[str] = set()
        self.login_events: dict[str, tuple] = {}
        self.question_events: dict[tuple[str, str], int] = {}
        self.document_users: dict[str, set[int]] = defaultdict(set)
        self.unknown_users: set[int] = set()
        self.membership_warnings: set[int] = set()
        self.has_warnings = False
        self.qa_history_note = ""

    def groups(self, user_id: int) -> tuple[dict, list[Bucket]]:
        location = self.scope.locate(user_id)
        member = self.scope.members.get(user_id, {})
        if member and member.get("tenant_member") is False and user_id not in self.membership_warnings:
            self.membership_warnings.add(user_id)
            self.has_warnings = True
            self.diagnose("WARNING", "组织", str(user_id), "缺少租户成员关系，仍按已隔离的当前主组织归属统计")
        if location["reason"] == "无当前主组织" and user_id not in self.unknown_users:
            self.unknown_users.add(user_id)
            self.has_warnings = True
            self.diagnose("WARNING", "组织", str(user_id), "无当前主组织，不能判断公司归属；不计入人员范围指标")
        keys = []
        if location["company"]:
            keys.append("company")
        if location["manufacturing"]:
            keys.extend(["manufacturing", location["group"]])
        return location, [self.buckets[key] for key in keys]

    def file(self, row: dict) -> dict:
        user_id = positive(row["user_id"], "上传人ID")
        level = row["level"]
        if level not in LEVELS:
            raise ReportError("未知库类型")
        identity = document_identity(positive(row["file_id"], "文件ID"), row.get("document_id"))
        location, buckets = self.groups(user_id)
        department_library = (
            level == "department"
            and row["owner_type"] == "department"
            and int(row["owner_id"]) == self.scope.manufacturing_id
        )
        if department_library:
            self.department_documents.add(identity)
        for bucket in buckets:
            bucket.documents[level].add(identity)
            if department_library:
                bucket.department_documents.add(identity)
        owners = self.document_users[identity]
        if owners and user_id not in owners:
            self.has_warnings = True
            self.diagnose("WARNING", "知识", identity, "同一文档入口存在不同上传人；科室分别归属，部门与公司合并去重")
        owners.add(user_id)
        return {**row, **location, "identity": identity, "department_library": int(department_library), "counted": 1}

    def login(self, row: dict) -> dict:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            raise ReportError("登录事件缺少稳定事件 ID")
        user_id = positive(row["user_id"], "登录人ID")
        fingerprint = (user_id, row["timestamp"])
        location, buckets = self.groups(user_id)
        if event_id in self.login_events:
            if self.login_events[event_id] != fingerprint:
                raise ReportError(f"登录事件身份冲突：{event_id}")
            return {**row, **location, "counted": 0}
        self.login_events[event_id] = fingerprint
        for bucket in buckets:
            bucket.login_count += 1
        return {**row, **location, "counted": 1}

    def question(self, row: dict) -> dict:
        qa_type = row["qa_type"]
        question_id = str(row.get("question_id") or "").strip()
        if qa_type not in QA or not question_id:
            raise ReportError("问答类型未知或缺少稳定问题 ID")
        user_id = positive(row["user_id"], "提问人ID")
        key = (qa_type, question_id)
        location, buckets = self.groups(user_id)
        if key in self.question_events:
            if self.question_events[key] != user_id:
                raise ReportError(f"问答身份归属冲突：{qa_type}/{question_id}")
            return {**row, **location, "counted": 0}
        self.question_events[key] = user_id
        for bucket in buckets:
            bucket.questions[qa_type] += 1
        return {**row, **location, "counted": 1}

    def reports(self) -> tuple[list[dict], list[dict], list[dict]]:
        summary, other, ratios = [], [], []
        office_login = sum(self.buckets[str(i)].login_count for i in self.scope.office_ids)
        office_qa = sum(self.buckets[str(i)].total_questions for i in self.scope.office_ids)
        company = self.buckets["company"]

        def make_row(key: str, label: str, number: Any, total: bool = False, extra: bool = False) -> dict:
            bucket = self.buckets[key]
            row = dict.fromkeys(HEADERS, "")
            row.update(
                {"序号": number, "科室": label, "贡献数": bucket.total_documents, "登录次数": bucket.login_count}
            )
            row.update({name: len(bucket.documents[level]) for level, name in LEVELS.items()})
            row.update({name: bucket.questions[typ] for typ, name in QA.items()})
            notes = ["存在来源/归属异常，见诊断；仅统计可归属记录"] if self.has_warnings else []
            if self.qa_history_note:
                notes.append(self.qa_history_note)
            if extra:
                notes.append("计入制造部合计，不进入主表十科室使用占比分母；本表不计算比例")
            else:
                formulas = [
                    (
                        "贡献比",
                        bucket.total_documents if total else len(bucket.department_documents),
                        company.total_documents if total else len(self.department_documents),
                        "公司五类库贡献并集" if total else "制造部部门库文档并集",
                    ),
                    (
                        "访问比",
                        bucket.login_count,
                        company.login_count if total else office_login,
                        "公司登录次数" if total else "主表十科室登录次数",
                    ),
                    (
                        "问答比",
                        bucket.total_questions,
                        company.total_questions if total else office_qa,
                        "公司三类问答数" if total else "主表十科室三类问答数",
                    ),
                ]
                for metric, numerator, denominator, scope in formulas:
                    value = f"{numerator / denominator:.2%}" if denominator else ""
                    row[metric] = value
                    ratios.append(
                        {
                            "科室": label,
                            "指标": metric,
                            "分子": numerator,
                            "分母": denominator,
                            "分母范围": scope,
                            "比例": value,
                            "状态": "正常" if denominator else "分母为 0",
                        }
                    )
                    if not denominator:
                        notes.append(f"{metric}分母为 0")
            row["备注"] = "；".join(notes)
            return row

        for index, org_id in enumerate(self.scope.office_ids, 1):
            summary.append(make_row(str(org_id), self.scope.names[org_id], index))
        summary.append(make_row("manufacturing", "制造部合计", "", total=True))
        for key in sorted(self.buckets):
            if key not in {"company", "manufacturing", *(str(i) for i in self.scope.office_ids)}:
                other.append(make_row(key, self.scope.names[int(key)], key, extra=True))
        return summary, other, ratios


CHINA = ZoneInfo("Asia/Shanghai")
RAW_INDEX = "base_telemetry_events"
LOGIN_INDEX = "mid_user_engagement_stat"
QA_INDEX = "mid_realtime_qa_question_fact"


class OfficeRepository:
    def __init__(self, session: Any) -> None:
        from bisheng.database.models.department import Department, UserDepartment
        from bisheng.database.models.qa_expert import Question
        from bisheng.database.models.tenant import UserTenant
        from bisheng.knowledge.domain.models.knowledge import Knowledge
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
        from bisheng.user.domain.models.user import User

        self.session = session
        self.Department, self.Membership, self.UserTenant, self.User = Department, UserDepartment, UserTenant, User
        self.Question = Question
        self.Space, self.Scope, self.File = Knowledge, KnowledgeSpaceScope, KnowledgeFile
        self.Version, self.FileDao = KnowledgeDocumentVersion, KnowledgeFileDao

    def rows(self, statement: Any) -> Iterator[dict]:
        result = self.session.execute(statement.execution_options(yield_per=400))
        try:
            for row in result.mappings():
                yield dict(row)
        finally:
            result.close()

    def departments(self) -> list[dict]:
        from sqlalchemy import select

        d = self.Department
        return list(self.rows(select(d.id, d.name, d.path, d.parent_id, d.org_level).order_by(d.id)))

    def memberships(self) -> list[dict]:
        from sqlalchemy import and_, case, select

        m, d, u, ut = self.Membership, self.Department, self.User, self.UserTenant
        # UserTenant 的 tenant_id 是关联字段，不受自动租户过滤；与已隔离的组织显式关联。
        # 不按用户在职或租户启用状态过滤历史贡献；EXISTS 只作校验，不抹去有主组织的旧用户。
        tenant_membership = select(ut.id).where(and_(ut.user_id == m.user_id, ut.tenant_id == d.tenant_id)).exists()
        # 组织列必须在投影中，现有租户钩子通过 column_descriptions 识别隔离表。
        statement = (
            select(
                m.user_id,
                d.id.label("department_id"),
                u.user_name,
                case((tenant_membership, 1), else_=0).label("tenant_member"),
            )
            .select_from(m)
            .join(d, d.id == m.department_id)
            .outerjoin(u, u.user_id == m.user_id)
            .where(m.is_primary == 1)
            .order_by(m.user_id, m.department_id)
        )
        # CASE 将谓词转为数值列，避免要求数据库支持直接 SELECT 布尔表达式。
        return [{**row, "tenant_member": bool(row["tenant_member"])} for row in self.rows(statement)]

    def inventory_statement(self) -> Any:
        from sqlalchemy import func, or_, select
        from sqlalchemy.orm import aliased

        f, s, scope, v = self.File, self.Space, self.Scope, aliased(self.Version)
        # 版本表无租户字段，必须经已隔离的文件 ID 关联，不通过任意 document_id 扫描版本。
        return (
            select(
                f.id.label("file_id"),
                f.user_id,
                f.file_name,
                s.id.label("space_id"),
                func.coalesce(f.reference_document_id, v.document_id).label("document_id"),
                scope.level,
                scope.owner_type,
                scope.owner_id,
            )
            .select_from(f)
            .join(s, s.id == f.knowledge_id)
            .join(scope, scope.space_id == s.id)
            .outerjoin(v, v.knowledge_file_id == f.id)
            .where(
                s.type == 3,
                scope.level.in_(list(LEVELS)),
                f.file_type == 1,
                f.status == 2,
                s.is_favorite.is_(False),
                or_(s.state.is_(None), s.state != 5),
                self.FileDao.active_inventory_predicate(),
            )
            .order_by(f.id)
        )

    def inventory(self) -> Iterator[dict]:
        return self.rows(self.inventory_statement())

    def expert_questions(self) -> Iterator[dict]:
        from sqlalchemy import select

        q = self.Question
        return self.rows(select(q.id.label("question_id"), q.user_id, q.created_at.label("timestamp")).order_by(q.id))


def epoch(value: Any) -> float:
    """兼容 ES 秒/毫秒及日期字符串；数据库专家时间使用北京时间。"""
    if isinstance(value, bool):
        raise ReportError("记录时间无效")
    if isinstance(value, datetime):
        result = (value if value.tzinfo else value.replace(tzinfo=CHINA)).timestamp()
    else:
        try:
            result = float(value)
            if result > 100_000_000_000:
                result /= 1000
        except (ValueError, TypeError):
            if not isinstance(value, str):
                raise ReportError("记录时间缺失或无效") from None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ReportError("记录时间格式无效") from None
            result = (parsed if parsed.tzinfo else parsed.replace(tzinfo=CHINA)).timestamp()
    if not math.isfinite(result) or result <= 0:
        raise ReportError("记录时间无效")
    return result


def local_time(value: Any) -> str:
    return datetime.fromtimestamp(epoch(value), CHINA).isoformat(sep=" ")


class EsReader:
    """完整 PIT 分页，不实例化有建索引副作用的业务统计类。"""

    def __init__(
        self, client: Any, tenant_id: int, diagnose: Callable, progress: Callable, page_size: int = 1000
    ) -> None:
        self.client, self.tenant_id = client, tenant_id
        self.diagnose, self.progress, self.page_size = diagnose, progress, page_size

    @staticmethod
    def validate(response: Any) -> None:
        shards = response.get("_shards") or {}
        if response.get("timed_out") or response.get("terminated_early") or shards.get("failed", 0):
            raise ReportError("ES 返回超时、提前终止或分片失败，不能生成完整报表")

    def scan(self, index: str, filters: list[dict], fields: list[str]) -> Iterator[dict]:
        self.progress(f"ES 开始查询：{index}")
        if not self.client.indices.exists(index=index):
            raise ReportError(f"必需 ES 索引不存在：{index}；不能按零处理")
        pit = None
        seen, pages, total = 0, 0, None
        cursor, cursors = None, set()
        minimum, maximum = None, None
        started = datetime.now(CHINA).isoformat()
        try:
            opened = self.client.open_point_in_time(index=index, keep_alive="5m")
            pit = opened.get("id")
            self.validate(opened)
            if not pit:
                raise ReportError("ES 未返回 PIT ID")
            while True:
                response = self.client.search(
                    pit={"id": pit, "keep_alive": "5m"},
                    size=self.page_size,
                    sort=["_shard_doc"],
                    search_after=cursor,
                    track_total_hits=True,
                    allow_partial_search_results=False,
                    source=fields,
                    query={"bool": {"filter": [{"term": {"tenant_id": str(self.tenant_id)}}, *filters]}},
                )
                pit = response.get("pit_id") or pit
                self.validate(response)
                hits = response.get("hits") or {}
                exact = hits.get("total") or {}
                if not isinstance(exact, dict) or exact.get("relation") != "eq" or "value" not in exact:
                    raise ReportError("ES 未返回精确命中总数")
                if total is None:
                    total = int(exact["value"])
                elif total != int(exact["value"]):
                    raise ReportError("ES PIT 内总数变化")
                page = hits.get("hits")
                if not isinstance(page, list):
                    raise ReportError("ES 缺少分页结果")
                if not page:
                    if seen != total:
                        raise ReportError("ES 分页不完整，读取数与总数不一致")
                    break
                pages += 1
                for hit in page:
                    source = hit.get("_source") or {}
                    if positive(source.get("tenant_id"), "事件租户ID") != self.tenant_id:
                        raise ReportError("ES 返回跨租户记录")
                    stamp = epoch(source.get("timestamp"))
                    minimum = stamp if minimum is None else min(minimum, stamp)
                    maximum = stamp if maximum is None else max(maximum, stamp)
                    seen += 1
                    if seen > total:
                        raise ReportError("ES 分页读取数超过命中总数")
                    yield source
                next_cursor = page[-1].get("sort")
                if not next_cursor or tuple(next_cursor) in cursors:
                    raise ReportError("ES 分页游标缺失或重复")
                cursors.add(tuple(next_cursor))
                cursor = next_cursor
                self.progress(f"ES {index} 第 {pages} 页，已读取 {seen}/{total}")
            coverage = f"{local_time(minimum)} 至 {local_time(maximum)}" if minimum is not None else "无匹配记录"
            self.diagnose(
                "INFO",
                index,
                "扫描完成",
                f"读取={seen};页数={pages};事件范围={coverage};开始={started};结束={datetime.now(CHINA).isoformat()}",
            )
        finally:
            if pit:
                try:
                    self.client.close_point_in_time(id=pit)
                except Exception as exc:
                    # 关闭游标不改变查询结果，但必须记录清理失败；不输出可能含凭据的异常文本。
                    self.diagnose("WARNING", index, "PIT清理失败", type(exc).__name__)


def create_clients(settings: Any) -> tuple[Any, Any]:
    from bisheng.core.search.elasticsearch.es_connection import ESConnection

    clients = []
    try:
        for config in (settings.get_telemetry_conf(), settings.get_search_conf()):
            if not config.elasticsearch_url:
                raise ReportError("原始埋点或看板 ES 未配置")
            clients.append(ESConnection(config.elasticsearch_url, **config.ssl_verify).sync_es_connection)
        return clients[0], clients[1]
    except Exception:
        for client in clients:
            client.close()
        raise


def es_nodes(client: Any) -> str:
    # 仅打印节点主机和端口，禁止输出含账号密码的 URL 或请求头。
    return ", ".join(f"{node.config.host}:{node.config.port}" for node in client.transport.node_pool.all())


LOCATION = {
    "user_id": "用户ID",
    "user_name": "用户姓名",
    "department_id": "当前主组织ID",
    "department_path": "组织路径",
    "group": "归属组ID",
    "company": "计入公司",
    "manufacturing": "计入制造部",
    "reason": "排除原因",
}
DETAILS = {
    "知识核对明细.csv": {
        "file_id": "文件ID",
        "identity": "文档去重键",
        "file_name": "文件名",
        "space_id": "空间ID",
        "level": "库类型",
        "owner_type": "库所有者类型",
        "owner_id": "库所有者ID",
        "department_library": "属于制造部部门库",
        **LOCATION,
    },
    "登录核对明细.csv": {
        "event_id": "事件ID",
        "timestamp": "登录时间",
        "counted": "去重后计入事件",
        "source": "来源",
        **LOCATION,
    },
    "问答核对明细.csv": {
        "qa_type": "问答类型",
        "question_id": "问题ID",
        "timestamp": "问题时间",
        "counted": "去重后计入问题",
        "source": "来源",
        **LOCATION,
    },
}
DIAGNOSTIC_HEADERS = ["级别", "来源", "记录", "说明"]


def safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if "\ufffd" in value:
        raise ReportError("输出文本含 U+FFFD 替换字符，不能冒充编码正常的结果")
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class CsvReport:
    """明细流式写出；仅在读取、计算和 CSV 读回成功后发布主表。"""

    def __init__(self, directory: Path, stack: ExitStack) -> None:
        directory.mkdir(parents=True, exist_ok=False)
        self.directory, self.stack = directory, stack
        self.writers: dict[str, Any] = {}
        self.handles: dict[str, Any] = {}
        self.counts = Counter()
        self.warnings = 0
        self._writer("来源诊断.csv", DIAGNOSTIC_HEADERS)

    def _writer(self, name: str, headers: list[str]) -> Any:
        if name not in self.writers:
            handle = self.stack.enter_context((self.directory / name).open("x", encoding="utf-8-sig", newline=""))
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            self.writers[name], self.handles[name] = writer, handle
        return self.writers[name]

    def row(self, name: str, headers: list[str], row: dict) -> None:
        self._writer(name, headers).writerow({key: safe_cell(row.get(key)) for key in headers})
        self.counts[name] += 1

    def diagnose(self, severity: str, source: str, key: str, message: str) -> None:
        self.row(
            "来源诊断.csv",
            DIAGNOSTIC_HEADERS,
            dict(zip(DIAGNOSTIC_HEADERS, (severity, source, key, message), strict=True)),
        )
        self.handles["来源诊断.csv"].flush()
        if severity in {"WARNING", "ERROR"}:
            self.warnings += 1

    def detail(self, name: str, row: dict) -> None:
        translated = {
            title: (local_time(row[key]) if key == "timestamp" else row.get(key, ""))
            for key, title in DETAILS[name].items()
        }
        self.row(name, list(DETAILS[name].values()), translated)

    def table(self, name: str, headers: list[str], rows: list[dict]) -> None:
        self._writer(name, headers)
        for row in rows:
            self.row(name, headers, row)

    def verify(self) -> None:
        for name, handle in self.handles.items():
            handle.flush()
            with (self.directory / name).open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                count = 0
                for row in reader:
                    if None in row or any(value is None or "\ufffd" in value for value in row.values()):
                        raise ReportError(f"CSV 列数或编码异常：{name}")
                    count += 1
                if count != self.counts[name]:
                    raise ReportError(f"CSV 读回行数不一致：{name}")

    def finish(self, metrics: Metrics) -> None:
        metrics.has_warnings |= bool(self.warnings)
        summary, other, ratios = metrics.reports()
        self.table("其他组织统计.csv", HEADERS, other)
        self.table("指标分子分母.csv", ["科室", "指标", "分子", "分母", "分母范围", "比例", "状态"], ratios)
        for name, fields in DETAILS.items():
            self._writer(name, list(fields.values()))
        pending = "科室指标汇总.csv.partial"
        self.table(pending, HEADERS, summary)
        self.verify()
        with (self.directory / pending).open(encoding="utf-8-sig", newline="") as file:
            actual = list(csv.DictReader(file))
        expected = [{key: str(safe_cell(row.get(key, ""))) for key in HEADERS} for row in summary]
        if actual != expected:
            raise ReportError("CSV 汇总数值读回不一致")
        self.handles[pending].close()
        (self.directory / pending).rename(self.directory / "科室指标汇总.csv")


def collect_database(repository: OfficeRepository, args: argparse.Namespace, report: CsvReport) -> Metrics:
    office_map = None
    if args.office_map:
        with args.office_map.open(encoding="utf-8-sig") as file:
            office_map = json.load(file)
        if not isinstance(office_map, dict):
            raise ReportError("科室映射必须是 JSON 对象：表格行名到组织 ID")
    scope = OrganizationScope(
        repository.departments(),
        repository.memberships(),
        args.company_department_id,
        args.manufacturing_department_id,
        office_map,
    )
    metrics = Metrics(scope, report.diagnose)
    for org_id, stored, derived in scope.path_differences:
        report.diagnose(
            "WARNING", "组织路径", str(org_id),
            f"按 parent_id 构建统计路径；数据库path={stored};统计路径={derived};未修改数据库",
        )
    for name, org_id in zip(OFFICES, scope.office_ids, strict=True):
        report.diagnose("INFO", "组织", name, f"匹配组织ID={org_id};路径={scope.departments[org_id]['path']}")
    seen_files = set()
    for row in repository.inventory():
        if row["file_id"] in seen_files:
            raise ReportError("同一文件关联多个版本或空间范围，库存查询无法唯一解释")
        seen_files.add(row["file_id"])
        detail = metrics.file(row)
        if detail["department_library"] or scope.relevant_user(detail["user_id"]):
            report.detail("知识核对明细.csv", detail)
    report.diagnose("INFO", "数据库库存", "读取完成", f"有效入口数={len(seen_files)}")
    for row in repository.expert_questions():
        if not scope.relevant_user(positive(row["user_id"], "提问人ID")):
            continue
        row = {**row, "qa_type": "expert", "source": "qa_question", "timestamp": epoch(row["timestamp"])}
        report.detail("问答核对明细.csv", metrics.question(row))
    report.diagnose("INFO", "qa_question", "读取完成", f"问题数={len(metrics.question_events)}")
    return metrics


def collect_events(
    metrics: Metrics, raw: EsReader, dashboard: EsReader, report: CsvReport, raw_index: str = RAW_INDEX,
    qa_history_policy: str = "strict",
) -> None:
    if qa_history_policy not in {"strict", "raw"}:
        raise ReportError("未知问答历史策略")
    if qa_history_policy == "raw":
        metrics.qa_history_note = "问答以原始来源为准；旧记录按event_id去重，不能保证真实问题去重；看板独有记录不叠加"
    daily = Counter()
    fields = [
        "tenant_id",
        "timestamp",
        "event_id",
        "event_type",
        "user_context.user_id",
        "event_data.portal_qa_scene",
        "event_data.portal_qa_status",
        "event_data.portal_qa_question_id",
    ]
    for record in raw.scan(raw_index, [{"terms": {"event_type": ["user_login", "portal_qa"]}}], fields):
        uid = positive((record.get("user_context") or {}).get("user_id"), "事件用户ID")
        if not metrics.scope.relevant_user(uid):
            continue
        stamp = epoch(record.get("timestamp"))
        if record.get("event_type") == "user_login":
            detail = metrics.login(
                {"event_id": record.get("event_id"), "user_id": uid, "timestamp": stamp, "source": raw_index}
            )
            if detail["counted"]:
                daily[(uid, datetime.fromtimestamp(stamp, CHINA).date().isoformat())] += 1
            report.detail("登录核对明细.csv", detail)
        elif record.get("event_type") == "portal_qa":
            data = record.get("event_data") or {}
            status = data.get("portal_qa_status")
            if status not in (None, "success"):
                report.diagnose("WARNING", raw_index, str(record.get("event_id")), "非成功问答事件已排除")
                continue
            scene = data.get("portal_qa_scene")
            if scene not in {"smart_qa", "document_qa", "my_knowledge_document_qa"}:
                raise ReportError("存在未知问答场景，不能猜测归入智能或文档问答")
            # 仅显式选择 raw 时兼容历史事件标识；不按用户、时间或会话猜测问题身份。
            question_id = data.get("portal_qa_question_id")
            if not question_id and qa_history_policy == "raw":
                question_id = record.get("event_id")
                if question_id:
                    report.diagnose(
                        "WARNING", raw_index, str(question_id),
                        "旧成功问答缺少 question_id，按 event_id 去重；不能保证按真实问题 ID 完全去重",
                    )
            row = {
                "qa_type": "smart" if scene == "smart_qa" else "document",
                "question_id": question_id,
                "user_id": uid,
                "timestamp": stamp,
                "source": raw_index,
            }
            report.detail("问答核对明细.csv", metrics.question(row))
        else:
            raise ReportError("ES 返回不符合筛选条件的事件")

    compare_login(metrics, daily, dashboard, report)
    compare_questions(metrics, dashboard, report, qa_history_policy)


def compare_login(metrics: Metrics, daily: Counter, dashboard: EsReader, report: CsvReport) -> None:
    seen = set()
    gaps = 0
    fields = ["tenant_id", "timestamp", "metric_source", "user_id", "local_date", "login_count", "logged_in"]
    for record in dashboard.scan(LOGIN_INDEX, [{"term": {"metric_source": "participation"}}], fields):
        if record.get("metric_source") != "participation":
            raise ReportError("用户统计包含非登录来源")
        uid = positive(record.get("user_id"), "登录日统计用户ID")
        if not metrics.scope.relevant_user(uid):
            continue
        day = str(record.get("local_date") or "")
        try:
            if datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
                raise ValueError
        except ValueError:
            raise ReportError("登录日统计缺少有效日期") from None
        key = (uid, day)
        if key in seen:
            raise ReportError("同一用户同一天存在重复登录投影")
        seen.add(key)
        count = record.get("login_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ReportError("登录日统计次数无效")
        if record.get("logged_in") is not (count > 0):
            raise ReportError("登录日统计标志与次数冲突")
        raw_count = daily.get(key, 0)
        if raw_count != count:
            report.diagnose(
                "WARNING", LOGIN_INDEX, f"{uid}/{day}", f"原始登录次数={raw_count};日投影次数={count};不相加、不取最大"
            )
            metrics.has_warnings = True
            if count > raw_count:
                gaps += 1
    for key in daily.keys() - seen:
        report.diagnose(
            "WARNING", LOGIN_INDEX, f"{key[0]}/{key[1]}", f"原始登录次数={daily[key]};缺少日投影，使用原始成功登录记录"
        )
        metrics.has_warnings = True
    if gaps:
        raise ReportError(f"{gaps} 组登录日统计多于原始事件，历史覆盖不一致；已保留诊断，不能交付完整登录统计")


def compare_questions(
    metrics: Metrics, dashboard: EsReader, report: CsvReport, qa_history_policy: str = "strict"
) -> None:
    seen = set()
    gaps = 0
    fields = ["tenant_id", "timestamp", "user_id", "qa_type", "question_id"]
    for record in dashboard.scan(QA_INDEX, [], fields):
        key = (str(record.get("qa_type") or ""), str(record.get("question_id") or ""))
        uid = positive(record.get("user_id"), "问答投影用户ID")
        if not metrics.scope.relevant_user(uid):
            continue
        if not key[1] or key[0] not in {"smart", "document", "expert"}:
            raise ReportError("问答投影类型或问题 ID 无效")
        if key in seen:
            raise ReportError("问答投影存在重复问题")
        seen.add(key)
        if key not in metrics.question_events:
            gaps += 1
            report.diagnose(
                "WARNING", QA_INDEX, "/".join(key), "原始来源未覆盖投影中的问题，可能有历史缺失或删除/投影延迟"
            )
        elif metrics.question_events[key] != uid:
            raise ReportError("问答原始记录与投影提问人冲突")
    for key in metrics.question_events.keys() - seen:
        report.diagnose("WARNING", QA_INDEX, "/".join(key), "缺少看板投影，使用原始问题记录")
        metrics.has_warnings = True
    if gaps and qa_history_policy == "raw":
        metrics.has_warnings = True
        report.diagnose(
            "WARNING", QA_INDEX, "原始来源优先",
            f"{gaps} 个看板独有问题不叠加；智能/文档按原始成功事件，专家按当前数据库问题；差异已逐条保留",
        )
    elif gaps:
        raise ReportError(f"{gaps} 个投影问题在原始来源中不存在；已保留诊断，不能冒充完整问答统计")


def write_rules(report: CsvReport, args: argparse.Namespace) -> None:
    rules = {
        "租户ID": args.tenant_id,
        "公司组织ID": args.company_department_id,
        "制造部组织ID": args.manufacturing_department_id,
        "导出开始时间": datetime.now(CHINA).isoformat(),
        "时间范围": "不设日期筛选；知识为当前有效库存，行为为现存历史。来源读取窗口不同，不承诺跨系统同一快照。",
        "归属": "按文件 user_id、登录人、提问人的当前主组织，含子组织；不按在职状态排除。无当前主组织单列诊断。",
        "组织树": "按指定租户当前 parent_id 关系在内存构建；原 path 差异写入诊断，不回写数据库。父节点缺失或环路拒绝统计。",
        "库存": "普通个人库及公共/部门/科室/团队库；当前成功、有效入口；排除软删除、历史版本、收藏夹和退役空间。",
        "去重": "按 document:<id>，无文档关联时 file:<id>；五列分别去重，贡献数为并集；入口上传人冲突保留诊断。",
        "科室贡献比": "本科室人员向制造部部门库贡献的去重文档数 / 制造部部门库文档并集（含外部人员贡献）",
        "部门贡献比": "制造部人员五类库贡献并集 / 公司人员五类库贡献并集",
        "登录次数": "原始 user_login 成功事件按事件 ID 去重，非登录人数或登录人天数；与日投影核对但不叠加。",
        "问答次数": "智能/文档统计成功问题，专家统计提交问题；按类型和问题 ID 去重，不按会话或回答数。",
        "问答历史策略": (
            "raw：原始来源优先，旧成功问答缺 question_id 时按 event_id 去重；不能保证真实问题去重；看板独有记录仅诊断、不叠加。"
            if getattr(args, "qa_history_policy", "strict") == "raw"
            else "strict：缺少问题 ID 或看板存在原始来源未覆盖的问题时停止导出。"
        ),
        "科室使用比例": "本科室登录/三类问答次数 / 主表十科室对应总次数",
        "部门使用比例": "制造部（含其他科室和直属人员）登录/三类问答次数 / 公司对应总次数",
        "零分母": "比例留空并备注分母为 0；缺来源/分页失败为错误，不按零处理。比例保留两位小数。",
        "来源": f"原始埋点配置 get_telemetry_conf():{args.raw_index}；看板配置 get_search_conf():{LOGIN_INDEX},{QA_INDEX}；专家 qa_question。",
        "完整性边界": "未采集、已清理、未标租户历史不可恢复；跨来源差异可发现部分缺口，不能证明平台上线以来无遗漏。",
        "文本安全": "CSV 使用 UTF-8 BOM；可能被表格软件执行的文本加单引号；不导出知识正文、问题正文或连接凭据。",
    }
    report.table("统计口径.csv", ["项目", "说明"], [{"项目": key, "说明": value} for key, value in rules.items()])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("tenant-id", "company-department-id", "manufacturing-department-id"):
        parser.add_argument(f"--{name}", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="必须是不存在的新目录")
    parser.add_argument("--office-map", type=Path, help="可选 JSON：固定科室行名到组织 ID 的映射")
    parser.add_argument("--raw-index", default=RAW_INDEX, help="原始埋点 ES 索引或别名")
    parser.add_argument(
        "--qa-history-policy", choices=("strict", "raw"), default="strict",
        help="strict 严格校验；raw 兼容旧问答 event_id，以原始来源为准并保留看板差异诊断",
    )
    parser.add_argument("--config", help="使用项目已有配置文件")
    parser.add_argument("--verbose", action="store_true", help="显示每页 ES 查询进度")
    return parser


def close_client(client: Any, report: CsvReport) -> None:
    try:
        client.close()
    except Exception as exc:
        # 连接释放失败不推翻已经校验的报表，也不能将外部异常中的凭据写到终端。
        report.diagnose("WARNING", "ES", "连接清理失败", type(exc).__name__)
        print(f"ES 连接清理失败：{type(exc).__name__}；已记录诊断。", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("tenant_id", "company_department_id", "manufacturing_department_id"):
        if getattr(args, name) <= 0:
            print(f"参数 {name} 必须大于 0", file=sys.stderr)
            return 2
    if args.config:
        os.environ["config"] = args.config
    try:
        with ExitStack() as stack:
            report = CsvReport(args.output_dir, stack)
            try:
                write_rules(report, args)
                from bisheng.common.services.config_service import settings
                from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
                from bisheng.core.database import get_sync_db_session
                from bisheng.core.database.tenant_filter import register_tenant_filter_events

                repository = OfficeRepository(None)
                register_tenant_filter_events()
                token = set_current_tenant_id(args.tenant_id)
                stack.callback(current_tenant_id.reset, token)
                stack.enter_context(strict_tenant_filter())
                print("[科室统计] 开始读取组织、知识和专家问题", file=sys.stderr, flush=True)
                with get_sync_db_session() as session:
                    repository.session = session
                    try:
                        metrics = collect_database(repository, args, report)
                    finally:
                        session.rollback()
                raw_client, dashboard_client = create_clients(settings)
                stack.callback(close_client, raw_client, report)
                stack.callback(close_client, dashboard_client, report)

                def progress(message: str) -> None:
                    if args.verbose or "开始" in message:
                        print(f"[科室统计] {message}", file=sys.stderr, flush=True)

                for name, client in (("原始埋点ES", raw_client), ("看板ES", dashboard_client)):
                    report.diagnose("INFO", name, "连接", es_nodes(client))
                raw = EsReader(raw_client, args.tenant_id, report.diagnose, progress)
                dashboard = EsReader(dashboard_client, args.tenant_id, report.diagnose, progress)
                collect_events(metrics, raw, dashboard, report, args.raw_index, args.qa_history_policy)
                report.diagnose("INFO", "报表", "计算完成", f"来源/归属提示数={report.warnings}")
                report.finish(metrics)
                print(f"输出目录：{args.output_dir.resolve()}；提示数：{report.warnings}")
                return 0
            except Exception as exc:
                # 仅自己的校验错误展示详情，连接异常可能携带凭据，只输出类型。
                message = str(exc) if isinstance(exc, ReportError) else type(exc).__name__
                report.diagnose("ERROR", "导出", type(exc).__name__, message)
                print(f"统计失败：{message}；请查看来源诊断.csv，未发布完整汇总。", file=sys.stderr)
                return 1
    except (FileExistsError, OSError) as exc:
        print(f"输出目录无法创建或写入：{type(exc).__name__}；不会覆盖已有目录。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
