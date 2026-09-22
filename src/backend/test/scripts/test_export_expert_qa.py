# ruff: noqa: RUF003
"""验证 CSV 导出的业务口径、只读查询、租户边界和异常输出。"""

import csv
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, String, Table, create_engine, event
from sqlmodel import Session, SQLModel

from scripts.export_expert_qa import ExportRepository, export_csv, organization_fields, read_people


@pytest.fixture()
def repository():
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
    from bisheng.core.database import tenant_filter

    repo = ExportRepository(None)
    # 全局测试夹具模拟了用户模型；这里只替代读取的三列，其他表和租户钩子均使用实际实现。
    table = SQLModel.metadata.tables.get("user")
    if table is None:
        table = Table(
            "user",
            SQLModel.metadata,
            Column("user_id", Integer, primary_key=True),
            Column("user_name", String),
            Column("external_id", String),
            Column("password", String),
        )
    repo.User = SimpleNamespace(__table__=table, **{column.name: column for column in table.columns})
    engine = create_engine("sqlite://")
    models = [
        repo.Question,
        repo.Answer,
        repo.Adopt,
        repo.Expert,
        repo.User,
        repo.Department,
        repo.Membership,
        repo.Dictionary,
        repo.Comment,
        repo.AnswerVote,
    ]
    for model in models:
        model.__table__.create(engine, checkfirst=True)
    tenant_filter.register_tenant_filter_events()
    # 共享测试进程可能已注册钩子；刷新已加载模型名单。
    tenant_filter._tenant_aware_tables = tenant_filter._discover_tenant_aware_tables()
    time = datetime(2026, 9, 20, 10)
    with engine.begin() as connection:
        connection.execute(
            repo.Question.__table__.insert(),
            [
                {
                    "id": 1,
                    "tenant_id": 1,
                    "user_id": 10,
                    "title": "问题一",
                    "description": "<p>描述</p>",
                    "business_domain": "设备",
                    "created_at": time,
                    "view_count": 30,
                    "resolved_at": datetime(2026, 9, 20, 12),
                },
                {
                    "id": 2,
                    "tenant_id": 1,
                    "user_id": 10,
                    "title": "问题二",
                    "description": "",
                    "business_domain": "设备",
                    "created_at": time,
                    "view_count": 12,
                    "resolved_at": None,
                },
                {
                    "id": 3,
                    "tenant_id": 2,
                    "user_id": 10,
                    "title": "其他租户",
                    "description": "",
                    "business_domain": "设备",
                    "created_at": time,
                    "view_count": 99,
                    "resolved_at": None,
                },
                {
                    "id": 4,
                    "tenant_id": 1,
                    "user_id": 10,
                    "title": "日期范围外",
                    "description": "",
                    "business_domain": "设备",
                    "created_at": datetime(2026, 9, 21),
                    "view_count": 99,
                    "resolved_at": None,
                },
            ],
        )
        connection.execute(
            repo.Answer.__table__.insert(),
            [
                {
                    "id": 11,
                    "tenant_id": 1,
                    "question_id": 1,
                    "expert_id": 1,
                    "user_id": 20,
                    "content": '<p>第一行, "引用"</p><p>第二行</p>',
                    "status": 1,
                    "adopted": True,
                    "vote_count": 5,
                    "created_at": time,
                    "anonymous": 0,
                },
                {
                    "id": 12,
                    "tenant_id": 1,
                    "question_id": 1,
                    "expert_id": 1,
                    "user_id": 20,
                    "content": "=SUM(1,2)",
                    "status": 1,
                    "adopted": False,
                    "vote_count": 3,
                    "created_at": datetime(2026, 9, 20, 11),
                    "anonymous": 1,
                },
                {
                    "id": 13,
                    "tenant_id": 1,
                    "question_id": 1,
                    "expert_id": 1,
                    "user_id": 20,
                    "content": "删除回答",
                    "status": 3,
                    "adopted": True,
                    "vote_count": 99,
                    "created_at": datetime(2026, 9, 19),
                    "anonymous": 0,
                },
                {
                    "id": 14,
                    "tenant_id": 2,
                    "question_id": 1,
                    "expert_id": 1,
                    "user_id": 20,
                    "content": "其他租户回答",
                    "status": 1,
                    "adopted": False,
                    "vote_count": 99,
                    "created_at": time,
                    "anonymous": 0,
                },
            ],
        )
        connection.execute(
            repo.Adopt.__table__.insert(),
            [
                {
                    "tenant_id": 1,
                    "question_id": 1,
                    "answer_id": 11,
                    "expert_user_id": 20,
                    "adopted_by": 10,
                    "created_at": datetime(2026, 9, 20, 12),
                },
                {
                    "tenant_id": 1,
                    "question_id": 1,
                    "answer_id": 13,
                    "expert_user_id": 20,
                    "adopted_by": 10,
                    "created_at": time,
                },
            ],
        )
        connection.execute(
            repo.Expert.__table__.insert(),
            {
                "id": 1,
                "tenant_id": 1,
                "user_id": 20,
                "expert_name": "专家",
                "major": "m",
                "position": "p",
                "job_family": "f",
                "job_category": "c",
                "depart_ment": "2",
            },
        )
        connection.execute(
            repo.User.__table__.insert(),
            [
                {"user_id": 10, "user_name": "提问者", "external_id": "asker", "password": "unused"},
                {"user_id": 20, "user_name": "专家", "external_id": "expert", "password": "unused"},
            ],
        )
        connection.execute(
            repo.Department.__table__.insert(),
            [
                {"id": 1, "tenant_id": 1, "dept_id": "d1", "name": "公司", "parent_id": None, "org_level": "company"},
                {"id": 2, "tenant_id": 1, "dept_id": "d2", "name": "组织", "parent_id": 1, "org_level": "dept"},
                {
                    "id": 3,
                    "tenant_id": 2,
                    "dept_id": "d3",
                    "name": "其他租户组织",
                    "parent_id": None,
                    "org_level": "dept",
                },
            ],
        )
        connection.execute(
            repo.Membership.__table__.insert(), {"id": 1, "user_id": 10, "department_id": 2, "is_primary": 1}
        )
        connection.execute(
            repo.Dictionary.__table__.insert(),
            [
                {"tenant_id": 1, "type": "expert_major", "dict_key": "m", "dict_value": "岗位甲"},
                {"tenant_id": 1, "type": "expert_position", "dict_key": "p", "dict_value": "职务乙"},
                {"tenant_id": 2, "type": "expert_major", "dict_key": "m", "dict_value": "错误岗位"},
            ],
        )
    token = set_current_tenant_id(1)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
    try:
        with strict_tenant_filter(), Session(engine) as session:
            repo.session = session
            yield repo, statements
            session.rollback()
    finally:
        current_tenant_id.reset(token)
        engine.dispose()


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_export_counts_identity_dates_and_csv_round_trip(repository, tmp_path):
    repo, statements = repository
    output = tmp_path / "report"
    people = {"asker": {"部门": "设备部", "科室": "技术室", "岗位": "技术员"}}
    result = export_csv(repo, output, date(2026, 9, 20), date(2026, 9, 20), people)
    summaries, details = rows(output / "问题汇总.csv"), rows(output / "回答明细.csv")
    assert result == {"问题数": 2, "有效回答数": 2, "明细行数": 3}
    assert sum(int(row["浏览数"]) for row in summaries) == 42
    assert summaries[0]["有用总数"] == "8"
    assert summaries[0]["回答数"] == "2" and summaries[0]["采纳数"] == "1"
    assert summaries[0]["首个有效回答时间"] == "2026-09-20 10:00:00"
    assert summaries[0]["提问人岗位"] == "技术员"
    assert summaries[0]["提问人部门"] == "组织"
    assert summaries[0]["提问人科室"] == ""
    assert summaries[0]["提问人组织路径"] == "公司 / 组织"
    assert details[0]["回答"] == '第一行, "引用"\n\n第二行'
    assert details[0]["专家岗位"] == "岗位甲" and details[0]["专家职务"] == "职务乙"
    assert details[0]["专家部门"] == "组织"
    assert details[0]["采纳时间"] == "2026-09-20 12:00:00"
    assert details[1]["回答"] == "'=SUM(1,2)"
    assert details[1]["专家姓名"] == "匿名用户"
    assert details[1]["专家账号"] == details[1]["专家岗位"] == details[1]["专家组织路径"] == ""
    assert details[2]["回答ID"] == details[2]["专家姓名"] == ""
    assert summaries[1]["首个有效回答时间"] == ""
    assert summaries[1]["其它用户首次追问时间"] == summaries[1]["首次有用点击时间"] == ""
    assert details[0]["其它用户首次点赞时间"] == details[0]["首次有用点击时间"] == ""
    assert details[2]["其它用户首次点赞时间"] == details[2]["首次有用点击时间"] == ""
    assert (output / "回答明细.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert not (output / "未完成.txt").exists()
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


def test_export_refuses_overwrite_and_marks_query_failure(repository, tmp_path):
    repo, _ = repository
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        export_csv(repo, existing)
    assert list(existing.iterdir()) == []

    class BrokenRepository:
        def reference_data(self):
            raise RuntimeError("数据库不可用")

    with pytest.raises(RuntimeError):
        export_csv(BrokenRepository(), tmp_path / "failed")
    assert (tmp_path / "failed" / "未完成.txt").exists()


def test_people_csv_rejects_duplicate_accounts(tmp_path):
    path = tmp_path / "people.csv"
    path.write_text("external_id,部门,科室,岗位\n001,部门甲,科室乙,岗位丙\n", encoding="utf-8-sig")
    assert read_people(path)["001"]["岗位"] == "岗位丙"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("001,重复,,\n")
    with pytest.raises(ValueError, match="重复"):
        read_people(path)


def test_multiple_adoptions_and_keyset_paging(repository, tmp_path):
    repo, _ = repository
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter():
        repo.session.execute(repo.Answer.__table__.update().where(repo.Answer.id == 12).values(adopted=True))
        repo.session.execute(
            repo.Adopt.__table__.insert().values(
                tenant_id=1,
                question_id=1,
                answer_id=12,
                expert_user_id=20,
                adopted_by=10,
                created_at=datetime(2026, 9, 20, 13),
            )
        )
        repo.session.execute(
            repo.Question.__table__.insert(),
            [
                {
                    "id": 100 + index,
                    "tenant_id": 1,
                    "user_id": 10,
                    "title": f"分页问题{index}",
                    "description": "",
                    "business_domain": "设备",
                    "created_at": datetime(2026, 9, 20),
                }
                for index in range(400)
            ],
        )
    output = tmp_path / "pages"
    totals = export_csv(repo, output, date(2026, 9, 20), date(2026, 9, 20))
    summaries, details = rows(output / "问题汇总.csv"), rows(output / "回答明细.csv")
    assert totals["问题数"] == 402
    assert len({row["问题ID"] for row in summaries}) == 402
    assert summaries[0]["采纳数"] == "2"
    assert [row["采纳时间"] for row in details[:2]] == ["2026-09-20 12:00:00", "2026-09-20 13:00:00"]
    assert all(row["是否采纳"] == "是" for row in details[:2])
    assert summaries[0]["提问人部门"] == "组织"
    assert summaries[0]["提问人岗位"] == ""


@pytest.mark.parametrize(
    "leaf,expected",
    [
        (4, {"部门": "设备部", "科室": "技术室"}),
        (2, {"部门": "设备部", "科室": ""}),
        (1, {"部门": "", "科室": ""}),
        (5, {"部门": "", "科室": ""}),
        (6, {"部门": "", "科室": "循环科室"}),
        (7, {"部门": "设备部", "科室": "技术室"}),
        (8, {"部门": "设备部", "科室": ""}),
    ],
)
def test_organization_uses_labels_not_depth_or_names(leaf, expected):
    departments = {
        1: {"name": "公司", "org_level": "company", "parent_id": None},
        2: {"name": "设备部", "org_level": "dept", "parent_id": 1},
        3: {"name": "技术室", "org_level": "office", "parent_id": 8},
        4: {"name": "班组", "org_level": "squad", "parent_id": 3},
        5: {"name": "未打标科室", "org_level": None, "parent_id": 1},
        6: {"name": "循环科室", "org_level": "office", "parent_id": 6},
        7: {"name": "未打标的用户组织", "org_level": None, "parent_id": 3},
        8: {"name": "未打标的中间组织", "org_level": None, "parent_id": 2},
    }
    assert organization_fields(leaf, departments) == expected


def test_empty_selection_still_writes_headers(repository, tmp_path):
    repo, _ = repository
    output = tmp_path / "empty"
    totals = export_csv(repo, output, date(2030, 1, 1), date(2030, 1, 2))
    assert totals == {"问题数": 0, "有效回答数": 0, "明细行数": 0}
    assert rows(output / "问题汇总.csv") == rows(output / "回答明细.csv") == []


def test_first_interactions_exclude_self_comments_and_inactive_answers(repository, tmp_path):
    repo, statements = repository
    with repo.session.bind.begin() as connection:
        connection.execute(
            repo.Comment.__table__.insert(),
            [
                {
                    "question_id": qid,
                    "answer_id": 0,
                    "tenant_id": tid,
                    "user_id": uid,
                    "is_follow_up": followup,
                    "content": "追问或评论",
                    "created_at": datetime(2026, 9, 20, hour),
                }
                for qid, tid, uid, followup, hour in [
                    (1, 1, 10, True, 8),  # 原提问人的更早追问不计入。
                    (1, 1, 30, False, 9),  # 其他用户的普通评论不计入。
                    (1, 1, 30, True, 13),
                    (1, 1, 40, True, 12),  # 最早的其他用户追问。
                    (1, 2, 50, True, 7),  # 其他租户的记录不计入。
                    (2, 1, 10, True, 8),
                ]
            ],
        )
        connection.execute(
            repo.AnswerVote.__table__.insert(),
            [
                {"answer_id": aid, "user_id": uid, "vote_type": kind, "created_at": datetime(2026, 9, 20, hour)}
                for aid, uid, kind, hour in [
                    (11, 20, "helpful", 11),  # 作者自己点击有用。
                    (11, 30, "helpful", 15),
                    (11, 40, "helpful", 14),  # 最早的其他用户点击有用。
                    (11, 50, "support", 8),  # 历史支持记录不能冒充有用。
                    (12, 20, "helpful", 10),  # 另一条匿名回答的自赞，汇总仍计入。
                    (13, 30, "helpful", 7),  # 已删除回答不计入。
                    (14, 30, "helpful", 6),  # 其他租户的回答不计入。
                ]
            ],
        )
    statements.clear()
    output = tmp_path / "interactions"
    export_csv(repo, output, date(2026, 9, 20), date(2026, 9, 20))
    summaries, details = rows(output / "问题汇总.csv"), rows(output / "回答明细.csv")
    assert summaries[0]["其它用户首次追问时间"] == "2026-09-20 12:00:00"
    assert summaries[0]["首次有用点击时间"] == "2026-09-20 10:00:00"
    assert details[0]["其它用户首次点赞时间"] == "2026-09-20 14:00:00"
    assert details[0]["首次有用点击时间"] == "2026-09-20 11:00:00"
    assert details[1]["其它用户首次点赞时间"] == ""
    assert details[1]["首次有用点击时间"] == "2026-09-20 10:00:00"
    assert summaries[1]["其它用户首次追问时间"] == summaries[1]["首次有用点击时间"] == ""
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


@pytest.mark.parametrize("expert_id,expected", [(1, "2026-09-20 13:00:00"), (None, "")])
def test_first_other_vote_resolves_legacy_author_or_leaves_blank(repository, tmp_path, expert_id, expected):
    repo, _ = repository
    with repo.session.bind.begin() as connection:
        connection.execute(
            repo.Answer.__table__.update().where(repo.Answer.id == 11).values(user_id=None, expert_id=expert_id)
        )
        connection.execute(
            repo.AnswerVote.__table__.insert(),
            [
                {"answer_id": 11, "user_id": uid, "vote_type": "helpful", "created_at": datetime(2026, 9, 20, hour)}
                for uid, hour in [(20, 12), (30, 13)]
            ],
        )
    output = tmp_path / "legacy-author"
    export_csv(repo, output)
    detail = rows(output / "回答明细.csv")[0]
    assert detail["其它用户首次点赞时间"] == expected
    assert detail["首次有用点击时间"] == "2026-09-20 12:00:00"
