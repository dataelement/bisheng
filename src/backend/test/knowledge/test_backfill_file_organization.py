"""存量组织补空脚本只在隔离SQLite验证, 不连接环境数据库。"""

import json

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.database.models.department import Department, UserDepartment
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from scripts.backfill_knowledge_file_organization import JsonlJournal, apply_plan, preview
from test.knowledge.test_file_belonging_organization import current_organization_schema as current_organization_schema
from test.knowledge.test_file_belonging_organization import seed_publish_organization


async def seed(session):
    await seed_publish_organization(session, "portal_clinic")
    session.add(Knowledge(id=30, tenant_id=7, name="分享接收库", type=3))
    session.add(Department(id=82, dept_id="upload-org", name="上传人主组织", tenant_id=7))
    await session.execute(sa.insert(UserDepartment.__table__).values(user_id=501, department_id=82, is_primary=1))
    historical = await session.get(KnowledgeFile, 99)
    historical.user_id = 601
    historical.original_uploader_id = 601
    session.add(historical)
    primary = await session.get(KnowledgeFile, 100)
    primary.original_uploader_id = 601
    session.add(primary)
    await session.commit()


async def make_plan(session, tmp_path, **kwargs):
    path = tmp_path / "plan.jsonl"
    with JsonlJournal(path) as journal:
        result = await preview(session, journal, tenant_id=7, **kwargs)
    return path, result


async def orgs(session):
    return {
        row.id: row.belonging_organization_id
        for row in (await session.exec(select(KnowledgeFile).execution_options(populate_existing=True))).all()
    }


async def test_preview_apply_repeat_and_rollback(async_db_session, tmp_path):
    session = async_db_session
    await seed(session)
    plan, report = await make_plan(session, tmp_path, space_id=30)
    assert report["would_update"] == 3
    assert set((await orgs(session)).values()) == {None}
    with JsonlJournal(tmp_path / "apply.jsonl") as journal:
        report = await apply_plan(session, plan, journal)
    assert report["updated"] == 3
    assert set((await orgs(session)).values()) == {82}
    assert (await session.get(KnowledgeFile, 100)).original_uploader_id == 601
    preview_records = [json.loads(line) for line in plan.read_text().splitlines()]
    write_records = [json.loads(line) for line in (tmp_path / "apply.jsonl").read_text().splitlines()]
    before = next(row for row in preview_records if row["type"] == "candidate")["rows"]
    after = next(row for row in write_records if row["type"] == "committed")["after"]
    assert [row["update_time"] for row in before] == [row["update_time"] for row in after]
    with JsonlJournal(tmp_path / "repeat.jsonl") as journal:
        repeat = await apply_plan(session, plan, journal)
    assert repeat["updated"] == 0
    with JsonlJournal(tmp_path / "rollback-preview.jsonl") as journal:
        dry = await apply_plan(session, tmp_path / "apply.jsonl", journal, rollback=True, apply=False)
    assert dry["would_update"] == 3
    assert set((await orgs(session)).values()) == {82}
    with JsonlJournal(tmp_path / "rollback.jsonl") as journal:
        restored = await apply_plan(session, tmp_path / "apply.jsonl", journal, rollback=True)
    assert restored["updated"] == 3
    assert set((await orgs(session)).values()) == {None}
    assert (tmp_path / "apply.jsonl").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("case", ["missing_primary_org", "multiple_primary_org", "existing_conflict", "broken_version"])
async def test_uncertain_groups_are_reported_without_changes(async_db_session, tmp_path, case):
    session = async_db_session
    await seed(session)
    if case == "missing_primary_org":
        await session.execute(sa.delete(UserDepartment.__table__).where(UserDepartment.user_id == 501))
    elif case == "multiple_primary_org":
        await session.execute(sa.insert(UserDepartment.__table__).values(user_id=501, department_id=81, is_primary=1))
    elif case == "existing_conflict":
        row = await session.get(KnowledgeFile, 102)
        row.belonging_organization_id = 81
        session.add(row)
    else:
        await session.delete(await session.get(KnowledgeFile, 99))
    await session.commit()
    before = await orgs(session)
    _, report = await make_plan(session, tmp_path)
    assert report["would_update"] == 0
    assert report["skipped"] > 0
    assert await orgs(session) == before


async def test_plan_drift_and_rollback_drift_do_not_overwrite(async_db_session, tmp_path):
    session = async_db_session
    await seed(session)
    plan, _ = await make_plan(session, tmp_path)
    primary = await session.get(KnowledgeFile, 100)
    primary.user_id = 601
    session.add(primary)
    await session.commit()
    with JsonlJournal(tmp_path / "drift.jsonl") as journal:
        result = await apply_plan(session, plan, journal)
    assert result["updated"] == 0 and result["skipped"] == 1
    primary.user_id = 501
    session.add(primary)
    await session.commit()
    new_plan = tmp_path / "new-plan.jsonl"
    with JsonlJournal(new_plan) as journal:
        await preview(session, journal, tenant_id=7)
    with JsonlJournal(tmp_path / "apply.jsonl") as journal:
        await apply_plan(session, new_plan, journal)
    primary = await session.get(KnowledgeFile, 100)
    primary.file_name = "changed.pdf"
    session.add(primary)
    await session.commit()
    with JsonlJournal(tmp_path / "rollback.jsonl") as journal:
        result = await apply_plan(session, tmp_path / "apply.jsonl", journal, rollback=True)
    assert result["updated"] == 0
    assert set((await orgs(session)).values()) == {82}


def test_report_is_exclusive_and_plan_is_jsonl(tmp_path):
    path = tmp_path / "report.jsonl"
    with JsonlJournal(path) as journal:
        journal.write({"type": "sample", "organization_id": None})
    assert json.loads(path.read_text())["organization_id"] is None
    with pytest.raises(FileExistsError):
        JsonlJournal(path)


async def test_commit_failure_rolls_back_and_is_not_blindly_recovered(async_db_session, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    session = async_db_session
    await seed(session)
    plan, _ = await make_plan(session, tmp_path)
    with monkeypatch.context() as scoped:
        scoped.setattr(session, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
        with JsonlJournal(tmp_path / "failed.jsonl") as journal:
            with pytest.raises(RuntimeError, match="commit failed"):
                await apply_plan(session, plan, journal)
    assert set((await orgs(session)).values()) == {None}
    with (tmp_path / "failed.jsonl").open("a") as stream:
        stream.write('{"type":"committed"')
    with JsonlJournal(tmp_path / "recovery.jsonl") as journal:
        result = await apply_plan(session, tmp_path / "failed.jsonl", journal, rollback=True)
    assert result["updated"] == 0 and result["skipped"] == 1
    assert "commit_outcome_unknown" in (tmp_path / "recovery.jsonl").read_text()


async def test_standalone_scope_and_non_business_exclusions(async_db_session, tmp_path):
    session = async_db_session
    await seed(session)
    session.add(Knowledge(id=80, tenant_id=8, name="其他租户库", type=3))
    session.add_all(
        [
            KnowledgeFile(id=150, tenant_id=7, knowledge_id=10, file_name="ordinary.pdf", user_id=601),
            KnowledgeFile(id=151, tenant_id=8, knowledge_id=80, file_name="foreign.pdf", user_id=501),
            KnowledgeFile(id=152, tenant_id=7, knowledge_id=10, file_name="folder", file_type=0, user_id=601),
            KnowledgeFile(id=153, tenant_id=7, knowledge_id=10, file_name="favorite", file_source="favorite_reference"),
            KnowledgeFile(
                id=154, tenant_id=7, knowledge_id=10, file_name="tombstone", entry_type="projection_tombstone"
            ),
        ]
    )
    await session.commit()
    plan, report = await make_plan(session, tmp_path, batch_size=1)
    assert report["would_update"] == 4
    with JsonlJournal(tmp_path / "apply.jsonl") as journal:
        await apply_plan(session, plan, journal)
    result = await orgs(session)
    assert result[150] == 81
    assert all(result[file_id] is None for file_id in (151, 152, 153, 154))


async def test_plan_database_and_organization_tampering_are_rejected(async_db_session, tmp_path):
    session = async_db_session
    await seed(session)
    plan, _ = await make_plan(session, tmp_path)
    records = [json.loads(line) for line in plan.read_text().splitlines()]
    for record in records:
        if record["type"] == "candidate":
            record["organization_id"] = 999
    changed = tmp_path / "changed.jsonl"
    changed.write_text("".join(json.dumps(record) + "\n" for record in records))
    with JsonlJournal(tmp_path / "refused.jsonl") as journal:
        result = await apply_plan(session, changed, journal)
    assert result["updated"] == 0 and result["skipped"] == 1
    records[0]["database_key"] = "other-database"
    changed.write_text("".join(json.dumps(record) + "\n" for record in records))
    with JsonlJournal(tmp_path / "wrong-db.jsonl") as journal:
        with pytest.raises(ValueError, match="数据库身份"):
            await apply_plan(session, changed, journal)
    assert set((await orgs(session)).values()) == {None}


async def test_incomplete_preview_is_rejected_before_any_write(async_db_session, tmp_path):
    session = async_db_session
    await seed(session)
    plan, _ = await make_plan(session, tmp_path)
    lines = plan.read_text().splitlines(keepends=True)
    broken = tmp_path / "incomplete.jsonl"
    broken.write_text("".join(lines[:-1]))
    with JsonlJournal(tmp_path / "refused.jsonl") as journal:
        with pytest.raises(ValueError, match="缺少完整汇总"):
            await apply_plan(session, broken, journal)
    assert set((await orgs(session)).values()) == {None}
