"""Tests for the knowledge-space reparse maintenance script."""

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

import scripts.reparse_knowledge_space_files as script_mod
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum


def _wait_for_jsonl_events(path: Path, expected_count: int) -> list[dict]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) >= expected_count:
                return [json.loads(line) for line in lines]
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for {expected_count} JSONL events")


async def _wait_for_jsonl_event_counts(
    path: Path,
    expected_counts: dict[str, int],
) -> list[dict]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if path.exists():
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            actual_counts = {
                event_type: sum(event["event_type"] == event_type for event in events) for event_type in expected_counts
            }
            if all(actual_counts[event_type] >= expected for event_type, expected in expected_counts.items()):
                return events
        await asyncio.sleep(0.01)
    pytest.fail(f"timed out waiting for JSONL event counts: {expected_counts}")


class _FakeAsyncSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _patch_run_dependencies(monkeypatch, selection: script_mod.SelectionReport) -> None:
    async def fake_collect_candidate_files(session, **kwargs):
        return selection

    async def fake_close_app_context():
        return None

    monkeypatch.setattr(script_mod, "get_async_db_session", _FakeAsyncSessionContext)
    monkeypatch.setattr(script_mod, "collect_candidate_files", fake_collect_candidate_files)
    monkeypatch.setattr(script_mod, "close_app_context", fake_close_app_context)


async def _seed_space(
    session: AsyncSession,
    knowledge_id: int,
    *,
    knowledge_type: int = KnowledgeTypeEnum.SPACE.value,
) -> None:
    await session.exec(
        text("INSERT INTO knowledge (id, user_id, name, type) VALUES (:id, :user_id, :name, :type)").bindparams(
            id=knowledge_id,
            user_id=1,
            name=f"space-{knowledge_id}",
            type=knowledge_type,
        )
    )
    await session.commit()


async def _seed_file(
    session: AsyncSession,
    *,
    file_id: int,
    knowledge_id: int,
    status: int = KnowledgeFileStatus.SUCCESS.value,
    file_type: int = FileType.FILE.value,
    file_name: str | None = None,
    file_level_path: str | None = None,
) -> None:
    session.add(
        KnowledgeFile(
            id=file_id,
            knowledge_id=knowledge_id,
            file_name=file_name or f"file-{file_id}.pdf",
            file_type=file_type,
            status=status,
            file_level_path=file_level_path,
            object_name=f"knowledge/{knowledge_id}/{file_id}.pdf",
        )
    )
    await session.commit()


async def _seed_space_scope(
    session: AsyncSession,
    *,
    space_id: int,
    level: KnowledgeSpaceLevelEnum,
) -> None:
    await session.exec(
        text(
            "INSERT INTO knowledge_space_scope "
            "(tenant_id, space_id, level, owner_type, owner_id, created_by) "
            "VALUES (1, :space_id, :level, 'user', 1, 1)"
        ).bindparams(space_id=space_id, level=level.value)
    )
    await session.commit()


@pytest.mark.asyncio
async def test_collect_default_selects_all_space_eligible_files(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2, knowledge_type=KnowledgeTypeEnum.NORMAL.value)
    await _seed_file(async_db_session, file_id=101, knowledge_id=1, status=KnowledgeFileStatus.SUCCESS.value)
    await _seed_file(async_db_session, file_id=102, knowledge_id=1, status=KnowledgeFileStatus.FAILED.value)
    await _seed_file(async_db_session, file_id=103, knowledge_id=1, status=KnowledgeFileStatus.TIMEOUT.value)
    await _seed_file(async_db_session, file_id=104, knowledge_id=1, status=KnowledgeFileStatus.VIOLATION.value)
    await _seed_file(async_db_session, file_id=105, knowledge_id=1, status=KnowledgeFileStatus.WAITING.value)
    await _seed_file(async_db_session, file_id=106, knowledge_id=1, file_type=FileType.DIR.value)
    await _seed_file(async_db_session, file_id=201, knowledge_id=2, status=KnowledgeFileStatus.SUCCESS.value)

    report = await script_mod.collect_candidate_files(async_db_session)

    assert [item.id for item in report.selected_files] == [101, 102, 103, 104]
    assert report.skipped_status_records == 1
    assert report.skipped_folder_records == 1


@pytest.mark.asyncio
async def test_collect_explicit_scopes_are_unioned_and_folders_recurse(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2)
    await _seed_space(async_db_session, 3)
    await _seed_file(async_db_session, file_id=10, knowledge_id=1, file_type=FileType.DIR.value)
    await _seed_file(async_db_session, file_id=11, knowledge_id=1, file_level_path="/10")
    await _seed_file(async_db_session, file_id=12, knowledge_id=1, file_type=FileType.DIR.value, file_level_path="/10")
    await _seed_file(async_db_session, file_id=13, knowledge_id=1, file_level_path="/10/12")
    await _seed_file(
        async_db_session, file_id=14, knowledge_id=1, status=KnowledgeFileStatus.PROCESSING.value, file_level_path="/10"
    )
    await _seed_file(async_db_session, file_id=21, knowledge_id=2)
    await _seed_file(async_db_session, file_id=31, knowledge_id=3)

    report = await script_mod.collect_candidate_files(
        async_db_session,
        space_ids=[3],
        folder_ids=[10],
        file_ids=[21],
    )

    assert [item.id for item in report.selected_files] == [11, 13, 21, 31]
    assert report.skipped_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("space_level", "expected_file_id"),
    [
        (KnowledgeSpaceLevelEnum.PUBLIC, 101),
        (KnowledgeSpaceLevelEnum.DEPARTMENT, 201),
        (KnowledgeSpaceLevelEnum.TEAM, 301),
        (KnowledgeSpaceLevelEnum.PERSONAL, 401),
    ],
)
async def test_collect_filters_by_space_level(
    async_db_session: AsyncSession,
    space_level: KnowledgeSpaceLevelEnum,
    expected_file_id: int,
):
    levels = [
        KnowledgeSpaceLevelEnum.PUBLIC,
        KnowledgeSpaceLevelEnum.DEPARTMENT,
        KnowledgeSpaceLevelEnum.TEAM,
        KnowledgeSpaceLevelEnum.PERSONAL,
    ]
    for index, level in enumerate(levels, start=1):
        await _seed_space(async_db_session, index)
        await _seed_space_scope(async_db_session, space_id=index, level=level)
        await _seed_file(async_db_session, file_id=index * 100 + 1, knowledge_id=index)

    report = await script_mod.collect_candidate_files(
        async_db_session,
        space_level=space_level,
    )

    assert [item.id for item in report.selected_files] == [expected_file_id]


@pytest.mark.asyncio
async def test_space_without_scope_does_not_match_space_level(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2)
    await _seed_space_scope(async_db_session, space_id=1, level=KnowledgeSpaceLevelEnum.PUBLIC)
    await _seed_file(async_db_session, file_id=101, knowledge_id=1)
    await _seed_file(async_db_session, file_id=201, knowledge_id=2)

    report = await script_mod.collect_candidate_files(
        async_db_session,
        space_level=KnowledgeSpaceLevelEnum.PUBLIC,
    )

    assert [item.id for item in report.selected_files] == [101]


@pytest.mark.asyncio
async def test_space_level_intersects_union_of_explicit_scopes(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2)
    await _seed_space(async_db_session, 3)
    await _seed_space_scope(async_db_session, space_id=1, level=KnowledgeSpaceLevelEnum.PUBLIC)
    await _seed_space_scope(async_db_session, space_id=2, level=KnowledgeSpaceLevelEnum.DEPARTMENT)
    await _seed_space_scope(async_db_session, space_id=3, level=KnowledgeSpaceLevelEnum.TEAM)
    await _seed_file(async_db_session, file_id=10, knowledge_id=1, file_type=FileType.DIR.value)
    await _seed_file(async_db_session, file_id=11, knowledge_id=1, file_level_path="/10")
    await _seed_file(async_db_session, file_id=21, knowledge_id=2)
    await _seed_file(async_db_session, file_id=31, knowledge_id=3)

    report = await script_mod.collect_candidate_files(
        async_db_session,
        space_ids=[2],
        folder_ids=[10],
        file_ids=[31],
        space_level=KnowledgeSpaceLevelEnum.PUBLIC,
    )

    assert [item.id for item in report.selected_files] == [11]


@pytest.mark.asyncio
async def test_collect_uses_explicit_status_union(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space_scope(async_db_session, space_id=1, level=KnowledgeSpaceLevelEnum.DEPARTMENT)
    await _seed_file(async_db_session, file_id=101, knowledge_id=1, status=KnowledgeFileStatus.SUCCESS.value)
    await _seed_file(async_db_session, file_id=102, knowledge_id=1, status=KnowledgeFileStatus.FAILED.value)
    await _seed_file(async_db_session, file_id=103, knowledge_id=1, status=KnowledgeFileStatus.WAITING.value)
    await _seed_file(async_db_session, file_id=104, knowledge_id=1, status=KnowledgeFileStatus.VIOLATION.value)

    report = await script_mod.collect_candidate_files(
        async_db_session,
        space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        eligible_statuses=(
            KnowledgeFileStatus.FAILED.value,
            KnowledgeFileStatus.WAITING.value,
            KnowledgeFileStatus.VIOLATION.value,
        ),
    )

    assert [item.id for item in report.selected_files] == [102, 103, 104]


@pytest.mark.asyncio
async def test_run_reparse_files_continues_after_single_file_failure(capsys):
    files = [
        KnowledgeFile(id=1, knowledge_id=1, file_name="a.pdf"),
        KnowledgeFile(id=2, knowledge_id=1, file_name="b.pdf"),
        KnowledgeFile(id=3, knowledge_id=1, file_name="c.pdf"),
    ]
    attempts: list[int] = []

    def fake_reparse(file_id: int) -> script_mod.FileReparseResult:
        attempts.append(file_id)
        if file_id == 2:
            raise RuntimeError("boom")
        return script_mod.FileReparseResult(
            file_id=file_id,
            knowledge_id=1,
            file_name=f"{file_id}.pdf",
            success=True,
            final_status=KnowledgeFileStatus.SUCCESS.value,
        )

    report = await script_mod.run_reparse_files(files, concurrency=2, reparse_func=fake_reparse)

    assert sorted(attempts) == [1, 2, 3]
    assert report.success == 2
    assert report.failed == 1
    assert report.total == 3
    assert report.duration_seconds >= 0
    assert report.started_at.endswith("+00:00")
    assert report.finished_at.endswith("+00:00")
    assert all(result.started_at.endswith("+00:00") for result in report.results)
    assert all(result.finished_at.endswith("+00:00") for result in report.results)
    assert all(result.duration_seconds >= 0 for result in report.results)
    failed = [item for item in report.results if not item.success]
    assert failed[0].file_id == 2
    assert "RuntimeError: boom" in failed[0].error
    output = capsys.readouterr().out
    assert output.count("[START]") == 3
    assert "progress=3/3 (100.0%)" in output
    assert "success=2 failed=1" in output
    assert "elapsed=" in output


@pytest.mark.asyncio
async def test_run_reparse_files_never_exceeds_concurrency():
    files = [KnowledgeFile(id=file_id, knowledge_id=1, file_name=f"{file_id}.pdf") for file_id in range(1, 7)]
    lock = threading.Lock()
    two_active = threading.Event()
    active = 0
    max_active = 0

    def fake_reparse(file_id: int) -> script_mod.FileReparseResult:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                two_active.set()
        assert two_active.wait(timeout=1)
        time.sleep(0.01)
        with lock:
            active -= 1
        return script_mod.FileReparseResult(
            file_id=file_id,
            knowledge_id=1,
            file_name=f"{file_id}.pdf",
            success=True,
            final_status=KnowledgeFileStatus.SUCCESS.value,
        )

    report = await script_mod.run_reparse_files(files, concurrency=2, reparse_func=fake_reparse)

    assert max_active == 2
    assert report.success == 6
    assert report.failed == 0


@pytest.mark.asyncio
async def test_run_reparse_files_uses_executable_file_count_for_totals():
    files = [
        KnowledgeFile(id=None, knowledge_id=1, file_name="missing-id.pdf"),
        KnowledgeFile(id=1, knowledge_id=1, file_name="valid.pdf"),
    ]

    def fake_reparse(file_id: int) -> script_mod.FileReparseResult:
        return script_mod.FileReparseResult(
            file_id=file_id,
            knowledge_id=1,
            file_name="valid.pdf",
            success=True,
            final_status=KnowledgeFileStatus.SUCCESS.value,
        )

    report = await script_mod.run_reparse_files(files, concurrency=1, reparse_func=fake_reparse)

    assert report.total == 1
    assert report.success + report.failed == report.total


def test_reparse_one_file_clears_vectors_and_runs_pipeline(monkeypatch):
    db_file = KnowledgeFile(
        id=100,
        knowledge_id=10,
        file_name="doc.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        simhash="abcdef0123456789",
        similar_status=1,
    )
    knowledge = Knowledge(id=10, name="space", type=KnowledgeTypeEnum.SPACE.value, user_id=1)
    calls: list[str] = []

    monkeypatch.setattr(script_mod, "_get_file_sync", lambda file_id: db_file)
    monkeypatch.setattr(script_mod, "_get_knowledge_sync", lambda knowledge_id: knowledge)

    def fake_update(file: KnowledgeFile) -> KnowledgeFile:
        calls.append(f"update:{file.status}:{file.simhash}:{file.similar_status}")
        return file

    def fake_delete(file_id: int, db_knowledge: Knowledge) -> None:
        calls.append(f"delete:{file_id}:{db_knowledge.id}")

    def fake_parse(db_knowledge: Knowledge, file: KnowledgeFile) -> None:
        calls.append(f"parse:{file.id}:{db_knowledge.id}")
        file.status = KnowledgeFileStatus.SUCCESS.value
        file.remark = ""

    monkeypatch.setattr(script_mod, "_update_file_sync", fake_update)
    monkeypatch.setattr(script_mod, "_delete_existing_vectors", fake_delete)
    monkeypatch.setattr(script_mod, "_run_parse_pipeline", fake_parse)

    result = script_mod.reparse_one_file(100)

    assert result.success is True
    assert calls == [
        "update:1:None:0",
        "delete:100:10",
        "parse:100:10",
    ]


def test_reparse_one_file_honors_explicit_statuses_at_execution_time(monkeypatch):
    db_file = KnowledgeFile(
        id=100,
        knowledge_id=10,
        file_name="doc.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.WAITING.value,
    )
    knowledge = Knowledge(id=10, name="space", type=KnowledgeTypeEnum.SPACE.value, user_id=1)
    calls: list[str] = []

    monkeypatch.setattr(script_mod, "_get_file_sync", lambda file_id: db_file)
    monkeypatch.setattr(script_mod, "_get_knowledge_sync", lambda knowledge_id: knowledge)
    monkeypatch.setattr(script_mod, "_update_file_sync", lambda file: file)
    monkeypatch.setattr(script_mod, "_delete_existing_vectors", lambda file_id, db_knowledge: calls.append("delete"))

    def fake_parse(db_knowledge: Knowledge, file: KnowledgeFile) -> None:
        calls.append("parse")
        file.status = KnowledgeFileStatus.SUCCESS.value

    monkeypatch.setattr(script_mod, "_run_parse_pipeline", fake_parse)

    result = script_mod.reparse_one_file(
        100,
        eligible_statuses=(KnowledgeFileStatus.WAITING.value,),
    )

    assert result.success is True
    assert calls == ["delete", "parse"]


def test_reparse_one_file_rejects_status_changed_after_selection(monkeypatch):
    db_file = KnowledgeFile(
        id=100,
        knowledge_id=10,
        file_name="doc.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.WAITING.value,
    )
    monkeypatch.setattr(script_mod, "_get_file_sync", lambda file_id: db_file)

    result = script_mod.reparse_one_file(
        100,
        eligible_statuses=(KnowledgeFileStatus.FAILED.value,),
    )

    assert result.success is False
    assert result.error == "file is in-flight"


def test_parse_args_defaults_to_dry_run_and_single_concurrency():
    args = script_mod.parse_args([])

    assert args.apply is False
    assert args.concurrency == 1
    assert args.space_ids == []
    assert args.folder_ids == []
    assert args.file_ids == []
    assert args.space_level is None
    assert args.statuses == []
    assert args.report_file is None


def test_parse_args_accepts_space_level_and_repeated_statuses():
    args = script_mod.parse_args(
        [
            "--space-level",
            "department",
            "--status",
            "failed",
            "--status",
            "waiting",
            "--status",
            "violation",
        ]
    )

    assert args.space_level == "department"
    assert args.statuses == ["failed", "waiting", "violation"]
    assert script_mod.resolve_eligible_statuses(args) == (
        KnowledgeFileStatus.FAILED.value,
        KnowledgeFileStatus.WAITING.value,
        KnowledgeFileStatus.VIOLATION.value,
    )


def test_parse_args_accepts_report_file():
    args = script_mod.parse_args(["--report-file", "/tmp/reparse.jsonl"])

    assert args.report_file == "/tmp/reparse.jsonl"


@pytest.mark.parametrize("legacy_flag", ["--include-inflight", "--only-inflight"])
def test_parse_args_rejects_status_with_legacy_inflight_flags(legacy_flag: str):
    with pytest.raises(SystemExit) as exc_info:
        script_mod.parse_args(["--status", "failed", legacy_flag])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["--space-level", "unknown"],
        ["--status", "unknown"],
    ],
)
def test_parse_args_rejects_unknown_space_levels_and_statuses(argv: list[str]):
    with pytest.raises(SystemExit) as exc_info:
        script_mod.parse_args(argv)

    assert exc_info.value.code == 2


def test_jsonl_report_writer_flushes_events_before_close(tmp_path: Path):
    report_path = tmp_path / "reports" / "run.jsonl"
    writer = script_mod.JsonlReportWriter(report_path, run_id="run-1")

    writer.start()
    writer.emit("run_started", {"concurrency": 2})

    events = _wait_for_jsonl_events(report_path, 1)
    writer.close()

    assert events == [
        {
            "schema_version": 1,
            "run_id": "run-1",
            "event_type": "run_started",
            "timestamp": events[0]["timestamp"],
            "concurrency": 2,
        }
    ]
    assert events[0]["timestamp"].endswith("+00:00")


def test_jsonl_report_writer_serializes_concurrent_producers(tmp_path: Path):
    report_path = tmp_path / "run.jsonl"
    writer = script_mod.JsonlReportWriter(report_path, run_id="run-2")
    writer.start()

    threads = [
        threading.Thread(target=writer.emit, args=("file_started", {"file_id": file_id})) for file_id in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    writer.close()
    events = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]

    assert len(events) == 10
    assert {event["file_id"] for event in events} == set(range(10))
    assert {event["event_type"] for event in events} == {"file_started"}


def test_jsonl_report_writer_refuses_existing_file(tmp_path: Path):
    report_path = tmp_path / "run.jsonl"
    report_path.write_text('{"existing": true}\n', encoding="utf-8")
    writer = script_mod.JsonlReportWriter(report_path, run_id="run-3")

    with pytest.raises(script_mod.ReportWriteError, match="already exists"):
        writer.start()

    assert report_path.read_text(encoding="utf-8") == '{"existing": true}\n'


def test_jsonl_report_writer_propagates_serialization_failure(tmp_path: Path):
    report_path = tmp_path / "run.jsonl"
    writer = script_mod.JsonlReportWriter(report_path, run_id="run-4")
    writer.start()
    writer.emit("run_started", {"invalid": object()})

    with pytest.raises(script_mod.ReportWriteError, match="not JSON serializable"):
        writer.close()


@pytest.mark.asyncio
async def test_apply_run_writes_complete_jsonl_lifecycle(monkeypatch, tmp_path: Path):
    files = [
        KnowledgeFile(id=1, knowledge_id=10, file_name="a.pdf"),
        KnowledgeFile(id=2, knowledge_id=10, file_name="b.pdf"),
    ]
    selection = script_mod.SelectionReport(selected_files=files)
    _patch_run_dependencies(monkeypatch, selection)

    def fake_reparse(file_id: int, **kwargs) -> script_mod.FileReparseResult:
        if file_id == 2:
            raise RuntimeError("boom")
        return script_mod.FileReparseResult(
            file_id=file_id,
            knowledge_id=10,
            file_name="a.pdf",
            success=True,
            final_status=KnowledgeFileStatus.SUCCESS.value,
        )

    monkeypatch.setattr(script_mod, "reparse_one_file", fake_reparse)
    report_path = tmp_path / "run.jsonl"
    args = script_mod.parse_args(
        [
            "--apply",
            "--concurrency",
            "1",
            "--report-file",
            str(report_path),
        ]
    )

    exit_code = await script_mod.run(args)
    events = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
    event_types = [event["event_type"] for event in events]

    assert exit_code == 2
    assert event_types[:3] == ["run_started", "selection_completed", "processing_started"]
    assert event_types[-1] == "run_completed"
    assert event_types.count("file_started") == 2
    assert event_types.count("file_completed") == 2
    for file_id in (1, 2):
        started_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "file_started" and event["file_id"] == file_id
        )
        completed_index = next(
            index
            for index, event in enumerate(events)
            if event["event_type"] == "file_completed" and event["file_id"] == file_id
        )
        assert started_index < completed_index

    completed = [event for event in events if event["event_type"] == "file_completed"]
    assert all(event["started_at"].endswith("+00:00") for event in completed)
    assert all(event["finished_at"].endswith("+00:00") for event in completed)
    assert all(event["duration_seconds"] >= 0 for event in completed)
    assert completed[-1]["completed"] == 2
    assert completed[-1]["total"] == 2
    summary = events[-1]
    assert summary["run_status"] == "partial_failure"
    assert summary["total"] == 2
    assert summary["success"] == 1
    assert summary["failed"] == 1
    assert summary["selection_duration_seconds"] >= 0
    assert summary["processing_duration_seconds"] >= 0
    assert summary["total_duration_seconds"] >= summary["processing_duration_seconds"]


@pytest.mark.asyncio
async def test_apply_run_flushes_file_events_while_batch_is_still_running(
    monkeypatch,
    tmp_path: Path,
):
    files = [
        KnowledgeFile(id=1, knowledge_id=10, file_name="a.pdf"),
        KnowledgeFile(id=2, knowledge_id=10, file_name="b.pdf"),
    ]
    _patch_run_dependencies(
        monkeypatch,
        script_mod.SelectionReport(selected_files=files),
    )
    lock = threading.Lock()
    release_second = threading.Event()
    second_started = threading.Event()
    invocation_count = 0

    def fake_reparse(file_id: int, **kwargs) -> script_mod.FileReparseResult:
        nonlocal invocation_count
        with lock:
            invocation_count += 1
            invocation = invocation_count
        if invocation == 2:
            second_started.set()
            assert release_second.wait(timeout=2)
        return script_mod.FileReparseResult(
            file_id=file_id,
            knowledge_id=10,
            file_name=f"{file_id}.pdf",
            success=True,
            final_status=KnowledgeFileStatus.SUCCESS.value,
        )

    monkeypatch.setattr(script_mod, "reparse_one_file", fake_reparse)
    report_path = tmp_path / "live.jsonl"
    args = script_mod.parse_args(
        [
            "--apply",
            "--concurrency",
            "1",
            "--report-file",
            str(report_path),
        ]
    )

    run_task = asyncio.create_task(script_mod.run(args))
    assert await asyncio.to_thread(second_started.wait, 2)
    events = await _wait_for_jsonl_event_counts(
        report_path,
        {"file_started": 2, "file_completed": 1},
    )

    assert run_task.done() is False
    assert sum(event["event_type"] == "file_started" for event in events) == 2
    assert sum(event["event_type"] == "file_completed" for event in events) == 1

    release_second.set()
    assert await run_task == 0


@pytest.mark.asyncio
async def test_apply_run_with_empty_selection_writes_run_summary(monkeypatch, tmp_path: Path):
    _patch_run_dependencies(monkeypatch, script_mod.SelectionReport())
    report_path = tmp_path / "empty.jsonl"
    args = script_mod.parse_args(["--apply", "--report-file", str(report_path)])

    exit_code = await script_mod.run(args)
    events = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]

    assert exit_code == 0
    assert [event["event_type"] for event in events] == [
        "run_started",
        "selection_completed",
        "run_completed",
    ]
    assert events[-1]["run_status"] == "success"
    assert events[-1]["total"] == 0
    assert events[-1]["success"] == 0
    assert events[-1]["failed"] == 0


@pytest.mark.asyncio
async def test_dry_run_does_not_create_jsonl_report(monkeypatch, tmp_path: Path):
    selection = script_mod.SelectionReport(selected_files=[KnowledgeFile(id=1, knowledge_id=10, file_name="a.pdf")])
    _patch_run_dependencies(monkeypatch, selection)
    report_path = tmp_path / "dry-run.jsonl"
    args = script_mod.parse_args(["--report-file", str(report_path)])

    exit_code = await script_mod.run(args)

    assert exit_code == 0
    assert not report_path.exists()


@pytest.mark.asyncio
async def test_apply_run_refuses_existing_report_before_selection(monkeypatch, tmp_path: Path):
    selection_called = False

    async def fake_collect_candidate_files(session, **kwargs):
        nonlocal selection_called
        selection_called = True
        return script_mod.SelectionReport()

    async def fake_close_app_context():
        return None

    monkeypatch.setattr(script_mod, "get_async_db_session", _FakeAsyncSessionContext)
    monkeypatch.setattr(script_mod, "collect_candidate_files", fake_collect_candidate_files)
    monkeypatch.setattr(script_mod, "close_app_context", fake_close_app_context)
    report_path = tmp_path / "existing.jsonl"
    report_path.write_text('{"existing": true}\n', encoding="utf-8")
    args = script_mod.parse_args(["--apply", "--report-file", str(report_path)])

    exit_code = await script_mod.run(args)

    assert exit_code != 0
    assert selection_called is False
    assert report_path.read_text(encoding="utf-8") == '{"existing": true}\n'


@pytest.mark.asyncio
async def test_apply_run_returns_nonzero_when_writer_close_fails(monkeypatch, tmp_path: Path):
    _patch_run_dependencies(monkeypatch, script_mod.SelectionReport())

    class FailingCloseWriter:
        def __init__(self, path, *, run_id):
            self.path = path
            self.run_id = run_id

        def start(self):
            return self

        def emit(self, event_type, payload=None):
            return None

        def close(self):
            raise script_mod.ReportWriteError("flush failed")

    monkeypatch.setattr(script_mod, "JsonlReportWriter", FailingCloseWriter)
    args = script_mod.parse_args(["--apply", "--report-file", str(tmp_path / "runtime-failure.jsonl")])

    exit_code = await script_mod.run(args)

    assert exit_code != 0


@pytest.mark.asyncio
async def test_apply_run_records_failed_terminal_event_before_reraising(monkeypatch, tmp_path: Path):
    async def fake_collect_candidate_files(session, **kwargs):
        raise RuntimeError("selection failed")

    async def fake_close_app_context():
        return None

    monkeypatch.setattr(script_mod, "get_async_db_session", _FakeAsyncSessionContext)
    monkeypatch.setattr(script_mod, "collect_candidate_files", fake_collect_candidate_files)
    monkeypatch.setattr(script_mod, "close_app_context", fake_close_app_context)
    report_path = tmp_path / "failed-run.jsonl"
    args = script_mod.parse_args(["--apply", "--report-file", str(report_path)])

    with pytest.raises(RuntimeError, match="selection failed"):
        await script_mod.run(args)

    events = [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == ["run_started", "run_completed"]
    assert events[-1]["run_status"] == "failed"
    assert events[-1]["error_type"] == "RuntimeError"
    assert events[-1]["error"] == "selection failed"
