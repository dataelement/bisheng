# ruff: noqa: RUF002, RUF003
"""用独立业务样例验证科室报表，避免把五列相加冒充贡献去重。"""

import csv
import shutil
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.export_office_metrics import (
    CHINA,
    LOGIN_INDEX,
    OFFICES,
    QA_INDEX,
    RAW_INDEX,
    CsvReport,
    EsReader,
    Metrics,
    OfficeRepository,
    OrganizationScope,
    collect_database,
    collect_events,
    main,
    write_rules,
)


def test_single_file_help_without_companion_scripts(tmp_path):
    import ast

    from scripts import export_office_metrics as cli

    standalone = tmp_path / "scripts" / "export_office_metrics.py"
    standalone.parent.mkdir()
    shutil.copyfile(cli.__file__, standalone)
    result = subprocess.run(
        [sys.executable, "-I", str(standalone), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--company-department-id" in result.stdout
    tree = ast.parse(Path(cli.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("scripts")


def scope_fixture():
    departments = [
        {"id": 1, "parent_id": None, "path": "/1/", "name": "公司", "org_level": "dept"},
        {"id": 2, "parent_id": 1, "path": "/1/2/", "name": "制造部", "org_level": "dept"},
        {"id": 3, "parent_id": 1, "path": "/1/3/", "name": "其他部门", "org_level": "dept"},
    ]
    departments += [
        {"id": 10 + i, "parent_id": 2, "path": f"/1/2/{10 + i}/", "name": name, "org_level": "office"}
        for i, name in enumerate(OFFICES)
    ]
    departments += [
        {"id": 30, "parent_id": 10, "path": "/1/2/10/30/", "name": "子组", "org_level": None},
        {"id": 31, "parent_id": 2, "path": "/1/2/31/", "name": "其他科室", "org_level": "office"},
    ]
    memberships = [
        {"user_id": user, "department_id": dep, "user_name": str(user)}
        for user, dep in [(101, 30), (102, 11), (103, 2), (104, 3), (105, 31)]
    ]
    return OrganizationScope(departments, memberships, 1, 2)


def test_distinct_documents_and_different_ratio_denominators():
    metrics = Metrics(scope_fixture())
    for fid, doc, user, level, owner in [
        (1, 50, 101, "personal", 101),
        (2, 50, 101, "department", 2),
        (3, 50, 101, "public", 1),
        (4, 51, 102, "team_ks", 11),
        (5, 52, 103, "team", 2),
        (6, 53, 104, "department", 2),
    ]:
        metrics.file(
            {
                "file_id": fid,
                "document_id": doc,
                "user_id": user,
                "level": level,
                "owner_id": owner,
                "owner_type": "department",
                "space_id": fid,
            }
        )
    for eid, uid in [(1, 101), (2, 101), (3, 102), (4, 103), (5, 104), (6, 105)]:
        metrics.login({"event_id": str(eid), "user_id": uid, "timestamp": 1000 + eid})
    duplicate = metrics.login({"event_id": "1", "user_id": 101, "timestamp": 1001})
    assert duplicate["counted"] == 0
    for typ, qid, uid in [
        ("smart", "q1", 101),
        ("document", "q2", 101),
        ("expert", "q3", 102),
        ("expert", "q4", 103),
        ("smart", "q5", 104),
    ]:
        metrics.question({"qa_type": typ, "question_id": qid, "user_id": uid, "timestamp": 2000})
    metrics.question({"qa_type": "expert", "question_id": "q3", "user_id": 102, "timestamp": 2000})
    summary, other, ratios = metrics.reports()
    first, total = summary[0], summary[-1]
    assert (first["公共库"], first["部门库"], first["个人库"], first["贡献数"]) == (1, 1, 1, 1)
    assert first["贡献比"] == "50.00%"  # 外部人员上传到部门库的文档也在分母中。
    assert first["访问比"] == "66.67%"
    assert first["问答比"] == "66.67%"
    assert (total["贡献数"], total["贡献比"], total["访问比"], total["问答比"]) == (3, "75.00%", "83.33%", "80.00%")
    assert len(summary) == 11 and len(other) == 2
    assert sum(row["登录次数"] for row in other) == 2
    assert any(row["分子"] == 5 and row["分母"] == 6 for row in ratios)
    assert summary[1]["科室库"] == 1 and summary[1]["团队库"] == 0


def test_invalid_organization_or_identity_does_not_silently_count():
    scope = scope_fixture()
    with pytest.raises(ValueError, match="主组织"):
        OrganizationScope(
            list(scope.departments.values()),
            [{"user_id": 101, "department_id": 10}, {"user_id": 101, "department_id": 11}],
            1,
            2,
        )
    metrics = Metrics(scope)
    metrics.login({"event_id": "a", "user_id": 101, "timestamp": 1000})
    with pytest.raises(ValueError, match="冲突"):
        metrics.login({"event_id": "a", "user_id": 102, "timestamp": 1000})
    assert Metrics(scope).reports()[0][0]["访问比"] == ""


class FakeEs:
    """只实现读取协议；错误调用写 API 会直接失败。"""

    def __init__(self, records, fault=None):
        self.records, self.fault = records, fault
        self.indices = SimpleNamespace(exists=lambda index: index in self.records)
        self.pits, self.closed, self.requests = {}, [], []
        self.transport = SimpleNamespace(node_pool=SimpleNamespace(all=lambda: []))
        self.connection_closed = False

    def open_point_in_time(self, index, keep_alive):
        key = f"pit-{index}"
        self.pits[key] = index
        return {"id": key, "_shards": {"failed": 0}}

    def search(self, **kwargs):
        self.requests.append(kwargs)
        assert kwargs["allow_partial_search_results"] is False
        assert kwargs["query"]["bool"]["filter"][0] == {"term": {"tenant_id": "1"}}
        index = self.pits[kwargs["pit"]["id"]]
        start = (kwargs["search_after"] or [0])[0]
        records = self.records[index]
        page = [
            {"_source": row, "sort": [i + 1]} for i, row in enumerate(records) if start <= i < start + kwargs["size"]
        ]
        pit = f"{index}-{len(self.requests)}"
        self.pits[pit] = index
        response = {
            "pit_id": pit,
            "_shards": {"failed": 0},
            "hits": {"total": {"value": len(records), "relation": "eq"}, "hits": page},
        }
        if self.fault:
            self.fault(response, len(self.requests))
        return response

    def close_point_in_time(self, id):
        self.closed.append(id)

    def close(self):
        self.connection_closed = True


STAMP = 1700000000


def sources():
    from datetime import datetime

    login = {
        "tenant_id": 1,
        "timestamp": STAMP,
        "event_type": "user_login",
        "event_id": "L1",
        "user_context": {"user_id": 101},
    }
    question = {
        "tenant_id": 1,
        "timestamp": STAMP,
        "event_type": "portal_qa",
        "event_id": "Q1",
        "user_context": {"user_id": 101},
        "event_data": {"portal_qa_scene": "smart_qa", "portal_qa_status": "success", "portal_qa_question_id": "S1"},
    }
    raw = FakeEs({RAW_INDEX: [login, login.copy(), {**login, "event_id": "L2"}, question, question.copy()]})
    day = datetime.fromtimestamp(STAMP, CHINA).date().isoformat()
    dashboard = FakeEs(
        {
            LOGIN_INDEX: [
                {
                    "tenant_id": 1,
                    "timestamp": STAMP,
                    "metric_source": "participation",
                    "local_date": day,
                    "user_id": 101,
                    "login_count": 2,
                    "logged_in": True,
                }
            ],
            QA_INDEX: [
                {"tenant_id": 1, "timestamp": STAMP, "qa_type": "smart", "question_id": "S1", "user_id": 101},
                {"tenant_id": 1, "timestamp": STAMP, "qa_type": "expert", "question_id": "1", "user_id": 102},
            ],
        }
    )
    return raw, dashboard


def fake_repository():
    scope = scope_fixture()
    return SimpleNamespace(
        departments=lambda: list(scope.departments.values()),
        memberships=lambda: list(scope.members.values()),
        inventory=lambda: iter(
            [
                {
                    "file_id": 1,
                    "document_id": 50,
                    "file_name": "=HYPERLINK(test)",
                    "user_id": 101,
                    "level": "personal",
                    "space_id": 1,
                    "owner_id": 101,
                    "owner_type": "user",
                }
            ]
        ),
        expert_questions=lambda: iter([{"question_id": 1, "user_id": 102, "timestamp": STAMP}]),
    )


def arguments(path):
    return SimpleNamespace(
        tenant_id=1,
        company_department_id=1,
        manufacturing_department_id=2,
        office_map=None,
        raw_index=RAW_INDEX,
        output_dir=path,
    )


def test_readers_to_csv_report_reconciles_and_preserves_values(tmp_path):
    args = arguments(tmp_path / "report")
    raw, dashboard = sources()
    with ExitStack() as stack:
        report = CsvReport(args.output_dir, stack)
        write_rules(report, args)
        metrics = collect_database(fake_repository(), args, report)
        readers = [EsReader(client, 1, report.diagnose, lambda text: None, page_size=2) for client in (raw, dashboard)]
        collect_events(metrics, *readers, report)
        report.finish(metrics)
    with (args.output_dir / "科室指标汇总.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 11
    assert rows[0]["登录次数"] == "2" and rows[0]["智能问答数"] == "1"
    assert rows[1]["专家问答数"] == "1"
    assert rows[0]["贡献比"] == "" and "分母为 0" in rows[0]["备注"]
    assert len(list(args.output_dir.glob("*.csv"))) == 8
    assert "'=HYPERLINK(test)" in (args.output_dir / "知识核对明细.csv").read_text(encoding="utf-8-sig")
    assert raw.closed[-1] == f"{RAW_INDEX}-{len(raw.requests)}"
    assert len(raw.requests) == 4  # 三页数据加一次空页完整性验证。
    assert (
        main(
            [
                "--tenant-id",
                "1",
                "--company-department-id",
                "1",
                "--manufacturing-department-id",
                "2",
                "--output-dir",
                str(args.output_dir),
            ]
        )
        == 2
    )
    assert (args.output_dir / "科室指标汇总.csv").exists()


@pytest.mark.parametrize("fault", ["timeout", "shards", "total", "early_end", "cursor", "tenant"])
def test_incomplete_es_fails_and_closes_pit(fault):
    rows = [{"tenant_id": 1, "timestamp": STAMP, "user_id": i} for i in range(3)]

    def mutate(response, page):
        if fault == "timeout":
            response["timed_out"] = True
        elif fault == "shards":
            response["_shards"]["failed"] = 1
        elif fault == "total":
            response["hits"]["total"]["relation"] = "gte"
        elif fault == "early_end" and page == 2:
            response["hits"]["hits"] = []
        elif fault == "cursor" and page == 2:
            response["hits"]["hits"][-1]["sort"] = [2]
        elif fault == "tenant":
            response["hits"]["hits"][0]["_source"]["tenant_id"] = 2

    client = FakeEs({"index": rows}, fault=mutate)
    with pytest.raises(ValueError):
        list(EsReader(client, 1, lambda *args: None, lambda text: None, page_size=2).scan("index", [], []))
    assert client.closed


@pytest.mark.parametrize("gap", ["login", "question", "missing_index", "missing_question_id"])
def test_history_gap_never_publishes_zero_report(tmp_path, gap):
    args = arguments(tmp_path / gap)
    raw, dashboard = sources()
    if gap == "login":
        dashboard.records[LOGIN_INDEX][0]["login_count"] = 8
    elif gap == "question":
        dashboard.records[QA_INDEX].append(
            {"tenant_id": 1, "timestamp": STAMP, "qa_type": "document", "question_id": "old", "user_id": 101}
        )
    elif gap == "missing_index":
        dashboard.records.pop(LOGIN_INDEX)
    else:
        raw.records[RAW_INDEX][-1]["event_data"]["portal_qa_question_id"] = None
    with ExitStack() as stack:
        report = CsvReport(args.output_dir, stack)
        metrics = collect_database(fake_repository(), args, report)
        with pytest.raises(ValueError):
            collect_events(
                metrics, *(EsReader(c, 1, report.diagnose, lambda text: None) for c in (raw, dashboard)), report
            )
    assert not (args.output_dir / "科室指标汇总.csv").exists()
    assert (args.output_dir / "来源诊断.csv").exists()


def test_cli_success_and_sanitized_failure(tmp_path, monkeypatch, capsys):
    from contextlib import nullcontext

    from bisheng.core import database
    from scripts import export_office_metrics as cli

    raw, dashboard = sources()
    session = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(database, "get_sync_db_session", lambda: nullcontext(session))
    monkeypatch.setattr(cli, "OfficeRepository", lambda session: fake_repository())
    monkeypatch.setattr(cli, "create_clients", lambda settings: (raw, dashboard))
    args = ["--tenant-id", "1", "--company-department-id", "1", "--manufacturing-department-id", "2", "--output-dir"]
    output = tmp_path / "cli-success"
    assert main([*args, str(output)]) == 0
    assert (output / "科室指标汇总.csv").exists()
    assert raw.connection_closed and dashboard.connection_closed

    def fail(_):
        raise ValueError("connection contains SECRET_TEST_CREDENTIAL")

    monkeypatch.setattr(cli, "OfficeRepository", fail)
    failed = tmp_path / "cli-failed"
    assert main([*args, str(failed)]) == 1
    captured = capsys.readouterr()
    assert "SECRET_TEST_CREDENTIAL" not in captured.out + captured.err
    assert "SECRET_TEST_CREDENTIAL" not in (failed / "来源诊断.csv").read_text(encoding="utf-8-sig")
    assert not (failed / "科室指标汇总.csv").exists()


def test_organization_mapping_conflicts_and_unknown_people_are_visible():
    scope = scope_fixture()
    departments = list(scope.departments.values())
    members = list(scope.members.values())
    departments.append({"id": 40, "parent_id": 2, "path": "/1/2/40/", "name": OFFICES[0], "org_level": "office"})
    with pytest.raises(ValueError, match="唯一匹配"):
        OrganizationScope(departments, members, 1, 2)
    explicit = OrganizationScope(departments, members, 1, 2, {OFFICES[0]: 10})
    assert explicit.locate(101)["group"] == "10"
    with pytest.raises(ValueError, match="重叠"):
        OrganizationScope(departments, members, 1, 2, {OFFICES[0]: 10, OFFICES[1]: 30})
    diagnostics = []
    metrics = Metrics(explicit, lambda *args: diagnostics.append(args))
    detail = metrics.login({"user_id": 999, "event_id": "unknown", "timestamp": STAMP})
    assert detail["company"] == 0 and detail["reason"] == "无当前主组织"
    assert diagnostics and metrics.has_warnings
    explicit.members[101]["tenant_member"] = False
    metrics.login({"user_id": 101, "event_id": "old-member", "timestamp": STAMP})
    assert metrics.reports()[0][0]["登录次数"] == 1
    assert any("缺少租户成员关系" in item[-1] for item in diagnostics)


def test_document_events_follow_actual_serialization_and_ignore_failed_questions(tmp_path):
    from bisheng.common.schemas.telemetry.base_telemetry_schema import BaseTelemetryEvent, UserContext
    from bisheng.common.schemas.telemetry.event_data_schema import PortalQaEventData

    records = []
    for qid in ("d1", "d2"):
        record = BaseTelemetryEvent(
            tenant_id=1,
            event_id=qid,
            event_type="portal_qa",
            timestamp=STAMP,
            user_context=UserContext(user_id=101, user_name="甲"),
            event_data=PortalQaEventData(
                source_app="bisheng_my_knowledge",
                scene="my_knowledge_document_qa",
                entry_point="my_knowledge_document_qa",
                question_id=qid,
                conversation_id="same-session",
            ),
        ).model_dump()
        records.append(record)
    failed = {
        **records[0],
        "event_data": {**records[0]["event_data"], "portal_qa_status": "failed", "portal_qa_question_id": "failed"},
    }
    raw = FakeEs({RAW_INDEX: [*records, failed]})
    dashboard = FakeEs(
        {
            LOGIN_INDEX: [],
            QA_INDEX: [
                {"tenant_id": 1, "timestamp": STAMP, "qa_type": "document", "question_id": qid, "user_id": 101}
                for qid in ("d1", "d2")
            ],
        }
    )
    with ExitStack() as stack:
        report = CsvReport(tmp_path / "actual-contract", stack)
        metrics = Metrics(scope_fixture(), report.diagnose)
        collect_events(metrics, *(EsReader(c, 1, report.diagnose, lambda text: None) for c in (raw, dashboard)), report)
        assert metrics.reports()[0][0]["文档问答"] == 2
        assert report.warnings == 1


def test_other_company_activity_is_excluded_but_its_department_library_contribution_remains(tmp_path):
    scope = scope_fixture()
    departments = [
        *scope.departments.values(),
        {"id": 40, "parent_id": None, "path": "/40/", "name": "另一公司", "org_level": "dept"},
    ]
    members = [*scope.members.values(), {"user_id": 999, "department_id": 40, "user_name": "外部人员"}]
    repo = fake_repository()
    repo.departments = lambda: departments
    repo.memberships = lambda: members
    files = list(repo.inventory())
    files.extend(
        [
            {
                "file_id": 2,
                "document_id": 99,
                "user_id": 999,
                "level": "public",
                "space_id": 2,
                "owner_id": 40,
                "owner_type": "department",
            },
            {
                "file_id": 3,
                "document_id": 100,
                "user_id": 999,
                "level": "department",
                "space_id": 3,
                "owner_id": 2,
                "owner_type": "department",
            },
        ]
    )
    repo.inventory = lambda: iter(files)
    raw, dashboard = sources()
    raw.records[RAW_INDEX].append(
        {
            "tenant_id": 1,
            "timestamp": STAMP,
            "event_type": "portal_qa",
            "user_context": {"user_id": 999},
            "event_data": {},
        }
    )
    dashboard.records[QA_INDEX].append(
        {"tenant_id": 1, "timestamp": STAMP, "qa_type": "expert", "question_id": "out-of-scope", "user_id": 999}
    )
    args = arguments(tmp_path / "company-boundary")
    with ExitStack() as stack:
        report = CsvReport(args.output_dir, stack)
        metrics = collect_database(repo, args, report)
        collect_events(metrics, *(EsReader(c, 1, report.diagnose, lambda text: None) for c in (raw, dashboard)), report)
        report.finish(metrics)
    with (args.output_dir / "知识核对明细.csv").open(encoding="utf-8-sig") as file:
        assert {r["文件ID"] for r in csv.DictReader(file)} == {"1", "3"}
    with (args.output_dir / "问答核对明细.csv").open(encoding="utf-8-sig") as file:
        assert "999" not in {r["用户ID"] for r in csv.DictReader(file)}
    assert metrics.reports()[0][0]["贡献比"] == "0.00%"


def test_database_inventory_memberships_and_experts_use_real_tenant_queries(monkeypatch):
    from datetime import datetime

    from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, event
    from sqlalchemy.orm import registry
    from sqlmodel import Session

    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
    from bisheng.core.database import tenant_filter

    repo = OfficeRepository(None)

    # 全局夹具模拟了 User；仅替换这两个只读列，业务查询和租户钩子仍用真实实现。
    class UserColumns:
        __tablename__ = "user"

    user_table = Table("user", MetaData(), Column("user_id", Integer, primary_key=True), Column("user_name", String))
    registry().map_imperatively(UserColumns, user_table)
    repo.User = UserColumns
    engine, metadata = create_engine("sqlite://"), MetaData()
    specs = {
        repo.Department: "id tenant_id name path parent_id org_level",
        repo.Membership: "id user_id department_id is_primary",
        repo.User: "user_id user_name",
        repo.UserTenant: "id user_id tenant_id",
        repo.Space: "id tenant_id type state is_favorite",
        repo.Scope: "id tenant_id space_id level owner_type owner_id",
        repo.File: "id tenant_id knowledge_id user_id file_name file_type status reference_document_id entry_type entry_status deleted_at",
        repo.Version: "id document_id knowledge_file_id is_primary",
        repo.Question: "id tenant_id user_id created_at",
    }
    strings = {
        "name",
        "path",
        "org_level",
        "user_name",
        "level",
        "owner_type",
        "file_name",
        "entry_type",
        "entry_status",
        "deleted_at",
    }
    tables = {
        model: Table(
            model.__tablename__,
            metadata,
            *[
                Column(name, DateTime if name == "created_at" else String if name in strings else Integer)
                for name in fields.split()
            ],
        )
        for model, fields in specs.items()
    }
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            tables[repo.Department].insert(),
            [
                {"id": 1, "tenant_id": 1, "name": "本组织", "path": "/1/", "parent_id": None, "org_level": "dept"},
                {"id": 2, "tenant_id": 2, "name": "跨租户组织", "path": "/2/", "parent_id": None, "org_level": "dept"},
            ],
        )
        conn.execute(
            tables[repo.Membership].insert(),
            [
                {"id": 1, "user_id": 100, "department_id": 1, "is_primary": 1},
                {"id": 2, "user_id": 200, "department_id": 2, "is_primary": 1},
                {"id": 3, "user_id": 200, "department_id": 1, "is_primary": 0},
                {"id": 4, "user_id": 300, "department_id": 1, "is_primary": 1},
            ],
        )
        conn.execute(
            tables[repo.User].insert(), [{"user_id": 100, "user_name": "甲"}, {"user_id": 200, "user_name": "乙"}]
        )
        conn.execute(
            tables[repo.UserTenant].insert(),
            [{"id": 1, "user_id": 100, "tenant_id": 1}, {"id": 2, "user_id": 200, "tenant_id": 2}],
        )
        for sid, level, tenant in [(1, "personal", 1), (2, "team_ks", 1), (3, "public", 2)]:
            conn.execute(
                tables[repo.Space].insert(), {"id": sid, "tenant_id": tenant, "type": 3, "state": 1, "is_favorite": 0}
            )
            conn.execute(
                tables[repo.Scope].insert(),
                {
                    "id": sid,
                    "tenant_id": tenant,
                    "space_id": sid,
                    "level": level,
                    "owner_type": "department",
                    "owner_id": 1,
                },
            )
        conn.execute(
            tables[repo.Space].insert(),
            [
                {"id": 4, "tenant_id": 1, "type": 3, "state": 1, "is_favorite": 1},
                {"id": 5, "tenant_id": 1, "type": 3, "state": 5, "is_favorite": 0},
            ],
        )
        conn.execute(
            tables[repo.Scope].insert(),
            [
                {"id": i, "tenant_id": 1, "space_id": i, "level": "personal", "owner_type": "user", "owner_id": 100}
                for i in (4, 5)
            ],
        )
        files = [
            {
                "id": i,
                "tenant_id": 1,
                "knowledge_id": 1,
                "user_id": 100,
                "file_name": str(i),
                "file_type": 1,
                "status": 2,
                "reference_document_id": None,
                "entry_type": None,
                "entry_status": None,
                "deleted_at": None,
            }
            for i in range(1, 11)
        ]
        files[1].update(knowledge_id=2, reference_document_id=50, entry_type="publish", entry_status="active")
        files[2].update(knowledge_id=3, tenant_id=2)
        files[3].update(deleted_at="2026-09-01")
        files[4].update(status=3)
        files[5].update(knowledge_id=4)
        files[6].update(knowledge_id=5)
        files[7].update(reference_document_id=50, entry_type="share", entry_status="preparing")
        files[9].update(file_type=0)
        conn.execute(tables[repo.File].insert(), files)
        conn.execute(
            tables[repo.Version].insert(),
            [
                {"id": 1, "document_id": 50, "knowledge_file_id": 1, "is_primary": 1},
                {"id": 2, "document_id": 50, "knowledge_file_id": 9, "is_primary": 0},
            ],
        )
        conn.execute(
            tables[repo.Question].insert(),
            [
                {"id": 1, "tenant_id": 1, "user_id": 100, "created_at": datetime(2026, 9, 29)},
                {"id": 2, "tenant_id": 2, "user_id": 200, "created_at": datetime(2026, 9, 29)},
            ],
        )
    tenant_filter.register_tenant_filter_events()
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._discover_tenant_aware_tables())
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt))
    token = set_current_tenant_id(1)
    try:
        with strict_tenant_filter(), Session(engine) as session:
            repo.session = session
            assert [d["id"] for d in repo.departments()] == [1]
            memberships = repo.memberships()
            assert [m["user_id"] for m in memberships] == [100, 300]
            assert [m["tenant_member"] for m in memberships] == [True, False]
            inventory = list(repo.inventory())
            assert {r["file_id"] for r in inventory} == {1, 2}
            assert {r["document_id"] for r in inventory} == {50}
            assert {r["level"] for r in inventory} == {"personal", "team_ks"}
            assert [q["question_id"] for q in repo.expert_questions()] == [1]
    finally:
        current_tenant_id.reset(token)
        engine.dispose()
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
