#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""只读合并审计、ES 操作和业务记录，按有效操作导出每日用户活跃统计。

在 src/backend 执行：
    .venv/bin/python scripts/export_user_daily_activity.py --all-tenants \
        --start-date 2026-08-01 --end-date 2026-09-21 --verbose
不写数据库、不创建 ES 索引；输出目录必须不存在。详见 scripts/README.md。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

CHINA = ZoneInfo("Asia/Shanghai")
LOGIN = "user_login"
ES_INDEX = "base_telemetry_events"
# 仅采用用户动作；模型、工具、解析完成及连接心跳可能在用户离开后继续产生。
OPERATION_EVENTS = (
    "new_message_session",
    "delete_message_session",
    "new_application",
    "edit_application",
    "delete_application",
    "new_knowledge_base",
    "delete_knowledge_base",
    "new_knowledge_file",
    "delete_knowledge_file",
    "message_feedback",
    "portal_favorite",
    "portal_qa",
    "portal_document_read",
    "portal_document_download",
    "portal_search",
)
AUDIT_ACTIONS = (
    "approval.request.submit",
    "approval.request.withdraw",
    "approval.task.approve",
    "approval.task.reject",
    "approval.exception.retry",
    "approval.exception.assign_approver",
    "approval.exception.cancel",
    "approval.exception.skip_node",
    "approval.flow.update",
    "approval.scenario.create",
    "approval.scenario.toggle",
    "approval.menu_access.revoke_grant",
    "approval.department_file_view.grant.revoke",
)
SUMMARY_HEADERS = [
    "日期",
    "日活数量",
    "截至当日累计有效操作人数",
    "日活比例",
    "每日用户平均使用时间(分钟)",
]
PLATFORM_HEADERS = ["统计截止时间", "统计范围", "平台总用户数（看板口径）", "截至当前累计有效操作人数"]
MONTHLY_HEADERS = ["月份", "统计开始时间", "统计截止时间（不含）", "月活人数"]


def trace(message: str, verbose: bool) -> None:
    if verbose:
        print(f"[活跃统计] {message}", file=sys.stderr, flush=True)


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, CHINA)


def local_text(timestamp: float | None) -> str:
    return datetime.fromtimestamp(timestamp, CHINA).isoformat(sep=" ") if timestamp is not None else ""


@dataclass
class UserDay:
    first_operation: float | None = None
    last_operation: float | None = None
    last_sources: set[str] = field(default_factory=set)

    @property
    def operation_seconds(self) -> float:
        if self.first_operation is None or self.last_operation is None:
            return 0.0
        return self.last_operation - self.first_operation


class Activity:
    def __init__(self, start: date, end: date, cutoff: float, *, snapshot_cutoff: float | None = None) -> None:
        self.start, self.end, self.cutoff = start, end, cutoff
        self.snapshot_cutoff = cutoff if snapshot_cutoff is None else snapshot_cutoff
        if self.snapshot_cutoff < cutoff:
            raise ValueError("平台汇总截止时间不能早于每日统计截止时间")
        self.history: dict[int, float] = {}
        self.days: dict[tuple[date, int], UserDay] = defaultdict(UserDay)
        self.sources: dict[tuple[date, str], dict] = {}

    def historical_operation(self, user: int, timestamp: float) -> None:
        if user > 0 and timestamp < self.snapshot_cutoff:
            self.history[user] = min(self.history.get(user, timestamp), timestamp)

    def record(self, user: int, first: float, last: float, source: str, *, login: bool = False, count: int = 1) -> None:
        if user <= 0 or login:
            return
        day = datetime.fromtimestamp(first, CHINA).date()
        if not (self.start <= day <= self.end and first <= last < self.cutoff):
            raise ValueError("数据源返回了统计时间范围之外的记录")
        if datetime.fromtimestamp(last, CHINA).date() != day:
            raise ValueError("数据源将跨自然日记录合并，不能计算每日时长")
        item = self.days[day, user]
        self.historical_operation(user, first)
        item.first_operation = min(item.first_operation if item.first_operation is not None else first, first)
        if item.last_operation is None or last >= item.last_operation:
            if item.last_operation != last:
                item.last_sources.clear()
            item.last_operation = last
            item.last_sources.add(source)
        stat = self.sources.setdefault((day, source), {"count": 0, "users": set(), "first": first, "last": last})
        stat["count"] += count
        stat["users"].add(user)
        stat["first"], stat["last"] = min(stat["first"], first), max(stat["last"], last)

    def daily_totals(self) -> dict[date, dict]:
        totals: dict[date, dict] = defaultdict(lambda: {"operation_users": 0, "seconds": 0.0})
        for (day, _), item in self.days.items():
            stat = totals[day]
            if item.first_operation is not None:
                stat["operation_users"] += 1
                stat["seconds"] += item.operation_seconds
        return totals

    def reports(self) -> list[list]:
        summaries = []
        totals = self.daily_totals()
        first_days = sorted(datetime.fromtimestamp(ts, CHINA).date() for ts in self.history.values())
        cumulative, day = 0, self.start
        while day <= self.end:
            while cumulative < len(first_days) and first_days[cumulative] <= day:
                cumulative += 1
            stat = totals[day]
            active = stat["operation_users"]
            if active > cumulative:
                raise ValueError("当日活跃人数大于历史累计操作人数，请核对操作来源")
            summaries.append(
                [
                    day.isoformat(),
                    active,
                    cumulative,
                    f"{active / cumulative:.2%}" if cumulative else "0.00%",
                    round(stat["seconds"] / active / 60, 2) if active else 0.0,
                ]
            )
            day += timedelta(days=1)
        return summaries

    def monthly_reports(self) -> list[list]:
        users: dict[date, set[int]] = defaultdict(set)
        for (day, user), item in self.days.items():
            if item.first_operation is not None:
                users[day.replace(day=1)].add(user)
        summaries = []
        month = self.start.replace(day=1)
        while month <= self.end:
            next_month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
            first = midnight(max(month, self.start)).timestamp()
            cutoff = min(
                midnight(next_month).timestamp(), midnight(self.end + timedelta(days=1)).timestamp(), self.cutoff
            )
            summaries.append([month.strftime("%Y-%m"), local_text(first), local_text(cutoff), len(users[month])])
            month = next_month
        return summaries


class ActivityRepository:
    """使用真实 ORM 和项目租户上下文，只读取标识和发生时间。"""

    def __init__(self, session: Any, db_zone: ZoneInfo) -> None:
        from bisheng.channel.domain.models.article_read_record import ArticleReadRecord
        from bisheng.database.models.audit_log import AuditLog, EventType
        from bisheng.database.models.message import ChatMessage
        from bisheng.database.models.qa_expert import Answer, Comment, Question

        self.session, self.db_zone = session, db_zone
        self.Audit = AuditLog
        self.legacy_events = [event.value for event in EventType if event.value != LOGIN]
        self.sources = [
            (ChatMessage, ChatMessage.create_time, "chat_message", db_zone, [ChatMessage.is_bot.is_(False)]),
            (Question, Question.created_at, "qa_question", CHINA, []),
            (Answer, Answer.created_at, "qa_answer", CHINA, []),
            (Comment, Comment.created_at, "qa_comment", CHINA, []),
            (ArticleReadRecord, ArticleReadRecord.create_time, "article_read", db_zone, []),
        ]

    @staticmethod
    def timestamp(value: datetime, zone: ZoneInfo) -> float:
        return (value.replace(tzinfo=zone) if value.tzinfo is None else value).timestamp()

    def dashboard_user_metric(self) -> tuple[str, dict]:
        from sqlalchemy import select

        from bisheng.telemetry_search.domain.models.dashboard_dataset import DashboardDataset, SchemaConfig

        row = self.session.execute(
            select(DashboardDataset.es_index_name, DashboardDataset.schema_config).where(
                DashboardDataset.dataset_code == "mid_user_increment"
            )
        ).one_or_none()
        if row is None:
            raise ValueError("未找到看板用户数据统计数据集 mid_user_increment，无法对齐平台总用户数")
        schema = SchemaConfig(**row[1])
        metrics = [metric for metric in schema.metrics if metric.field == "total_user_count"]
        if len(metrics) != 1 or not row[0]:
            raise ValueError("看板总用户数指标配置缺失或不唯一")
        return row[0], metrics[0].model_dump()

    def collect_history(
        self,
        activity: Activity,
        user_column: Any,
        time_column: Any,
        zone: ZoneInfo,
        filters: list,
        name: str,
        *,
        verbose: bool,
    ) -> None:
        from sqlalchemy import func, select

        # 全历史首次操作同时支撑每日累计分母和截至运行时的累计人数，不受报表结束日期限制。
        trace(f"数据库：查询 {name} 截至运行时的历史操作（无历史下界）", verbose)
        statement = (
            select(user_column, func.min(time_column))
            .where(
                user_column > 0,
                time_column < datetime.fromtimestamp(activity.snapshot_cutoff, zone).replace(tzinfo=None),
                *filters,
            )
            .group_by(user_column)
            .execution_options(yield_per=1000)
        )
        count = 0
        for user, first in self.session.execute(statement):
            activity.historical_operation(user, self.timestamp(first, zone))
            count += 1
        trace(f"数据库：{name} 历史操作查询完成，用户数={count}", verbose)

    def collect(self, activity: Activity, *, verbose: bool) -> None:
        from sqlalchemy import or_, select

        audit = self.Audit
        start = midnight(activity.start)
        end = datetime.fromtimestamp(activity.cutoff, CHINA)
        low = start.astimezone(self.db_zone).replace(tzinfo=None)
        high = end.astimezone(self.db_zone).replace(tzinfo=None)
        audit_filters = [
            or_(audit.event_type.is_(None), audit.event_type != LOGIN),
            or_(audit.event_type.in_(self.legacy_events), audit.action.in_(AUDIT_ACTIONS)),
        ]
        self.collect_history(
            activity, audit.operator_id, audit.create_time, self.db_zone, audit_filters, "audit", verbose=verbose
        )
        trace("数据库：查询审计中的用户操作记录（不含登录）", verbose)
        statement = (
            select(audit.operator_id, audit.create_time, audit.event_type, audit.action)
            .where(
                audit.operator_id > 0,
                audit.create_time >= low,
                audit.create_time < high,
                *audit_filters,
            )
            .execution_options(yield_per=1000)
        )
        count = 0
        for user, occurred, event, action in self.session.execute(statement):
            timestamp = self.timestamp(occurred, self.db_zone)
            activity.record(user, timestamp, timestamp, f"audit:{action or event}", login=event == LOGIN)
            count += 1
        trace(f"数据库：审计查询完成，记录数={count}", verbose)
        for model, time_column, name, zone, extra in self.sources:
            self.collect_history(activity, model.user_id, time_column, zone, extra, name, verbose=verbose)
            trace(f"数据库：开始查询 {name}", verbose)
            statement = (
                select(model.user_id, time_column)
                .where(
                    model.user_id > 0,
                    time_column >= start.astimezone(zone).replace(tzinfo=None),
                    time_column < end.astimezone(zone).replace(tzinfo=None),
                    *extra,
                )
                .execution_options(yield_per=1000)
            )
            count = 0
            for user, occurred in self.session.execute(statement):
                timestamp = self.timestamp(occurred, zone)
                activity.record(user, timestamp, timestamp, name, login=False)
                count += 1
            trace(f"数据库：{name} 查询完成，记录数={count}", verbose)


def create_telemetry_client(settings: Any) -> Any:
    from bisheng.core.search.elasticsearch.es_connection import ESConnection

    config = settings.get_telemetry_conf()
    if not config.elasticsearch_url:
        raise ValueError("未配置原始埋点 ES 连接")
    return ESConnection(config.elasticsearch_url, **config.ssl_verify).sync_es_connection


def create_dashboard_client(settings: Any) -> Any:
    from bisheng.core.search.elasticsearch.es_connection import ESConnection

    config = settings.get_search_conf()
    if not config.elasticsearch_url:
        raise ValueError("未配置看板 ES，无法统计与看板同口径的平台总用户数")
    return ESConnection(config.elasticsearch_url, **config.ssl_verify).sync_es_connection


def dashboard_total_users(
    client: Any,
    index: str,
    metric_config: dict,
    cutoff: float,
    tenant_id: int | None,
    *,
    verbose: bool,
) -> int:
    from bisheng.telemetry_search.domain.models.dashboard_dataset import MetricConfig
    from bisheng.telemetry_search.domain.schemas.query_builder import AggregationExpression, AggsTypeEnum
    from bisheng.telemetry_search.domain.services.search_engine_service import QueryBuilder, SearchParameters

    metric = MetricConfig(**metric_config)
    # 对齐看板无时间分组的 query_sum_metric，保留 cardinality 的默认精度及指标过滤条件。
    if (
        not metric.is_virtual
        or metric.sum_field != "user_id"
        or metric.sum_type != AggsTypeEnum.CARDINALITY
        or metric.formula is not None
        or metric.calculation is not None
    ):
        raise ValueError("看板总用户数口径已改变，不能按用户去重方式读取，请核对数据集配置")
    if metric.filter:
        metric.filter.to_dsl()  # 构造器会忽略过滤器转换异常，此处先校验以免静默扩大范围。
    body = QueryBuilder(
        SearchParameters(
            index_name=index,
            metrics=[AggregationExpression(field=metric.sum_field, type=metric.sum_type)],
            dimensions=[],
            filters=[metric.filter] if metric.filter else None,
        )
    ).build_query_dsl()
    filters: list[dict] = [
        body["query"],
        {"range": {"timestamp": {"lt": str(cutoff), "format": "epoch_second"}}},
    ]
    if tenant_id is not None:
        filters.append({"term": {"tenant_id": tenant_id}})
    body["query"] = {"bool": {"filter": filters}}
    trace(f"看板 ES 请求：总用户数 index={index} metric=total_user_count", verbose)
    if not client.indices.exists(index=index):
        raise ValueError("看板用户数据集索引不存在，不能把缺失数据当作零用户")
    response = client.search(index=index, body=body, allow_partial_search_results=False)
    if response.get("timed_out") or response.get("terminated_early") or response.get("_shards", {}).get("failed", 0):
        raise ValueError("看板用户总数查询未完整返回，拒绝生成统计结果")
    value = response["aggregations"]["metric_0"]["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
        raise ValueError("看板用户总数返回值无效")
    trace(f"看板 ES 响应：总用户数={int(value)}", verbose)
    return int(value)


def composite_pages(
    client: Any,
    index: str,
    filters: list[dict],
    sources: list[dict],
    *,
    verbose: bool,
    label: str,
    page_size: int = 1000,
) -> Iterator[dict]:
    after = None
    page = 0
    while True:
        composite: dict = {"size": page_size, "sources": sources}
        if after is not None:
            composite["after"] = after
        body = {
            "size": 0,
            "query": {"bool": {"filter": filters}},
            "aggs": {
                "records": {
                    "composite": composite,
                    "aggs": {
                        "first": {"min": {"field": "timestamp"}},
                        "last": {"max": {"field": "timestamp"}},
                    },
                }
            },
        }
        page += 1
        trace(f"ES 请求：{label} index={index} 第{page}页", verbose)
        response = client.search(index=index, body=body, allow_partial_search_results=False)
        if (
            response.get("timed_out")
            or response.get("terminated_early")
            or response.get("_shards", {}).get("failed", 0)
        ):
            raise ValueError("ES 查询未完整返回，拒绝生成统计结果")
        records = response["aggregations"]["records"]
        buckets = records["buckets"]
        trace(f"ES 响应：{label} 第{page}页 返回分组={len(buckets)}", verbose)
        yield from buckets
        if not buckets or "after_key" not in records:
            break
        next_after = records["after_key"]
        if next_after == after:
            raise ValueError("ES 分页游标未推进，拒绝返回不完整结果")
        after = next_after


def collect_es(client: Any, index: str, activity: Activity, tenant_id: int | None, *, verbose: bool) -> None:
    trace(f"ES 检查索引：{index}", verbose)
    if not client.indices.exists(index=index):
        raise ValueError("原始埋点 ES 索引不存在，不能把缺失数据当作零活跃")
    filters: list[dict] = [{"range": {"user_context.user_id": {"gt": 0}}}]
    if tenant_id is not None:
        filters.append({"term": {"tenant_id": tenant_id}})
    user_source = {"user": {"terms": {"field": "user_context.user_id"}}}
    historical_filters = [
        *filters,
        {"terms": {"event_type": list(OPERATION_EVENTS)}},
        {
            "range": {"timestamp": {"lt": str(activity.snapshot_cutoff), "format": "epoch_second"}},
        },
    ]
    for bucket in composite_pages(
        client, index, historical_filters, [user_source], verbose=verbose, label="截至运行时历史操作"
    ):
        # ES date 字段的 min/max 数值始终为毫秒，即使写入格式是 epoch_second。
        activity.historical_operation(int(bucket["key"]["user"]), bucket["first"]["value"] / 1000)
    period_filters = [
        *filters,
        {"terms": {"event_type": list(OPERATION_EVENTS)}},
        {
            "range": {
                "timestamp": {
                    "gte": str(midnight(activity.start).timestamp()),
                    "lt": str(activity.cutoff),
                    "format": "epoch_second",
                }
            },
        },
    ]
    sources = [
        {"day": {"date_histogram": {"field": "timestamp", "calendar_interval": "1d", "time_zone": "+08:00"}}},
        user_source,
        {"event": {"terms": {"field": "event_type"}}},
    ]
    for bucket in composite_pages(client, index, period_filters, sources, verbose=verbose, label="每日用户操作"):
        event = bucket["key"]["event"]
        activity.record(
            int(bucket["key"]["user"]),
            bucket["first"]["value"] / 1000,
            bucket["last"]["value"] / 1000,
            f"es:{event}",
            login=event == LOGIN,
            count=bucket["doc_count"],
        )


def write_report(directory: Path, activity: Activity, platform_users: int, tenant_id: int | None = None) -> Path:
    summaries = activity.reports()
    monthly = activity.monthly_reports()
    directory.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(directory):
        raise FileExistsError("输出目录已存在，请指定新目录")
    target = directory / "每日用户活跃统计.csv"
    platform_rows = [
        [
            local_text(activity.snapshot_cutoff),
            "全平台" if tenant_id is None else f"租户 {tenant_id}",
            platform_users,
            len(activity.history),
        ]
    ]
    # 所有表都写完后一次性发布目录，避免只留下其中一张或半份报表。
    with tempfile.TemporaryDirectory(dir=directory.parent, prefix=".user-activity-") as staging:
        for name, headers, rows in [
            (target.name, SUMMARY_HEADERS, summaries),
            ("平台用户汇总.csv", PLATFORM_HEADERS, platform_rows),
            ("每月用户活跃统计.csv", MONTHLY_HEADERS, monthly),
        ]:
            with (Path(staging) / name).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(headers)
                writer.writerows(rows)
                stream.flush()
                os.fsync(stream.fileno())
        if os.path.lexists(directory):
            raise FileExistsError("输出目录已存在，请指定新目录")
        Path(staging).rename(directory)
    return target


def print_summary(activity: Activity, target: Path, *, verbose: bool) -> None:
    print("日活口径：当日有有效操作的去重人数；比例为日活 / 截至当天的历史累计操作人数。登录事件不计入。")
    print("月活口径：所选日期范围内，每月有效操作用户去重；非整月按实际起止时间统计，不外推整月人数。")
    print("平均时长：每位有操作用户的当日最后操作减首次操作，再按有操作人数平均；单位分钟，包含中途闲置。")
    print(f"时间范围：{activity.start} 至 {activity.end}，北京时间；查询截止（不含）：{local_text(activity.cutoff)}")
    totals = activity.daily_totals()
    if not activity.history:
        print("提示：未找到任何有效操作记录，请核对配置、统计范围及历史日志留存。")
    print("分母为可追溯历史累计操作用户；未采集、已清理或缺失用户ID的操作无法还原，人数和比例受留存范围影响。")
    if activity.cutoff < midnight(activity.end + timedelta(days=1)).timestamp():
        print(f"注意：{activity.end} 尚未结束，最后一天为截至运行时的部分数据，完整结果请次日重跑。")
    for day, stat in sorted(totals.items()):
        trace(
            f"{day} 活跃人数={stat['operation_users']} 首末操作总秒数={stat['seconds']}",
            verbose,
        )
    print(f"平台汇总截止（不含）：{local_text(activity.snapshot_cutoff)}；累计有效操作人数={len(activity.history)}")
    print("平台总用户数沿用看板数据集的去重聚合；看板同步延迟、页面额外筛选和聚合估算可能影响比对。")
    print(f"已导出 {(activity.end - activity.start).days + 1} 天、5 列结果：{target.resolve()}")
    print(f"平台用户汇总：{(target.parent / '平台用户汇总.csv').resolve()}")
    print(f"每月用户活跃统计：{(target.parent / '每月用户活跃统计.csv').resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-tenants", action="store_true", help="全平台，合并所有租户及历史无租户记录，按用户ID去重")
    scope.add_argument("--tenant-id", type=int, help="只统计指定租户；无法归属租户的历史记录不计入")
    parser.add_argument("--start-date", type=date.fromisoformat, required=True, help="起始日期，包含当天")
    parser.add_argument("--end-date", type=date.fromisoformat, required=True, help="结束日期，包含当天")
    parser.add_argument("--db-timezone", default="Asia/Shanghai", help="数据库无时区审计/聊天/资讯时间的时区")
    parser.add_argument("--config", help="项目配置文件名，与后端 config 环境变量一致")
    parser.add_argument("--es-index", default=ES_INDEX, help="原始操作埋点索引或别名，不是看板日汇总索引")
    parser.add_argument("--verbose", action="store_true", help="打印数据库进度、ES 节点和每页请求/响应")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs") / f"user-daily-activity-{datetime.now():%Y%m%d-%H%M%S-%f}"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    now = datetime.now(CHINA)
    if args.start_date > args.end_date or args.end_date > now.date():
        parser.error("起始日期不能晚于结束日期，结束日期不能晚于北京时间今天")
    if args.tenant_id is not None and args.tenant_id <= 0:
        parser.error("租户ID必须为正整数")
    try:
        if args.output_dir.exists():
            raise ValueError("输出目录已存在，请指定新目录")
        zone = ZoneInfo(args.db_timezone)
        if args.config:
            os.environ["config"] = args.config
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.tenant import (
            bypass_tenant_filter,
            current_tenant_id,
            set_current_tenant_id,
            strict_tenant_filter,
        )
        from bisheng.core.database import get_sync_db_session
        from bisheng.core.database.tenant_filter import register_tenant_filter_events

        cutoff = min(now.timestamp(), midnight(args.end_date + timedelta(days=1)).timestamp())
        activity = Activity(args.start_date, args.end_date, cutoff, snapshot_cutoff=now.timestamp())
        repository = ActivityRepository(None, zone)
        register_tenant_filter_events()
        token = set_current_tenant_id(args.tenant_id)
        context: AbstractContextManager = bypass_tenant_filter() if args.all_tenants else strict_tenant_filter()
        try:
            trace(f"脚本={Path(__file__).resolve()} 截止={local_text(cutoff)}", args.verbose)
            with context, get_sync_db_session() as session:
                repository.session = session
                try:
                    dashboard_index, dashboard_metric = repository.dashboard_user_metric()
                    repository.collect(activity, verbose=args.verbose)
                finally:
                    session.rollback()
        finally:
            current_tenant_id.reset(token)
        client = create_telemetry_client(settings)
        try:
            if args.verbose:
                nodes = ", ".join(f"{node.config.host}:{node.config.port}" for node in client.transport.node_pool.all())
                trace(f"原始埋点 ES 节点={nodes}", True)
            collect_es(client, args.es_index, activity, args.tenant_id, verbose=args.verbose)
        finally:
            client.close()
        dashboard_client = create_dashboard_client(settings)
        try:
            platform_users = dashboard_total_users(
                dashboard_client,
                dashboard_index,
                dashboard_metric,
                activity.snapshot_cutoff,
                args.tenant_id,
                verbose=args.verbose,
            )
        finally:
            dashboard_client.close()
        target = write_report(args.output_dir, activity, platform_users, args.tenant_id)
        print_summary(activity, target, verbose=args.verbose)
        return 0
    except Exception as exc:
        # 连接异常可能含凭据，只输出异常类型；业务校验错误可安全展示。
        print(f"统计失败：{type(exc).__name__}；未生成可用的新报告。", file=sys.stderr)
        if isinstance(exc, (ValueError, FileExistsError)):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
