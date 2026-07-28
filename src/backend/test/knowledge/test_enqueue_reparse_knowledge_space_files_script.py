"""Tests for the knowledge-space reparse enqueue maintenance script."""

from types import SimpleNamespace

import pytest

import scripts.enqueue_reparse_knowledge_space_files as script_mod
from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)


def _make_file(
    file_id: int,
    *,
    tenant_id: int = 1,
    knowledge_id: int = 10,
    status: int = KnowledgeFileStatus.SUCCESS.value,
    file_type: int = FileType.FILE.value,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=tenant_id,
        knowledge_id=knowledge_id,
        file_name=f"file-{file_id}.pdf",
        file_type=file_type,
        status=status,
        remark="original remark",
        simhash="abcdef0123456789",
        similar_status=1,
    )


def _make_space(knowledge_id: int = 10, *, tenant_id: int = 1) -> Knowledge:
    return Knowledge(
        id=knowledge_id,
        tenant_id=tenant_id,
        name=f"space-{knowledge_id}",
        type=KnowledgeTypeEnum.SPACE.value,
        user_id=1,
    )


def test_parse_args_defaults_to_dry_run_and_preserves_selection_filters():
    args = script_mod.parse_args([])

    assert args.apply is False
    assert args.space_ids == []
    assert args.folder_ids == []
    assert args.file_ids == []
    assert args.space_level is None
    assert args.statuses == []
    assert args.include_inflight is False
    assert args.only_inflight is False


def test_parse_args_rejects_explicit_status_with_inflight_flags():
    with pytest.raises(SystemExit):
        script_mod.parse_args(["--status", "failed", "--include-inflight"])


def test_apply_selection_dry_run_has_no_enqueue_side_effect(capsys):
    selected = script_mod.SelectionReport(selected_files=[_make_file(1)])
    calls: list[int] = []

    report = script_mod.apply_selection(
        selected,
        apply=False,
        eligible_statuses=(KnowledgeFileStatus.SUCCESS.value,),
        enqueue_func=lambda file_id, *, eligible_statuses: calls.append(file_id),
    )

    assert report is None
    assert calls == []
    assert "Dry-run only" in capsys.readouterr().out


def test_enqueue_one_file_updates_state_and_publishes_with_tenant():
    db_file = _make_file(100, tenant_id=7)
    knowledge = _make_space(tenant_id=7)
    updates: list[tuple[int, str | None, str | None, int]] = []
    published: list[tuple[int, int]] = []

    def update_file(file: KnowledgeFile) -> KnowledgeFile:
        updates.append((file.status, file.remark, file.simhash, file.similar_status))
        return file

    def publish_task(file_id: int, tenant_id: int) -> str:
        published.append((file_id, tenant_id))
        return "task-100"

    result = script_mod.enqueue_one_file(
        100,
        eligible_statuses=(KnowledgeFileStatus.SUCCESS.value,),
        fetch_file=lambda file_id: db_file,
        fetch_knowledge=lambda knowledge_id: knowledge,
        update_file=update_file,
        publish_task=publish_task,
    )

    assert result.outcome == script_mod.EnqueueOutcome.ENQUEUED
    assert result.task_id == "task-100"
    assert updates == [(KnowledgeFileStatus.WAITING.value, "", None, 0)]
    assert published == [(100, 7)]


@pytest.mark.parametrize(
    ("db_file", "knowledge", "expected_error"),
    [
        (None, None, "file not found"),
        (_make_file(100, file_type=FileType.DIR.value), _make_space(), "record is not a file"),
        (
            _make_file(100, status=KnowledgeFileStatus.PROCESSING.value),
            _make_space(),
            "status is no longer eligible",
        ),
        (
            _make_file(100),
            Knowledge(id=10, tenant_id=1, name="normal", type=KnowledgeTypeEnum.NORMAL.value, user_id=1),
            "knowledge is not a space",
        ),
    ],
    ids=["missing", "folder", "status-drift", "non-space"],
)
def test_enqueue_one_file_skips_records_that_are_no_longer_eligible(
    db_file: KnowledgeFile | None,
    knowledge: Knowledge | None,
    expected_error: str,
):
    updates: list[int] = []
    published: list[int] = []

    result = script_mod.enqueue_one_file(
        100,
        eligible_statuses=(KnowledgeFileStatus.SUCCESS.value,),
        fetch_file=lambda file_id: db_file,
        fetch_knowledge=lambda knowledge_id: knowledge,
        update_file=lambda file: updates.append(int(file.id)) or file,
        publish_task=lambda file_id, tenant_id: published.append(file_id) or "task",
    )

    assert result.outcome == script_mod.EnqueueOutcome.SKIPPED
    assert result.error == expected_error
    assert updates == []
    assert published == []


def test_publish_retry_task_uses_explicit_queue_and_isolates_tenant_headers():
    calls: list[tuple[dict, int | None]] = []

    class FakeTask:
        def apply_async(self, **kwargs):
            calls.append((kwargs, get_current_tenant_id()))
            return SimpleNamespace(id=f"task-{len(calls)}")

    task = FakeTask()
    outer_token = set_current_tenant_id(99)
    try:
        first_id = script_mod.publish_retry_task(100, 7, task=task)
        second_id = script_mod.publish_retry_task(200, 9, task=task)
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)

    assert first_id == "task-1"
    assert second_id == "task-2"
    assert calls == [
        (
            {
                "args": [100],
                "queue": "knowledge_celery",
                "headers": {"tenant_id": 7},
            },
            7,
        ),
        (
            {
                "args": [200],
                "queue": "knowledge_celery",
                "headers": {"tenant_id": 9},
            },
            9,
        ),
    ]


def test_enqueue_one_file_restores_snapshot_when_publish_fails():
    db_file = _make_file(100)
    knowledge = _make_space()
    updates: list[tuple[int, str | None, str | None, int]] = []

    def update_file(file: KnowledgeFile) -> KnowledgeFile:
        updates.append((file.status, file.remark, file.simhash, file.similar_status))
        return file

    def publish_task(file_id: int, tenant_id: int) -> str:
        raise RuntimeError("broker unavailable")

    result = script_mod.enqueue_one_file(
        100,
        eligible_statuses=(KnowledgeFileStatus.SUCCESS.value,),
        fetch_file=lambda file_id: db_file,
        fetch_knowledge=lambda knowledge_id: knowledge,
        update_file=update_file,
        publish_task=publish_task,
    )

    assert result.outcome == script_mod.EnqueueOutcome.FAILED
    assert result.error == "publish failed: broker unavailable"
    assert result.rollback_error == ""
    assert updates == [
        (KnowledgeFileStatus.WAITING.value, "", None, 0),
        (KnowledgeFileStatus.SUCCESS.value, "original remark", "abcdef0123456789", 1),
    ]


def test_enqueue_one_file_reports_publish_and_rollback_failures():
    db_file = _make_file(100)
    knowledge = _make_space()
    update_count = 0

    def update_file(file: KnowledgeFile) -> KnowledgeFile:
        nonlocal update_count
        update_count += 1
        if update_count == 2:
            raise RuntimeError("database rollback failed")
        return file

    def publish_task(file_id: int, tenant_id: int) -> str:
        raise RuntimeError("broker unavailable")

    result = script_mod.enqueue_one_file(
        100,
        eligible_statuses=(KnowledgeFileStatus.SUCCESS.value,),
        fetch_file=lambda file_id: db_file,
        fetch_knowledge=lambda knowledge_id: knowledge,
        update_file=update_file,
        publish_task=publish_task,
    )

    assert result.outcome == script_mod.EnqueueOutcome.FAILED
    assert result.error == "publish failed: broker unavailable"
    assert result.rollback_error == "rollback failed: database rollback failed"


def test_run_enqueue_files_continues_and_reports_distinct_outcomes(capsys):
    files = [_make_file(1), _make_file(2), _make_file(3)]
    attempted: list[int] = []

    def enqueue_func(file_id: int, *, eligible_statuses: tuple[int, ...]):
        attempted.append(file_id)
        if file_id == 1:
            return script_mod.FileEnqueueResult(file_id, 1, "one.pdf", script_mod.EnqueueOutcome.ENQUEUED)
        if file_id == 2:
            return script_mod.FileEnqueueResult(
                file_id,
                1,
                "two.pdf",
                script_mod.EnqueueOutcome.FAILED,
                error="publish failed",
            )
        return script_mod.FileEnqueueResult(
            file_id,
            1,
            "three.pdf",
            script_mod.EnqueueOutcome.SKIPPED,
            error="status is no longer eligible",
        )

    report = script_mod.run_enqueue_files(
        files,
        eligible_statuses=(KnowledgeFileStatus.SUCCESS.value,),
        enqueue_func=enqueue_func,
    )
    script_mod.print_run_report(report)

    assert attempted == [1, 2, 3]
    assert report.selected == 3
    assert report.enqueued == 1
    assert report.failed == 1
    assert report.skipped == 1
    assert script_mod.exit_code_for_report(report) == 2
    output = capsys.readouterr().out
    assert "[ENQUEUED]" in output
    assert "selected=3 enqueued=1 skipped=1 failed=1" in output
    assert "parse success" not in output.lower()
