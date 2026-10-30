"""纠错表改挂上传人: 只在隔离 SQLite 验证, 不连接环境数据库。"""

from datetime import datetime

import pytest
import sqlalchemy as sa
from openpyxl import Workbook
from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from scripts import reassign_admin_upload_owners as script

STAMP = datetime(2026, 7, 27, 11, 20, 49)


def test_classify_named_users() -> None:
    assert script.classify_named_users([(8, "张若瑜", 0)])[0]["user_id"] == 8
    assert script.classify_named_users([(8, "张若瑜", 0), (9, "张若瑜", 1)])[0]["user_id"] == 8
    assert script.classify_named_users([(8, "张若瑜", 0), (9, "张若瑜", 0)])[1] == "user_name_ambiguous"
    assert script.classify_named_users([(8, "张若瑜", 1)])[1] == "user_resigned"
    assert script.classify_named_users([])[1] == "user_not_found"


def test_sheet_conflict_collapses_identical_rows_and_rejects_disagreement(tmp_path) -> None:
    path = tmp_path / "rows.xlsx"
    _write_sheet(
        path,
        [
            ["document:10", 101, "a.pdf", "张若瑜"],
            ["document:10", 101, "a.pdf", "张若瑜"],
            ["document:11", 102, "b.pdf", "张若瑜"],
            ["document:11", 102, "b.pdf", "冯大伟"],
            ["not-a-document", 103, "c.pdf", "张若瑜"],
        ],
    )

    rows, skipped, notes, data_rows = script.load_sheet(path)

    assert data_rows == 5
    assert [row.excel_row for row in rows] == [2]
    assert notes == [{"type": "duplicate_collapsed", "file_id": 101, "excel_rows": [2, 3]}]
    reasons = {(item["file_id"], item["reason"]) for item in skipped}
    assert reasons == {(102, "sheet_conflict"), (103, "sheet_document_invalid")}
    assert sum(1 for item in skipped if item["file_id"] == 102) == 2


def test_sheet_requires_the_four_columns(tmp_path) -> None:
    path = tmp_path / "bad.xlsx"
    workbook = Workbook()
    workbook.active.append(["文件名"])
    workbook.save(path)

    with pytest.raises(ValueError, match="缺少列"):
        script.load_sheet(path)


def test_preview_cli_does_not_accept_apply() -> None:
    with pytest.raises(SystemExit):
        script.parse_args(["--tenant-id", "1", "--xlsx", "rows.xlsx", "--apply", "--output", "out.jsonl"])
    args = script.parse_args(["--tenant-id", "1", "--output", "out.jsonl"])
    assert args.apply is False
    assert args.plan is None
    assert args.xlsx == script.DEFAULT_XLSX
    assert args.xlsx.name == "纠错2.xlsx"


async def test_preview_updates_only_resolved_rows_and_rollback_restores(async_db_session, tmp_path) -> None:
    session = async_db_session
    await _seed(session)
    workbook = tmp_path / "owners.xlsx"
    _write_sheet(
        workbook,
        [
            ["document:10", 101, "a.pdf", "张若瑜"],
            ["document:10", 101, "a.pdf", "张若瑜"],
            ["document:11", 102, "b.pdf", "冯大伟"],
            ["document:12", 103, "c.pdf", "张若瑜"],
            ["document:13", 104, "missing.pdf", "张若瑜"],
            ["document:14", 105, "d.pdf", "张若瑜"],
            ["document:99", 106, "e.pdf", "张若瑜"],
            ["document:16", 107, "f.pdf", "离职人"],
        ],
    )
    plan = tmp_path / "plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        preview = await script.preview(session, journal, tenant_id=1, xlsx_path=workbook)
    assert preview == {"would_update": 1, "skipped": 6, "siblings": 1}
    assert (await _owner(session, 101))["user_name"] == "管理员"

    applied = tmp_path / "apply.jsonl"
    with script.JsonlJournal(applied) as journal:
        result = await script.apply_plan(session, plan, journal)
    assert result == {"updated": 1, "skipped": 0}
    updated = await _owner(session, 101)
    assert updated["user_id"] == 21
    assert updated["user_name"] == "张若瑜"
    assert updated["belonging_organization_id"] == 81
    assert script.as_datetime(updated["update_time"]) == STAMP
    unchanged = await _owner(session, 102)
    assert unchanged["user_name"] == "管理员"
    assert unchanged["belonging_organization_id"] == 9
    sibling = await _owner(session, 201)
    assert sibling["user_name"] == "管理员"
    assert sibling["belonging_organization_id"] == 9
    preserved = (
        await session.exec(
            select(
                KnowledgeFile.original_uploader_id,
                KnowledgeFile.updater_id,
                KnowledgeFile.updater_name,
            ).where(KnowledgeFile.id == 101)
        )
    ).one()
    assert (preserved.original_uploader_id, preserved.updater_id, preserved.updater_name) == (1, 1, "管理员")
    assert plan.stat().st_mode & 0o777 == 0o600

    unknown = tmp_path / "unknown.jsonl"
    with script.JsonlJournal(unknown) as journal:
        journal.write(
            {
                "type": "header",
                "version": 1,
                "mode": "apply",
                "tenant_id": 1,
                "database_key": script.database_key(session),
            }
        )
        journal.write({"type": "prepared", "files": [{"file_id": 101}]})
        journal.write({"type": "summary", "updated": 1, "skipped": 0})
    with script.JsonlJournal(tmp_path / "unknown-rollback.jsonl") as journal:
        refused = await script.rollback_plan(session, unknown, journal, apply=True)
    assert refused["updated"] == 0
    assert (await _owner(session, 101))["user_name"] == "张若瑜"

    with script.JsonlJournal(tmp_path / "rollback-preview.jsonl") as journal:
        dry = await script.rollback_plan(session, applied, journal, apply=False)
    assert dry["would_update"] == 1
    assert dry["updated"] == 0
    assert (await _owner(session, 101))["user_name"] == "张若瑜"
    with script.JsonlJournal(tmp_path / "rollback.jsonl") as journal:
        restored = await script.rollback_plan(session, applied, journal, apply=True)
    assert restored == {"updated": 1, "skipped": 0, "would_update": 1}
    restored_owner = await _owner(session, 101)
    assert restored_owner["user_id"] == 1
    assert restored_owner["user_name"] == "管理员"
    assert restored_owner["belonging_organization_id"] == 9
    assert script.as_datetime(restored_owner["update_time"]) == STAMP


def _write_sheet(path, rows: list[list]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["备注", "文件名", "上传人ID", "文档唯一标识", "关联文件入口ID"])
    for document_id, file_id, file_name, target_name in rows:
        worksheet.append(["忽略", file_name, target_name, document_id, file_id])
    workbook.save(path)


async def _seed(session) -> None:
    await session.exec(
        sa.text(
            "INSERT INTO department (id, dept_id, name, tenant_id, path, status, is_deleted) "
            "VALUES (81, 'org81', '安全管理室', 1, '', 'active', 0)"
        )
    )
    await session.exec(
        sa.text(
            'INSERT INTO user (user_id, user_name, password, "delete") VALUES '
            "(21, '张若瑜', 'x', 0), (22, '冯大伟', 'x', 0), (23, '离职人', 'x', 1)"
        )
    )
    await session.exec(sa.text("INSERT INTO user_department (user_id, department_id, is_primary) VALUES (21, 81, 1)"))
    session.add_all(
        [
            _file(101, 10, "a.pdf", "管理员", 9),
            _file(102, 11, "b.pdf", "管理员", 9),
            _file(103, 12, "c.pdf", "别人", 9),
            _file(105, 14, "other.pdf", "管理员", 9),
            _file(106, 15, "e.pdf", "管理员", 9),
            _file(107, 16, "f.pdf", "管理员", 9),
            _file(201, 10, "sibling.pdf", "管理员", 9),
        ]
    )
    await session.commit()


def _file(file_id: int, document_id: int, file_name: str, user_name: str, organization_id: int) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=1,
        knowledge_id=1,
        file_name=file_name,
        user_id=1,
        user_name=user_name,
        reference_document_id=document_id,
        belonging_organization_id=organization_id,
        original_uploader_id=1,
        updater_id=1,
        updater_name="管理员",
        update_time=STAMP,
    )


async def _owner(session, file_id: int) -> dict:
    return (await script.files_by_ids(session, [file_id]))[file_id]
