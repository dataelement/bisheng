#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""只读导出专家问答为问题汇总、回答明细 CSV。

在 src/backend 执行：
    .venv/bin/python scripts/export_expert_qa.py --tenant-id 1 --output-dir /tmp/qa-export
可选 --start-date 2026-09-01 --end-date 2026-09-30 --people-csv people.csv。
仅查询数据库，不调用增加浏览数的详情接口，不提交事务，不覆盖已有输出目录。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

ASKER_FIELDS = ["提问人姓名", "提问人部门", "提问人科室", "提问人岗位"]
EXPERT_FIELDS = ["专家姓名", "专家部门", "专家科室", "专家岗位", "专家职务", "专家职位族", "专家职位类"]
QUESTION_FIELDS = ["问题", "业务域", "问题描述", "提问时间", "首个有效回答时间", "回答数", "采纳数", "浏览数"]
DETAIL_FIELDS = (
    ASKER_FIELDS
    + EXPERT_FIELDS
    + [
        "问题",
        "业务域",
        "问题描述",
        "回答",
        "提问时间",
        "首个有效回答时间",
        "采纳时间",
        "回答数",
        "采纳数",
        "有用数",
        "浏览数",
        "问题ID",
        "回答ID",
        "回答时间",
        "是否采纳",
        "提问人账号",
        "专家账号",
        "提问人组织路径",
        "专家组织路径",
        "采纳时间说明",
        "其它用户首次点赞时间",
        "首次有用点击时间",
    ]
)
SUMMARY_FIELDS = [
    "问题ID",
    *ASKER_FIELDS,
    *QUESTION_FIELDS,
    "首次采纳时间",
    "有用总数",
    "状态",
    "提问人账号",
    "提问人组织路径",
    "采纳时间说明",
    "其它用户首次追问时间",
    "首次有用点击时间",
]
CAREER_TYPES = {
    "major": "expert_major",
    "position": "expert_position",
    "job_family": "expert_job_family",
    "job_category": "expert_job_category",
}
TIME_NOTE = "历史迁移可能以回答创建时间补填；不能视为精确的历史采纳操作时间"


class TextExtractor(HTMLParser):
    """保留段落、换行与图片替代说明，避免把富文本标签导入表格。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipped = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.skipped += 1
        if not self.skipped:
            if tag in {"br", "p", "div", "li", "tr"}:
                self.parts.append("\n")
            elif tag == "img":
                self.parts.append(f"[图片：{dict(attrs).get('alt') or '见原问题或回答'}]")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skipped = max(0, self.skipped - 1)
        elif not self.skipped and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipped:
            self.parts.append(data)


def plain_text(value: Any) -> str:
    value = str(value or "")
    if not re.search(r"</?[a-zA-Z][^>]*>", value):
        return value
    parser = TextExtractor()
    parser.feed(value)
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()


def csv_value(value: Any) -> Any:
    """把不可信文本作为文本写入，防止 Excel 将其解释为公式。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def read_people(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"external_id", "岗位"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("人员补充 CSV 必须包含 external_id、岗位 列")
        people = {}
        for line, row in enumerate(reader, 2):
            account = (row.get("external_id") or "").strip()
            if not account or account in people:
                raise ValueError(f"人员补充 CSV 第 {line} 行账号为空或重复")
            people[account] = {key: (row.get(key) or "").strip() for key in required}
        return people


class ExportRepository:
    """只读查询入口；使用项目会话和自动租户过滤，按问题分批读取。"""

    def __init__(self, session: Any) -> None:
        from bisheng.database.models.department import Department, UserDepartment
        from bisheng.database.models.qa_expert import Answer, AnswerAdopt, AnswerVote, Comment, Expert, Question
        from bisheng.dictionary.domain.models.system_dictionary import SystemDictionary
        from bisheng.user.domain.models.user import User

        self.session = session
        self.Question, self.Answer, self.Adopt = Question, Answer, AnswerAdopt
        self.Expert, self.User = Expert, User
        self.Comment, self.AnswerVote = Comment, AnswerVote
        self.Department, self.Membership, self.Dictionary = Department, UserDepartment, SystemDictionary

    def rows(self, statement: Any) -> list[dict]:
        return [dict(row) for row in self.session.execute(statement).mappings()]

    @staticmethod
    def columns(model: Any, names: str) -> list:
        return [getattr(model, name) for name in names.split()]

    def select(self, model: Any, names: str) -> Any:
        from sqlalchemy import select

        return select(*self.columns(model, names))

    def lookup(self, model: Any, names: str, key: str, ids: set[int]) -> list[dict]:
        result = []
        ordered = sorted(ids)
        for offset in range(0, len(ordered), 400):
            result.extend(
                self.rows(self.select(model, names).where(getattr(model, key).in_(ordered[offset : offset + 400])))
            )
        return result

    def reference_data(self) -> tuple[dict, dict]:
        departments = self.rows(self.select(self.Department, "id name parent_id org_level"))
        dictionaries = self.rows(self.select(self.Dictionary, "type dict_key dict_value"))
        return (
            {row["id"]: row for row in departments},
            {(row["type"], row["dict_key"]): row["dict_value"] for row in dictionaries},
        )

    def batches(self, start: date | None, end: date | None):
        last_id = 0
        while True:
            q = self.Question
            statement = self.select(
                q,
                "id user_id title description business_domain created_at "
                "view_count question_type asker_anonymous asker_reveal_on_public resolved_at",
            )
            statement = statement.where(q.id > last_id)
            if start:
                statement = statement.where(q.created_at >= datetime.combine(start, datetime.min.time()))
            if end:
                statement = statement.where(
                    q.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time())
                )
            questions = self.rows(statement.order_by(q.id).limit(400))
            if not questions:
                break
            ids = {row["id"] for row in questions}
            answers = self.lookup(
                self.Answer,
                "id question_id expert_id user_id expert_name content status "
                "anonymous reveal_on_public vote_count adopted created_at",
                "question_id",
                ids,
            )
            answers = [row for row in answers if row["status"] != 3]
            adopts = self.lookup(self.Adopt, "question_id answer_id created_at", "question_id", ids)
            experts = self.lookup(
                self.Expert,
                "id user_id expert_name depart_ment major position job_family job_category",
                "id",
                {row["expert_id"] for row in answers if row["expert_id"]},
            )
            user_ids = {row["user_id"] for row in questions + answers + experts if row.get("user_id")}
            users = self.lookup(self.User, "user_id user_name external_id", "user_id", user_ids)
            memberships = self.lookup(self.Membership, "user_id department_id is_primary", "user_id", user_ids)
            comments = self.lookup(self.Comment, "question_id user_id is_follow_up created_at", "question_id", ids)
            # 投票表没有租户字段，仅查询本租户已筛选的有效回答，避免无关或已删除回答参与统计。
            votes = self.lookup(
                self.AnswerVote, "answer_id user_id vote_type created_at", "answer_id", {row["id"] for row in answers}
            )
            yield questions, answers, adopts, experts, users, memberships, comments, votes
            last_id = questions[-1]["id"]


def organization_path(department_id: Any, departments: dict) -> str:
    try:
        current = int(department_id)
    except (TypeError, ValueError):
        return ""
    parts, seen = [], set()
    while current in departments and current not in seen:
        seen.add(current)
        row = departments[current]
        parts.append(row["name"])
        current = row["parent_id"]
    return " / ".join(reversed(parts))


def organization_fields(department_id: Any, departments: dict) -> dict[str, str]:
    """沿主组织的父链提取最近的部门、科室；未打标不按深度或名称猜测。"""
    result = {"部门": "", "科室": ""}
    try:
        current = int(department_id)
    except (TypeError, ValueError):
        return result
    seen = set()
    labels = {"dept": "部门", "office": "科室"}
    while current in departments and current not in seen:
        seen.add(current)
        row = departments[current]
        label = labels.get(row.get("org_level"))
        if label and not result[label]:
            result[label] = row["name"]
        current = row["parent_id"]
    return result


def build_rows(batch: tuple, departments: dict, dictionaries: dict, people: dict):
    questions, answers, adopts, experts, users, memberships, comments, votes = batch
    expert_map = {row["id"]: row for row in experts}
    user_map = {row["user_id"]: row for row in users}
    primary = defaultdict(list)
    for member in memberships:
        if member["is_primary"] == 1 and member["department_id"] in departments:
            primary[member["user_id"]].append(member["department_id"])
    grouped = defaultdict(list)
    for answer in answers:
        grouped[answer["question_id"]].append(answer)
    adopt_map = {row["answer_id"]: row for row in adopts}
    followups = defaultdict(list)
    for comment in comments:
        if comment["is_follow_up"]:
            followups[comment["question_id"]].append(comment)
    helpful_votes = defaultdict(list)
    for vote in votes:
        if vote["vote_type"] == "helpful":
            helpful_votes[vote["answer_id"]].append(vote)

    def identity(
        user_id: int | None,
        fallback: str,
        anonymous: bool,
        reveal: Any,
        question: dict,
        prefix: str,
        expert: dict | None = None,
    ) -> dict:
        masked = bool(anonymous) and not (question["question_type"] == "public" and bool(reveal))
        result = {f"{prefix}{key}": "" for key in ["姓名", "账号", "部门", "科室", "岗位", "组织路径"]}
        if masked:
            result[f"{prefix}姓名"] = "匿名用户"
            return result
        user = user_map.get(user_id, {})
        account = user.get("external_id") or ""
        extra = people.get(account, {})
        result[f"{prefix}姓名"] = user.get("user_name") or fallback or ""
        result[f"{prefix}账号"] = account
        result[f"{prefix}岗位"] = extra.get("岗位", "")
        department_ids = primary.get(user_id, [])
        department_id = department_ids[0] if len(department_ids) == 1 else None
        if not department_ids and expert:
            department_id = expert.get("depart_ment")
        result[f"{prefix}组织路径"] = organization_path(department_id, departments)
        for field, value in organization_fields(department_id, departments).items():
            result[f"{prefix}{field}"] = value
        if expert:
            for label, field in [
                ("岗位", "major"),
                ("职务", "position"),
                ("职位族", "job_family"),
                ("职位类", "job_category"),
            ]:
                key = expert.get(field) or ""
                result[f"{prefix}{label}"] = dictionaries.get((CAREER_TYPES[field], key), key) or result.get(
                    f"{prefix}{label}", ""
                )
        return result

    for question in questions:
        active = sorted(grouped[question["id"]], key=lambda row: (row["created_at"], row["id"]))
        accepted = [row for row in active if row["adopted"] or row["id"] in adopt_map]
        asker = identity(
            question["user_id"], "", question["asker_anonymous"], question["asker_reveal_on_public"], question, "提问人"
        )
        common = {
            **asker,
            "问题ID": question["id"],
            "问题": question["title"],
            "业务域": question["business_domain"],
            "问题描述": plain_text(question["description"]),
            "提问时间": question["created_at"],
            "首个有效回答时间": active[0]["created_at"] if active else "",
            "回答数": len(active),
            "采纳数": len(accepted),
            "浏览数": question["view_count"] or 0,
        }
        summary = {
            **common,
            "首次采纳时间": question["resolved_at"] or "",
            "有用总数": sum(row["vote_count"] or 0 for row in active),
            "状态": "已解决" if accepted else "待采纳" if active else "待回答",
            "采纳时间说明": TIME_NOTE if question["resolved_at"] else "",
            "其它用户首次追问时间": min(
                (row["created_at"] for row in followups[question["id"]] if row["user_id"] != question["user_id"]),
                default="",
            ),
            "首次有用点击时间": min(
                (vote["created_at"] for answer in active for vote in helpful_votes[answer["id"]]), default=""
            ),
        }
        details = []
        for answer in active:
            expert = expert_map.get(answer["expert_id"], {})
            author_id = answer["user_id"] or expert.get("user_id")
            author = identity(
                author_id,
                answer["expert_name"],
                answer["anonymous"],
                answer["reveal_on_public"],
                question,
                "专家",
                expert,
            )
            adopted = answer in accepted
            adoption = adopt_map.get(answer["id"], {})
            details.append(
                {
                    **common,
                    **author,
                    "回答ID": answer["id"],
                    "回答": plain_text(answer["content"]),
                    "回答时间": answer["created_at"],
                    "是否采纳": "是" if adopted else "否",
                    "采纳时间": adoption.get("created_at", ""),
                    "有用数": answer["vote_count"] or 0,
                    "采纳时间说明": TIME_NOTE if adoption else "缺少采纳时间记录" if adopted else "",
                    "其它用户首次点赞时间": min(
                        (
                            vote["created_at"]
                            for vote in helpful_votes[answer["id"]]
                            if author_id is not None and vote["user_id"] != author_id
                        ),
                        default="",
                    ),
                    "首次有用点击时间": min((vote["created_at"] for vote in helpful_votes[answer["id"]]), default=""),
                }
            )
        if not details:
            details.append({**common, "有用数": 0})
        yield summary, details


def export_csv(
    repository: ExportRepository,
    output: Path,
    start: date | None = None,
    end: date | None = None,
    people: dict | None = None,
) -> dict:
    # 新目录是一次导出的边界；失败保留说明，避免部分文件被误认为成功。
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    marker = output / "未完成.txt"
    marker.write_text("导出未完成，请勿使用本目录的部分 CSV。\n", encoding="utf-8")
    totals = {"问题数": 0, "有效回答数": 0, "明细行数": 0}
    departments, dictionaries = repository.reference_data()
    with (
        (output / "问题汇总.csv").open("x", encoding="utf-8-sig", newline="") as summary_file,
        (output / "回答明细.csv").open("x", encoding="utf-8-sig", newline="") as detail_file,
    ):
        summary_writer = csv.DictWriter(summary_file, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        detail_writer = csv.DictWriter(detail_file, fieldnames=DETAIL_FIELDS, extrasaction="ignore")
        summary_writer.writeheader()
        detail_writer.writeheader()
        for batch in repository.batches(start, end):
            for summary, details in build_rows(batch, departments, dictionaries, people or {}):
                summary_writer.writerow({key: csv_value(value) for key, value in summary.items()})
                detail_writer.writerows({key: csv_value(value) for key, value in row.items()} for row in details)
                totals["问题数"] += 1
                totals["有效回答数"] += summary["回答数"]
                totals["明细行数"] += len(details)
    with (output / "人员补充模板.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerow(["external_id", "岗位"])
    (output / "导出口径.txt").write_text(
        "按提问日期筛选，结束日期包含当天；回答、采纳、计数为导出时的当前数据，不是历史时点快照。\n"
        "每个问题一行汇总；每个有效回答一行明细；未回答问题保留一行。评论、追问和已删除回答不计入回答数。\n"
        "回答明细中的问题回答数、采纳数、浏览数重复展示，汇总请使用问题汇总.csv。\n"
        "时间按数据库保存的北京时间输出；首次有效回答时间按当前未删除回答计算。\n"
        "其它用户首次追问时间：该问题 is_follow_up=true 的最早记录，排除原提问人，不含普通评论。\n"
        "其它用户首次点赞时间：本回答最早的 helpful 记录，排除回答作者；作者无法确认时留空。\n"
        "首次有用点击时间：本回答最早的 helpful 记录，包含作者；问题汇总取所有有效回答的最早值。\n"
        "回答点赞与有用在当前后端为同一操作；上述时间仅依据现存记录，取消或删除的历史操作无法还原。\n"
        "首次采纳时间取问题 resolved_at；回答采纳时间取独立采纳记录。" + TIME_NOTE + "。\n"
        "姓名、组织、专家岗位取当前档案；部门、科室沿主组织父链按 org_level=dept/office 自动查询。\n"
        "未打标时继续向上查找至根节点，找不到部门或科室的对应字段留空；补充 CSV 仅填补缺失岗位。\n"
        "匿名且未允许转公开展示的人员隐藏姓名、账号及组织岗位字段。\n"
        "业务域保留数据库原值；图片用占位文字，不导出附件二进制。以公式符号开头的文本加单引号。\n"
        "本脚本面向有数据库读取权限的运维人员，导出指定租户公开和定向问题，不模拟页面用户权限。\n"
        "导出期间请避免数据变更；不同数据库的事务隔离可能影响跨批次一致性。\n"
        + json.dumps(totals, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    marker.unlink()
    return totals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True, help="仅导出这个租户的数据")
    parser.add_argument("--config", help="项目配置文件，与 execute_sql.py 一致")
    parser.add_argument("--output-dir", type=Path, required=True, help="必须为尚不存在的目录")
    parser.add_argument("--start-date", type=date.fromisoformat, help="提问日期起点，YYYY-MM-DD")
    parser.add_argument("--end-date", type=date.fromisoformat, help="提问日期终点，包含当天")
    parser.add_argument("--people-csv", type=Path, help="按 external_id 匹配的人员补充表")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.tenant_id <= 0 or (args.start_date and args.end_date and args.start_date > args.end_date):
        parser.error("租户ID必须为正整数，开始日期不得晚于结束日期")
    try:
        people = read_people(args.people_csv)
        if args.output_dir.exists():
            raise ValueError("输出目录已存在，请指定新目录")
        if args.config:
            os.environ["config"] = args.config
        from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
        from bisheng.core.database import get_sync_db_session

        token = set_current_tenant_id(args.tenant_id)
        try:
            # 先加载所需模型，确保会话初始化时能发现全部租户表（含系统字典）。
            repository = ExportRepository(None)
            from bisheng.core.database.tenant_filter import register_tenant_filter_events

            register_tenant_filter_events()
            with strict_tenant_filter(), get_sync_db_session() as session:
                repository.session = session
                try:
                    totals = export_csv(repository, args.output_dir, args.start_date, args.end_date, people)
                finally:
                    session.rollback()
        finally:
            current_tenant_id.reset(token)
        print(
            json.dumps(
                {"输出目录": str(args.output_dir.resolve()), "租户ID": args.tenant_id, **totals}, ensure_ascii=False
            )
        )
        return 0
    except Exception as exc:
        # 不打印连接串或完整数据库异常，避免配置中的凭据被日志泄露。
        print(f"导出失败：{type(exc).__name__}；请检查参数、配置与数据库表结构。", file=sys.stderr)
        if isinstance(exc, (ValueError, FileExistsError)):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
