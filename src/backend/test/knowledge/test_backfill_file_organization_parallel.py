"""并发使用独立文件数据库连接, 不以共享内存连接代替事务隔离。"""

import asyncio
import json
import sys

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from scripts import backfill_knowledge_file_organization as script
from test.fixtures.table_definitions import INDEX_DEFINITIONS, TABLE_DEFINITIONS
from test.knowledge.test_backfill_file_organization import seed
from test.knowledge.test_file_belonging_organization import current_organization_schema as current_organization_schema


@pytest.fixture
async def async_db_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'parallel.db'}")
    async with engine.begin() as connection:
        for ddl in TABLE_DEFINITIONS.values():
            await connection.execute(text(ddl))
        for ddl in INDEX_DEFINITIONS:
            await connection.execute(text(ddl))
    yield engine
    await engine.dispose()


def factory(engine):
    return lambda: AsyncSession(engine, expire_on_commit=False)


@pytest.mark.parametrize("apply", [False, True])
async def test_scan_without_saved_plan_supports_preview_apply_repeat_and_rollback(
    async_db_session, async_db_engine, tmp_path, monkeypatch, apply
):
    from bisheng.core import database
    from bisheng.core.context import manager

    async def close_isolated_context():
        return None

    monkeypatch.setattr(database, "get_async_db_session", factory(async_db_engine))
    monkeypatch.setattr(manager, "close_app_context", close_isolated_context)
    await seed(async_db_session)
    async_db_session.add(KnowledgeFile(id=200, tenant_id=7, knowledge_id=10, file_name="ordinary.pdf", user_id=501))
    await async_db_session.commit()
    log = tmp_path / "direct.jsonl"
    options = {"tenant_id": 7, "concurrency": 2, "session_factory": factory(async_db_engine)}
    argv = ["--tenant-id", "7", "--batch-size", "1", "--concurrency", "2", "--output", str(log)]
    if apply:
        argv.append("--apply")
    assert await script.run(script.parser().parse_args(argv)) == 0
    records = list(script.read_records(log))
    result = records[-1]
    assert result["groups"] == 2 and result["would_update"] == 4 and result["skipped"] == 0
    assert result["updated"] == (4 if apply else 0)
    assert records[0]["mode"] == ("apply" if apply else "preview")
    assert len([row for row in records if row["type"] == ("committed" if apply else "candidate")]) == 2
    async with factory(async_db_engine)() as session:
        for file_id in (99, 100, 102, 200):
            assert (await session.get(KnowledgeFile, file_id)).belonging_organization_id == (82 if apply else None)
    if not apply:
        return
    with script.JsonlJournal(tmp_path / "repeat.jsonl") as journal:
        repeat = await script.scan(async_db_session, journal, apply=True, **options)
    assert repeat["updated"] == 0 and repeat["skipped"] == 0
    with script.JsonlJournal(tmp_path / "rollback.jsonl") as journal:
        restored = await script.apply_plan(
            async_db_session, log, journal, rollback=True, concurrency=2, session_factory=factory(async_db_engine)
        )
    assert restored["updated"] == 4
    async with factory(async_db_engine)() as session:
        for file_id in (99, 100, 102, 200):
            assert (await session.get(KnowledgeFile, file_id)).belonging_organization_id is None


async def test_direct_apply_revalidates_before_writing(async_db_session, async_db_engine, tmp_path, monkeypatch):
    await seed(async_db_session)
    original = script.apply_item

    async def drift(session, item, *args, **kwargs):
        async with factory(async_db_engine)() as other:
            primary = await other.get(KnowledgeFile, 100)
            primary.user_id = 601
            other.add(primary)
            await other.commit()
        return await original(session, item, *args, **kwargs)

    monkeypatch.setattr(script, "apply_item", drift)
    with script.JsonlJournal(tmp_path / "drift.jsonl") as journal:
        result = await script.scan(
            async_db_session, journal, tenant_id=7, apply=True, session_factory=factory(async_db_engine)
        )
    assert result["updated"] == 0 and result["skipped"] == 1
    records = list(script.read_records(tmp_path / "drift.jsonl"))
    assert any(row.get("reason") == "plan_state_changed" for row in records)
    async with factory(async_db_engine)() as session:
        for file_id in (99, 100, 102):
            assert (await session.get(KnowledgeFile, file_id)).belonging_organization_id is None


@pytest.mark.parametrize("apply", [False, True])
def test_cli_accepts_scan_without_plan_and_keeps_preview_default(tmp_path, monkeypatch, apply):
    received = []

    async def stub(args):
        received.append(args)
        return 0

    argv = ["backfill", "--tenant-id", "7", "--output", str(tmp_path / "unused.jsonl")]
    if apply:
        argv.append("--apply")
    monkeypatch.setattr(script, "run", stub)
    monkeypatch.setattr(sys, "argv", argv)
    assert script.main() == 0
    assert len(received) == 1 and received[0].apply is apply and received[0].plan is None


def test_cli_direct_apply_requires_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["backfill", "--apply", "--output", str(tmp_path / "unused.jsonl")])
    with pytest.raises(SystemExit) as exc:
        script.main()
    assert exc.value.code == 2 and not (tmp_path / "unused.jsonl").exists()


async def test_preview_deduplicates_before_loading_entire_document(async_db_session, tmp_path, monkeypatch):
    await seed(async_db_session)
    original = script.candidate
    calls = []

    async def counted(*args, **kwargs):
        calls.append(args[1])
        return await original(*args, **kwargs)

    monkeypatch.setattr(script, "candidate", counted)
    with script.JsonlJournal(tmp_path / "plan.jsonl") as journal:
        report = await script.preview(async_db_session, journal, tenant_id=7, batch_size=1)
    assert report["would_update"] == 3
    assert len(calls) == 1


async def test_one_batch_updates_all_rows_and_preserves_rollback(async_db_session, tmp_path):
    await seed(async_db_session)
    plan = tmp_path / "plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        await script.preview(async_db_session, journal, tenant_id=7)
    updates = []

    def observe(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("UPDATE KNOWLEDGEFILE"):
            updates.append(statement)

    engine = async_db_session.get_bind()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with script.JsonlJournal(tmp_path / "write.jsonl") as journal:
            result = await script.apply_plan(async_db_session, plan, journal)
        assert result["updated"] == 3
        assert len(updates) == 1
    finally:
        event.remove(engine, "before_cursor_execute", observe)


async def test_parallel_sessions_are_distinct_bounded_and_tenant_scoped(
    async_db_session,
    async_db_engine,
    tmp_path,
    monkeypatch,
):
    await seed(async_db_session)
    async_db_session.add_all(
        [KnowledgeFile(id=200 + i, tenant_id=7, knowledge_id=10, file_name=f"{i}.pdf", user_id=501) for i in range(8)]
    )
    await async_db_session.commit()
    original = script.candidate
    active = set()
    peak = 0

    async def delayed(session, *args, **kwargs):
        nonlocal peak
        assert id(session) not in active
        assert get_current_tenant_id() == 7
        active.add(id(session))
        peak = max(peak, len(active))
        try:
            await asyncio.sleep(0.01)
            return await original(session, *args, **kwargs)
        finally:
            active.remove(id(session))

    monkeypatch.setattr(script, "candidate", delayed)
    plan = tmp_path / "parallel-plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        report = await script.preview(
            async_db_session, journal, tenant_id=7, concurrency=3, session_factory=factory(async_db_engine)
        )
    assert report["would_update"] == 11
    assert 1 < peak <= 3 and not active
    # 兼容此前没有并发元信息的V1计划。
    old_plan = [json.loads(line) for line in plan.read_text().splitlines()]
    old_plan[0].pop("concurrency", None)
    plan.write_text("".join(json.dumps(record) + "\n" for record in old_plan))
    with script.JsonlJournal(tmp_path / "parallel-write.jsonl") as journal:
        result = await script.apply_plan(
            async_db_session, plan, journal, concurrency=3, session_factory=factory(async_db_engine), write_batch_size=2
        )
    assert result["updated"] == 11
    old_log_path = tmp_path / "parallel-write.jsonl"
    old_log = [json.loads(line) for line in old_log_path.read_text().splitlines()]
    old_log[0].pop("concurrency", None)
    old_log[0].pop("write_batch_size", None)
    old_log_path.write_text("".join(json.dumps(record) + "\n" for record in old_log))
    with script.JsonlJournal(tmp_path / "parallel-rollback.jsonl") as journal:
        restored = await script.apply_plan(
            async_db_session,
            tmp_path / "parallel-write.jsonl",
            journal,
            rollback=True,
            concurrency=3,
            session_factory=factory(async_db_engine),
        )
    assert restored["updated"] == 11


async def test_failure_drains_inflight_workers_without_dispatching_more(
    async_db_session, async_db_engine, tmp_path, monkeypatch
):
    await seed(async_db_session)
    async_db_session.add_all(
        [KnowledgeFile(id=200 + i, tenant_id=7, knowledge_id=10, file_name=f"{i}.pdf", user_id=501) for i in range(5)]
    )
    await async_db_session.commit()
    plan = tmp_path / "plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        await script.preview(async_db_session, journal, tenant_id=7)
    original = script.write_values
    dispatched = []

    async def injected(session, record, *args, **kwargs):
        dispatched.append(record["group_key"])
        if record["document_id"] is not None:
            raise RuntimeError("worker failed")
        await asyncio.sleep(0.02)
        return await original(session, record, *args, **kwargs)

    monkeypatch.setattr(script, "write_values", injected)
    with script.JsonlJournal(tmp_path / "write.jsonl") as journal:
        with pytest.raises(RuntimeError, match="worker failed"):
            await script.apply_plan(
                async_db_session, plan, journal, concurrency=2, session_factory=factory(async_db_engine)
            )
    assert len(dispatched) == 2
    records = [json.loads(line) for line in (tmp_path / "write.jsonl").read_text().splitlines()]
    assert len([record for record in records if record["type"] == "committed"]) == 1
    async with factory(async_db_engine)() as session:
        assert (await session.get(KnowledgeFile, 200)).belonging_organization_id == 82
        assert (await session.get(KnowledgeFile, 201)).belonging_organization_id is None


async def test_late_batch_failure_rolls_back_the_whole_document(async_db_session, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.sql.dml import Update

    await seed(async_db_session)
    plan = tmp_path / "plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        await script.preview(async_db_session, journal, tenant_id=7)
    original = async_db_session.exec
    updates = 0

    async def injected(statement, *args, **kwargs):
        nonlocal updates
        if isinstance(statement, Update):
            updates += 1
            if updates == 2:
                return SimpleNamespace(rowcount=0)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(async_db_session, "exec", injected)
    with script.JsonlJournal(tmp_path / "write.jsonl") as journal:
        result = await script.apply_plan(async_db_session, plan, journal, write_batch_size=2)
    assert updates == 2 and result["updated"] == 0 and result["skipped"] == 1
    for file_id in (99, 100, 102):
        assert (await async_db_session.get(KnowledgeFile, file_id)).belonging_organization_id is None


async def test_cancellation_waits_for_dispatched_commits(async_db_session, async_db_engine, tmp_path, monkeypatch):
    await seed(async_db_session)
    async_db_session.add_all(
        [KnowledgeFile(id=200 + i, tenant_id=7, knowledge_id=10, file_name=f"{i}.pdf", user_id=501) for i in range(3)]
    )
    await async_db_session.commit()
    plan = tmp_path / "plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        await script.preview(async_db_session, journal, tenant_id=7)
    ready, release = asyncio.Event(), asyncio.Event()
    original = script.write_values
    calls = 0

    async def gated(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            ready.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(script, "write_values", gated)
    with script.JsonlJournal(tmp_path / "write.jsonl") as journal:
        task = asyncio.create_task(
            script.apply_plan(
                async_db_session,
                plan,
                journal,
                concurrency=2,
                session_factory=factory(async_db_engine),
            )
        )
        await asyncio.wait_for(ready.wait(), timeout=10)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls == 2
    records = [json.loads(line) for line in (tmp_path / "write.jsonl").read_text().splitlines()]
    assert len([record for record in records if record["type"] == "committed"]) == 2


async def test_journal_failure_prevents_peer_writes(async_db_session, async_db_engine, tmp_path, monkeypatch):
    await seed(async_db_session)
    async_db_session.add(KnowledgeFile(id=200, tenant_id=7, knowledge_id=10, file_name="peer.pdf", user_id=501))
    await async_db_session.commit()
    plan = tmp_path / "plan.jsonl"
    with script.JsonlJournal(plan) as journal:
        await script.preview(async_db_session, journal, tenant_id=7)
    attempts = []
    with script.JsonlJournal(tmp_path / "write.jsonl") as journal:
        original = journal.write_many

        def failed(values):
            if any(value["type"] == "intent" for value in values):
                attempts.append("intent")
                raise OSError("disk failure")
            original(values)

        monkeypatch.setattr(journal, "write_many", failed)
        with pytest.raises(OSError):
            await script.apply_plan(
                async_db_session, plan, journal, concurrency=2, session_factory=factory(async_db_engine)
            )
    assert attempts == ["intent"]
    async with factory(async_db_engine)() as session:
        for file_id in (99, 100, 102, 200):
            assert (await session.get(KnowledgeFile, file_id)).belonging_organization_id is None
