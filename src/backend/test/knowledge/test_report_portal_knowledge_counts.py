"""门户库存报表的分组、数据库筛选及交付契约验证."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.schema import CreateColumn

from bisheng.common.models.config import Config
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.database.models.department import Department
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from scripts.report_portal_knowledge_counts import (
    Candidate,
    Issues,
    ReportBuilder,
    SpaceInfo,
    attach_dimension_names,
    classify_space,
    generate_report,
    load_dimension_names,
    parse_args,
    validate_report,
    write_report,
)

STARTED = "2026-09-16T12:00:00+08:00"


def _builder() -> ReportBuilder:
    return ReportBuilder(
        {
            1: SpaceInfo(1, "公共库一", "public", True, True),
            2: SpaceInfo(2, "部门库一", "department", False, False),
            3: SpaceInfo(3, "个人一", "personal", False, False),
            4: SpaceInfo(4, "个人二", "personal", False, False),
            5: SpaceInfo(5, "空团队库", "team", False, False),
            6: SpaceInfo(6, "空科室库", "clinic", True, True),
        },
        Issues(),
    )


def _add(
    builder: ReportBuilder,
    file_id: int,
    space_id: int,
    document_id: int,
    category: str | None = "POL",
    domain: str | None = "PP",
) -> None:
    builder.add(Candidate(file_id, space_id, ("document", document_id), category, domain))


def test_grouping_duplicates_personal_merge_and_independent_dimensions(tmp_path: Path) -> None:
    builder = _builder()
    _add(builder, 1, 1, 100)
    _add(builder, 2, 1, 100)
    _add(builder, 3, 2, 100)
    _add(builder, 4, 3, 200, "STD", "QM")
    _add(builder, 5, 4, 200, "STD", "QM")
    _add(builder, 6, 4, 300, None, None)
    report = builder.build(1, STARTED)
    groups = {group["group"]: group for group in report["groups"]}
    assert list(groups) == ["public", "department", "team", "clinic", "personal"]
    assert report["summary"]["counts"]["summed_count"] == 5
    assert report["summary"]["counts"]["distinct_count"] == 3
    assert groups["personal"]["space_count"] == 2
    assert groups["personal"]["spaces"] == []
    assert groups["personal"]["counts"]["summed_count"] == 3
    assert groups["personal"]["counts"]["distinct_count"] == 2
    assert groups["team"]["spaces"][0]["counts"]["distinct_count"] == 0
    assert groups["public"]["spaces"][0]["portal_discovery_only"] is True
    assert groups["department"]["spaces"][0]["portal_discovery_only"] is False
    assert report["summary"]["counts"]["by_category"] == [
        {"kind": "unclassified", "code": None, "summed_count": 1, "distinct_count": 1},
        {"kind": "value", "code": "POL", "summed_count": 2, "distinct_count": 1},
        {"kind": "value", "code": "STD", "summed_count": 2, "distinct_count": 1},
    ]
    assert {b["code"] for b in report["summary"]["counts"]["by_business_domain"]} == {None, "PP", "QM"}
    target = tmp_path / "统计.json"
    write_report(report, target)
    assert json.loads(target.read_text()) == report
    with pytest.raises(FileExistsError):
        write_report(report, target)
    assert list(tmp_path.iterdir()) == [target]
    report["summary"]["counts"]["by_category"][0]["summed_count"] += 1
    with pytest.raises(ValueError, match="by_category"):
        validate_report(report)


def test_conflicting_dimensions_and_legacy_identity_do_not_lose_counts() -> None:
    builder = _builder()
    _add(builder, 1, 1, 100, "POL", "PP")
    _add(builder, 2, 2, 100, "STD", "PP")
    builder.add(Candidate(100, 1, ("file", 100), None, None))
    report = builder.build(1, STARTED)
    counts = report["summary"]["counts"]
    assert (counts["summed_count"], counts["distinct_count"]) == (3, 2)
    assert counts["by_category"][0] == {
        "kind": "conflict",
        "code": None,
        "summed_count": 2,
        "distinct_count": 1,
        "document_samples": [{"kind": "document", "id": 100}],
    }
    assert not any(bucket["kind"] == "conflict" for bucket in counts["by_business_domain"])
    assert report["groups"][0]["counts"]["by_category"][-1]["code"] == "POL"


async def test_dimension_names_use_tenant_configuration_and_cover_every_group(async_db_session) -> None:
    async_db_session.add_all(
        [
            Config(
                key="initdb_config",
                value=json.dumps(
                    {
                        "shougang": {
                            "file_encoding": {
                                "document_types": [
                                    {"code": "POL", "label": "系统政策"},
                                    {"code": "CUSTOM", "label": "系统自定义分类"},
                                ]
                            }
                        }
                    }
                ),
            ),
            Config(
                key="shougang_portal_config",
                value=json.dumps(
                    {
                        "portal": {
                            "document_types": [{"code": "POL", "label": "根租户名称"}],
                            "domains": [{"code": "PP", "name": "根租户业务域"}],
                        }
                    }
                ),
            ),
            Config(
                key="shougang_portal_config:t:2",
                value=json.dumps(
                    {
                        "portal": {
                            "document_types": [{"code": " pol ", "label": "租户政策制度"}],
                            "category_cards": [
                                {"code": "POL", "name": "卡片名称"},
                                {"code": "NEW", "name": "行业情报"},
                            ],
                            "domains": [{"code": " pp ", "name": "租户生产", "enabled": False}],
                        }
                    }
                ),
            ),
        ]
    )
    await async_db_session.commit()
    names = await load_dimension_names(async_db_session, 2)
    assert names["by_category"]["POL"] == "租户政策制度"
    assert names["by_category"]["CUSTOM"] == "系统自定义分类"
    assert names["by_category"]["NEW"] == "行业情报"
    assert names["by_category"]["STD"] == "标准规范"
    assert names["by_business_domain"]["PP"] == "租户生产"
    assert names["by_business_domain"]["QM"] == "质量"

    builder = _builder()
    for index, space_id in enumerate((1, 2, 3, 4)):
        _add(builder, index + 1, space_id, index + 100)
    report = builder.build(2, STARTED)
    original = json.loads(json.dumps(report))
    attach_dimension_names(report, names)
    nodes = [report["summary"]["counts"]]
    for group in report["groups"]:
        nodes.append(group["counts"])
        nodes.extend(space["counts"] for space in group["spaces"])
    for counts in nodes:
        for dimension, expected in (("by_category", "租户政策制度"), ("by_business_domain", "租户生产")):
            for bucket in counts[dimension]:
                assert bucket.pop("name") == expected
    assert report == original


async def test_dimension_name_fallbacks_and_special_buckets(async_db_session) -> None:
    names = await load_dimension_names(async_db_session, 1)
    assert names["by_category"]["POL"] == "政策制度"
    assert names["by_business_domain"]["PP"] == "生产"
    builder = _builder()
    _add(builder, 1, 1, 100, "POL", "PP")
    _add(builder, 2, 2, 100, "STD", "QM")
    _add(builder, 3, 3, 200, None, None)
    _add(builder, 4, 4, 300, "UNKNOWN", "UNKNOWN")
    report = builder.build(1, STARTED)
    attach_dimension_names(report, names)
    counts = report["summary"]["counts"]
    assert [bucket["name"] for bucket in counts["by_category"]] == ["分类冲突", "未分类", "未知分类 (UNKNOWN)"]
    assert [bucket["name"] for bucket in counts["by_business_domain"]] == [
        "业务域冲突",
        "未指定业务域",
        "未知业务域 (UNKNOWN)",
    ]
    validate_report(report)


@pytest.mark.parametrize(
    ("level", "owner_type", "binding_mode", "enabled", "group", "eligible"),
    [
        ("public", "tenant_root_department", "none", True, "public", True),
        ("department", "department", "valid", True, "department", True),
        ("department", "department", "valid", False, "department", False),
        ("department", "department", "deleted", True, "department", False),
        ("department", "department", "foreign", True, "department", False),
        ("department", "department", "mismatch", True, "department", False),
        ("team_ks", "user", "valid", True, "clinic", True),
        ("team", "user", "valid", True, "clinic", True),
        ("team_ks", "user", "none", True, "clinic", False),
        ("team", "user_group", "none", True, "team", False),
        ("personal", "user", "none", True, "personal", False),
        ("unknown", "user", "none", True, "unassigned", False),
    ],
)
def test_space_classification_and_effective_discovery(level, owner_type, binding_mode, enabled, group, eligible):
    space = SimpleNamespace(id=1, name="知识库", tenant_id=1)
    scope = SimpleNamespace(level=level, owner_type=owner_type, owner_id=10, portal_discovery_enabled=enabled)
    bindings = (
        []
        if binding_mode == "none"
        else [
            SimpleNamespace(
                space_id=1,
                department_id=11 if binding_mode == "mismatch" else 10,
                tenant_id=1,
            )
        ]
    )
    departments = {
        key: SimpleNamespace(
            id=key,
            tenant_id=2 if binding_mode == "foreign" else 1,
            status="active",
            is_deleted=int(binding_mode == "deleted"),
        )
        for key in (10, 11)
    }
    result = classify_space(space, scope, bindings, departments)
    assert result.group == group
    assert result.portal_discovery_only is eligible
    assert result.portal_discovery_enabled is enabled


def _space(space_id: int, tenant_id: int = 1, **values) -> Knowledge:
    return Knowledge(id=space_id, tenant_id=tenant_id, user_id=1, name=f"库{space_id}", type=3, **values)


def _file(file_id: int, space_id: int = 1, tenant_id: int = 1, **values) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        knowledge_id=space_id,
        tenant_id=tenant_id,
        user_id=1,
        file_name="同名.pdf",
        **{"status": 2, "file_type": 1, **values},
    )


async def test_database_report_filters_versions_keeps_distributions_and_is_tenant_isolated(
    async_db_session,
    async_db_engine,
) -> None:
    # 共享 fixture 的旧表缺少部分新字段, 仅在本测试的临时 SQLite 内补齐.
    def prepare_tables(connection):
        DepartmentKnowledgeSpace.__table__.create(connection, checkfirst=True)
        for model in (Department, KnowledgeSpaceScope):
            names = {column["name"] for column in inspect(connection).get_columns(model.__tablename__)}
            for column in model.__table__.columns:
                if column.name not in names:
                    ddl = str(CreateColumn(column).compile(dialect=connection.dialect))
                    connection.execute(text(f"ALTER TABLE {model.__tablename__} ADD COLUMN {ddl}"))

    async with async_db_engine.begin() as connection:
        await connection.run_sync(prepare_tables)
    register_tenant_filter_events()
    async_db_session.add_all(
        [
            _space(1),
            _space(2),
            _space(3),
            _space(4, is_favorite=True),
            _space(5, state=5),
            _space(6),
            _space(9, 2),
            KnowledgeSpaceScope(
                space_id=1,
                tenant_id=1,
                level="public",
                owner_type="tenant_root_department",
                owner_id=1,
                portal_discovery_enabled=True,
            ),
            KnowledgeSpaceScope(
                space_id=2,
                tenant_id=1,
                level="department",
                owner_type="department",
                owner_id=10,
                portal_discovery_enabled=True,
            ),
            KnowledgeSpaceScope(space_id=3, tenant_id=1, level="personal", owner_type="user", owner_id=1),
            KnowledgeSpaceScope(space_id=4, tenant_id=1, level="personal", owner_type="user", owner_id=2),
            KnowledgeSpaceScope(
                space_id=9, tenant_id=2, level="public", owner_type="tenant_root_department", owner_id=1
            ),
            Department(id=10, tenant_id=1, dept_id="dept10", name="部门", status="active"),
            DepartmentKnowledgeSpace(space_id=2, department_id=10, tenant_id=1),
            KnowledgeDocument(id=100, tenant_id=1, knowledge_id=1, primary_version_id=1000),
            KnowledgeDocument(id=101, tenant_id=1, knowledge_id=1, lifecycle_status="invalid"),
            KnowledgeDocument(id=102, tenant_id=1, knowledge_id=1, primary_version_id=1020),
            KnowledgeDocument(id=999, tenant_id=2, knowledge_id=9),
            KnowledgeDocumentVersion(id=1000, document_id=100, knowledge_file_id=10, version_no=2, is_primary=True),
            KnowledgeDocumentVersion(id=1001, document_id=100, knowledge_file_id=11, version_no=1, is_primary=False),
            KnowledgeDocumentVersion(id=1020, document_id=102, knowledge_file_id=12, version_no=1, is_primary=True),
            _file(1, file_encoding="GF-POL-PP-2026090001"),
            _file(2, status=3),
            _file(3, status=1),
            _file(4, deleted_at=datetime(2026, 9, 1)),
            _file(5, file_type=0),
            _file(6, entry_status="invalid"),
            _file(7, entry_type="projection_tombstone"),
            _file(8, 5),
            _file(9, reference_document_id=999, entry_type="publish", entry_status="active"),
            _file(10, reference_document_id=100, entry_type="manager", entry_status="active"),
            _file(11),
            _file(12, reference_document_id=100, entry_type="manager", entry_status="active"),
            _file(13, 2, reference_document_id=100, entry_type="publish", entry_status="active"),
            _file(14, 3, reference_document_id=100, entry_type="share", entry_status="active"),
            _file(15, 4, reference_document_id=100, entry_type="share", entry_status="active"),
            _file(16, reference_document_id=101, entry_type="share", entry_status="active"),
            _file(
                17,
                6,
                split_rule=json.dumps({"file_category_code": "STD", "business_domain_code": "QM"}),
                file_encoding="GF-POL-PP-2026090002",
            ),
            _file(18, 9, tenant_id=2),
            _file(19, reference_document_id=100, entry_type="share", entry_status="invalid"),
        ]
    )
    await async_db_session.commit()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(async_db_engine.sync_engine, "before_cursor_execute", capture)
    tenant_token = set_current_tenant_id(1)
    try:
        with strict_tenant_filter():
            report = await generate_report(async_db_session, 1, page_size=2)
    finally:
        current_tenant_id.reset(tenant_token)
        event.remove(async_db_engine.sync_engine, "before_cursor_execute", capture)
    assert set(statements) == {"SELECT"}
    assert report["summary"]["space_count"] == 5
    assert report["summary"]["counts"]["summed_count"] == 6
    assert report["summary"]["counts"]["distinct_count"] == 3
    groups = {group["group"]: group for group in report["groups"]}
    assert groups["personal"]["counts"]["summed_count"] == 2
    assert groups["personal"]["counts"]["distinct_count"] == 1
    assert groups["department"]["spaces"][0]["portal_discovery_only"] is True
    assert groups["unassigned"]["counts"]["by_category"][0]["code"] == "STD"
    assert groups["unassigned"]["counts"]["by_business_domain"][0]["code"] == "QM"
    assert {a["reason"]: a["count"] for a in report["anomalies"]} == {
        "document_reference_mismatch": 1,
        "missing_or_inactive_document": 2,
        "missing_or_unknown_space_scope": 1,
    }


@pytest.mark.parametrize("arguments", [["--page-size", "0"], ["--page-size", "501"], ["--tenant-id", "0"]])
def test_invalid_cli_parameters_fail(arguments):
    with pytest.raises(SystemExit) as error:
        parse_args(arguments)
    assert error.value.code == 2


def test_help_runs_without_loading_configuration_or_connecting(tmp_path: Path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "report_portal_knowledge_counts.py"
    result = subprocess.run(
        [sys.executable, str(script), "--config", "/missing.yaml", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--tenant-id" in result.stdout
    assert "--output" in result.stdout
