#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""只读统计已保存提问的 AI 回答覆盖率和回复当前点赞数。

从 src/backend 执行：
    python scripts/export_portal_qa_statistics.py --all-tenants \
        --start-date 2026-08-01 --end-date 2026-09-21 --verbose
不补写失败记录、不查询只包含成功事件的 ES。输出目录必须不存在。
单文档问答失败时可能连提问也未保存；统计仅代表现存记录，详见 scripts/README.md。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

CHINA = ZoneInfo("Asia/Shanghai")
HEADERS = ["问答类型", "提问总数（含失败）", "AI回复成功次数", "成功比例", "回复点赞数"]
LABELS = ("智能问答", "单文档问答")
ANSWER_TYPES = ("end", "over", "end_cover", "bot", "answer", "assistant")
ANSWER_CATEGORIES = ("answer", "agent_answer")


def trace(message: str, verbose: bool) -> None:
    if verbose:
        print(f"[问答统计] {message}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class Message:
    id: int
    chat_id: str
    user_id: int | None
    tenant_id: int | None
    flow_id: str | None
    is_bot: bool
    category: str
    type: str
    extra: str | None
    liked: int | None
    create_time: datetime

    @property
    def identity(self) -> tuple:
        return self.chat_id, self.user_id, self.tenant_id, self.flow_id


@dataclass
class Totals:
    questions: int = 0
    success: int = 0
    likes: int = 0

    @property
    def failed(self) -> int:
        return self.questions - self.success

    def row(self, label: str) -> list:
        ratio = f"{self.success / self.questions:.2%}" if self.questions else "0.00%"
        return [label, self.questions, self.success, ratio, self.likes]


def count_messages(messages: list[Message], start: datetime | None, end: datetime, diagnostics: Counter) -> Totals:
    """在同一会话内配对；日期筛选只作用于提问，回答可在区间结束后到达。"""
    questions = {item.id: item for item in messages if not item.is_bot and item.category == "question"}
    selected = {
        key
        for key, item in questions.items()
        if (start is None or item.create_time >= start) and item.create_time < end
    }
    answered: set[int] = set()
    likes: set[int] = set()
    previous: dict[tuple, Message] = {}
    for item in sorted(messages, key=lambda value: (value.create_time, value.id)):
        if item.id in questions:
            previous[item.identity] = item
            continue
        if not item.is_bot or item.category not in ANSWER_CATEGORIES or item.type not in ANSWER_TYPES:
            continue
        try:
            extra = json.loads(item.extra) if item.extra else {}
        except (ValueError, TypeError) as exc:
            raise ValueError("回复关联信息不是有效 JSON，无法可靠匹配提问") from exc
        if not isinstance(extra, dict):
            raise ValueError("回复关联信息不是对象，无法可靠匹配提问")
        if "parentMessageId" in extra:
            raw_parent = extra["parentMessageId"]
            if isinstance(raw_parent, bool) or not str(raw_parent).isdigit():
                diagnostics["invalid_parent"] += 1
                continue
            question = questions.get(int(raw_parent))
        else:
            question = previous.get(item.identity)
            diagnostics["sequence_matched"] += 1
        if (
            question is None
            or question.identity != item.identity
            or (question.create_time, question.id) >= (item.create_time, item.id)
        ):
            diagnostics["unmatched_answers"] += 1
            continue
        if question.id in selected:
            answered.add(question.id)
            if item.liked == 1:
                likes.add(item.id)
    return Totals(len(selected), len(answered), len(likes))


class QaStatisticsRepository:
    """仅封装 ORM 读取，兼容现有租户钩子，不访问模型提供商或业务写接口。"""

    def __init__(self, session) -> None:
        from bisheng.database.models.flow import FlowType
        from bisheng.database.models.message import ChatMessage
        from bisheng.database.models.session import MessageSession

        self.session = session
        self.Message, self.Chat, self.FlowType = ChatMessage, MessageSession, FlowType

    def collect(
        self, start: datetime | None, end: datetime, snapshot: datetime, *, batch_size: int, verbose: bool
    ) -> tuple[dict[str, Totals], Counter]:
        from sqlalchemy import and_, func, or_
        from sqlmodel import select

        msg, chat = self.Message, self.Chat
        totals = {label: Totals() for label in LABELS}
        diagnostics: Counter = Counter()
        trace("开始读取数据库消息快照边界", verbose)
        max_id = self.session.exec(select(func.max(msg.id)).where(msg.create_time < snapshot)).one() or 0

        # chat_id 是会话主键；额外校验派生消息的所有者、租户和应用与会话一致。
        def equal_or_null(left, right):
            return or_(left == right, and_(left.is_(None), right.is_(None)))

        join = and_(
            msg.chat_id == chat.chat_id,
            equal_or_null(msg.user_id, chat.user_id),
            equal_or_null(msg.tenant_id, chat.tenant_id),
            equal_or_null(msg.flow_id, chat.flow_id),
        )
        base = [msg.id <= max_id, msg.create_time < snapshot]
        after = None
        while True:
            statement = (
                select(chat.chat_id, chat.flow_type, chat.flow_id)
                .join(msg, join)
                .where(
                    *base,
                    msg.is_bot.is_(False),
                    msg.category == "question",
                    msg.create_time < end,
                    chat.flow_type.in_([self.FlowType.WORKSTATION.value, self.FlowType.KNOLEDGE_SPACE.value]),
                )
                .distinct()
                .order_by(chat.chat_id)
                .limit(batch_size)
            )
            if start is not None:
                statement = statement.where(msg.create_time >= start)
            if after is not None:
                statement = statement.where(chat.chat_id > after)
            candidates = self.session.exec(statement).all()
            if not candidates:
                break
            labels = {}
            for chat_id, flow_type, flow_id in candidates:
                if flow_type == self.FlowType.WORKSTATION.value:
                    labels[chat_id] = LABELS[0]
                elif re.fullmatch(r"space_[0-9]+_file_[0-9]+", flow_id or ""):
                    labels[chat_id] = LABELS[1]
            if labels:
                statement = (
                    select(*(getattr(msg, field) for field in Message.__dataclass_fields__))
                    .join(chat, join)
                    .where(*base, msg.chat_id.in_(labels), msg.category.in_(["question", *ANSWER_CATEGORIES]))
                    .order_by(msg.chat_id, msg.create_time, msg.id)
                )
                # 一批会话完全读完再查下一批；每次配对仅保存一个会话的消息。
                rows = self.session.exec(statement)
                for chat_id, group in groupby(rows, key=lambda row: row.chat_id):
                    result = count_messages([Message(*row) for row in group], start, end, diagnostics)
                    target = totals[labels[chat_id]]
                    target.questions += result.questions
                    target.success += result.success
                    target.likes += result.likes
                    diagnostics["conversations"] += 1
            after = candidates[-1].chat_id
            trace(
                f"已处理会话={diagnostics['conversations']}，提问={sum(t.questions for t in totals.values())}", verbose
            )
        return totals, diagnostics


def write_report(directory: Path, totals: dict[str, Totals]) -> Path:
    directory.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(directory):
        raise FileExistsError("输出目录已存在，请指定新目录")
    name = "智能问答与单文档问答统计.csv"
    with tempfile.TemporaryDirectory(dir=directory.parent, prefix=".portal-qa-") as staging:
        with (Path(staging) / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADERS)
            writer.writerows(totals[label].row(label) for label in LABELS)
            stream.flush()
            os.fsync(stream.fileno())
        if os.path.lexists(directory):
            raise FileExistsError("输出目录已存在，请指定新目录")
        Path(staging).rename(directory)
    return directory / name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-tenants", action="store_true", help="所有租户的现存问答记录")
    scope.add_argument("--tenant-id", type=int, help="严格限定记录所属租户")
    parser.add_argument("--start-date", type=date.fromisoformat, help="北京时间提问起始日期，包含当天；默认全部历史")
    parser.add_argument("--end-date", type=date.fromisoformat, help="北京时间提问结束日期，包含当天；默认截至运行时")
    parser.add_argument("--db-timezone", default="Asia/Shanghai", help="数据库无时区时间实际使用的时区")
    parser.add_argument("--config", help="后端配置文件名，与 config 环境变量一致")
    parser.add_argument("--batch-size", type=int, default=100, help="每批会话数量，1 至 500")
    parser.add_argument("--verbose", action="store_true", help="显示查询进度，不输出问答内容或用户信息")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs") / f"portal-qa-{datetime.now():%Y%m%d-%H%M%S-%f}"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    now = datetime.now(CHINA)
    end_date = args.end_date or now.date()
    if end_date > now.date() or (args.start_date and args.start_date > end_date):
        parser.error("日期范围无效：起始日期不能晚于结束日期，结束日期不能晚于北京时间今天")
    if (args.tenant_id is not None and args.tenant_id <= 0) or not 1 <= args.batch_size <= 500:
        parser.error("租户ID必须为正整数，每批会话数必须在 1 至 500 之间")
    try:
        if os.path.lexists(args.output_dir):
            raise FileExistsError("输出目录已存在，请指定新目录")
        zone = ZoneInfo(args.db_timezone)
        start = datetime.combine(args.start_date, time.min, CHINA) if args.start_date else None
        end = min(datetime.combine(end_date + timedelta(days=1), time.min, CHINA), now)
        if args.config:
            os.environ["config"] = args.config
        from bisheng.core.context.tenant import (
            bypass_tenant_filter,
            current_tenant_id,
            set_current_tenant_id,
            strict_tenant_filter,
        )
        from bisheng.core.database import get_sync_db_session
        from bisheng.core.database.tenant_filter import register_tenant_filter_events

        register_tenant_filter_events()
        token = set_current_tenant_id(args.tenant_id)
        try:
            context = bypass_tenant_filter() if args.all_tenants else strict_tenant_filter()
            with context, get_sync_db_session() as session:
                try:
                    totals, diagnostics = QaStatisticsRepository(session).collect(
                        start.astimezone(zone).replace(tzinfo=None) if start else None,
                        end.astimezone(zone).replace(tzinfo=None),
                        now.astimezone(zone).replace(tzinfo=None),
                        batch_size=args.batch_size,
                        verbose=args.verbose,
                    )
                finally:
                    session.rollback()
        finally:
            current_tenant_id.reset(token)
        target = write_report(args.output_dir, totals)
        print(f"提问范围：{start or '全部历史'} 至 {end}（不含）；回答查询截至 {now}（不含）。")
        print(
            f"统计范围：{'所有租户' if args.all_tenants else f'租户 {args.tenant_id}'}；数据来源：数据库 chatmessage、message_session。"
        )
        print("按提问计数：存在对应的最终 AI 回答记录即成功，不按回答内容或错误文案判断。无回答即按失败计入。")
        print("单文档问答失败时可能未保存提问；成功率仅代表现存记录，不代表真实请求成功率。")
        print("历史消息缺少门户入口标记，按问答会话类型识别，可能包含工作台和我的知识等同类入口。")
        print("无提问关联ID时按会话顺序配对；并发提问、跨轮重新生成可能导致配对不准确。正在生成的提问也会暂计无回答。")
        print("已物理删除或未保存的提问/回答无法还原；保留消息的已删除会话仍统计。点赞取查询时当前状态。")
        if diagnostics["invalid_parent"] or diagnostics["unmatched_answers"]:
            print(
                f"未匹配回答={diagnostics['unmatched_answers']}，无效提问关联={diagnostics['invalid_parent']}；未用于抵扣其他提问的失败数。"
            )
        for label in LABELS:
            item = totals[label]
            trace(
                f"{label} 总数={item.questions} 成功={item.success} 无回答={item.failed} 点赞={item.likes}",
                args.verbose,
            )
        print(f"输出文件：{target.resolve()}")
        return 0
    except Exception as exc:
        print(f"统计失败：{type(exc).__name__}；未生成可用的新报告。", file=sys.stderr)
        if isinstance(exc, (ValueError, FileExistsError)):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
