import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.backfill_knowledge_fulltext as backfill_script
from bisheng.knowledge.domain.services.knowledge_fulltext_backfill_service import (
    KnowledgeFulltextBackfillCandidate,
    KnowledgeFulltextBackfillPage,
    KnowledgeFulltextBackfillTarget,
)
from scripts.backfill_knowledge_fulltext import (
    EXIT_EXECUTION,
    EXIT_OK,
    EXIT_WAIT,
    BackfillReportStore,
    BackfillTargetRecord,
    _scan,
    _verify_es,
    _wait_for_targets,
    parse_args,
)


class FakeNestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    def begin_nested(self):
        return FakeNestedTransaction()


def report(tmp_path, *, apply: bool) -> BackfillReportStore:
    return BackfillReportStore.create(
        report_dir=tmp_path,
        run_id="run-test",
        parameters={"apply": apply, "batch_size": 2, "start_after_id": 0},
    )


def test_cli_defaults_to_dry_run_and_bounded_batches():
    args = parse_args([])

    assert args.apply is False
    assert args.wait is False
    assert args.batch_size == 200
    assert args.start_after_id == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["--wait"],
        ["--resume-report", "report.json"],
        ["--batch-size", "0"],
        ["--batch-size", "1001"],
        ["--file-id", "0"],
        ["--poll-interval-seconds", "0"],
    ],
)
def test_cli_rejects_unsafe_or_unbounded_combinations(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_report_recovers_only_committed_target_lines(tmp_path):
    store = BackfillReportStore.create(
        report_dir=tmp_path,
        run_id="run-1",
        parameters={"apply": True, "batch_size": 2},
    )
    store.append_committed_batch(
        [BackfillTargetRecord(file_id=7, outbox_id=101, target_revision=3)],
        next_start_after_id=7,
    )

    with store.targets_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"file_id": 999, "outbox_id": 999, "target_revision": 999}) + "\n")

    resumed = BackfillReportStore.resume(store.summary_path)

    assert resumed.summary["target_line_count"] == 1
    assert resumed.summary["next_start_after_id"] == 7
    assert list(resumed.iter_target_batches(batch_size=10)) == [
        [BackfillTargetRecord(file_id=7, outbox_id=101, target_revision=3)]
    ]
    assert resumed.targets_path.read_text(encoding="utf-8").count("\n") == 1


def test_resume_report_rejects_target_path_traversal(tmp_path):
    summary_path = tmp_path / "unsafe.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "apply",
                "targets_file": "../unrelated.jsonl",
                "target_line_count": 0,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="report directory"):
        BackfillReportStore.resume(summary_path)


def test_resume_wait_does_not_allow_scope_or_new_apply():
    with pytest.raises(SystemExit):
        parse_args(["--resume-report", "report.json", "--wait", "--apply"])
    with pytest.raises(SystemExit):
        parse_args(["--resume-report", "report.json", "--wait", "--knowledge-id", "9"])


async def test_dry_run_scans_and_reports_without_outbox_or_commit(tmp_path):
    args = parse_args(["--limit", "1"])
    session = FakeSession()
    service = AsyncMock()
    service.inspect_page.side_effect = [
        KnowledgeFulltextBackfillPage(
            scanned_count=1,
            candidates=(KnowledgeFulltextBackfillCandidate(file_id=7, knowledge_id=9),),
            excluded_counts={},
            next_start_after_id=7,
        )
    ]
    store = report(tmp_path, apply=False)

    result = await _scan(args, session, service, store)

    assert result == EXIT_OK
    service.request_target.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert store.summary["candidate_count"] == 1
    assert store.summary["submitted_count"] == 0


async def test_apply_commits_other_targets_when_one_file_fails(tmp_path):
    args = parse_args(["--apply", "--limit", "2", "--batch-size", "2"])
    session = FakeSession()
    service = AsyncMock()
    service.inspect_page.return_value = KnowledgeFulltextBackfillPage(
        scanned_count=2,
        candidates=(
            KnowledgeFulltextBackfillCandidate(file_id=7, knowledge_id=9),
            KnowledgeFulltextBackfillCandidate(file_id=8, knowledge_id=9),
        ),
        excluded_counts={},
        next_start_after_id=8,
    )
    service.request_target.side_effect = [
        RuntimeError("sensitive source details"),
        KnowledgeFulltextBackfillTarget(file_id=8, outbox_id=102, target_revision=4),
    ]
    store = report(tmp_path, apply=True)

    result = await _scan(args, session, service, store)

    assert result == EXIT_EXECUTION
    session.commit.assert_awaited_once()
    assert store.summary["submitted_count"] == 1
    assert store.summary["error_samples"] == [{"file_id": 7, "error_type": "RuntimeError"}]
    assert "sensitive source details" not in store.summary_path.read_text(encoding="utf-8")


async def test_wait_accepts_applied_revision_that_has_advanced_past_target(tmp_path):
    args = parse_args(["--apply", "--wait", "--wait-timeout-seconds", "1"])
    session = FakeSession()
    service = AsyncMock()
    service.classify_target_states.return_value = {101: "success"}
    store = report(tmp_path, apply=True)
    store.append_committed_batch(
        [BackfillTargetRecord(file_id=7, outbox_id=101, target_revision=3)],
        next_start_after_id=7,
    )

    result = await _wait_for_targets(args, session, service, store)

    assert result == EXIT_OK
    assert store.summary["wait_status_counts"]["success"] == 1


async def test_wait_timeout_is_nonzero_and_does_not_cancel_outbox(tmp_path, monkeypatch):
    args = parse_args(
        [
            "--apply",
            "--wait",
            "--wait-timeout-seconds",
            "1",
            "--poll-interval-seconds",
            "1",
        ]
    )
    session = FakeSession()
    service = AsyncMock()
    service.classify_target_states.return_value = {101: "pending"}
    store = report(tmp_path, apply=True)
    store.append_committed_batch(
        [BackfillTargetRecord(file_id=7, outbox_id=101, target_revision=3)],
        next_start_after_id=7,
    )
    monotonic = iter([0.0, 2.0])
    monkeypatch.setattr(
        backfill_script,
        "time",
        SimpleNamespace(monotonic=lambda: next(monotonic, 2.0)),
    )

    result = await _wait_for_targets(args, session, service, store)

    assert result == EXIT_WAIT
    assert store.summary["wait_status_counts"] == {
        "success": 0,
        "failed": 0,
        "pending": 1,
        "processing": 0,
        "timeout": 1,
    }


async def test_verify_es_reports_missing_ids_without_writes(tmp_path):
    args = parse_args(["--verify-es", "--limit", "2"])
    session = FakeSession()
    service = AsyncMock()
    service.inspect_page.return_value = KnowledgeFulltextBackfillPage(
        scanned_count=2,
        candidates=(
            KnowledgeFulltextBackfillCandidate(file_id=7, knowledge_id=9),
            KnowledgeFulltextBackfillCandidate(file_id=8, knowledge_id=9),
        ),
        excluded_counts={},
        next_start_after_id=8,
    )
    index_repository = AsyncMock()
    index_repository.existing_file_ids.return_value = {7}
    store = report(tmp_path, apply=False)

    await _verify_es(args, session, service, index_repository, store)

    assert store.summary["verification"]["missing_file_id_samples"] == [8]
    index_repository.existing_file_ids.assert_awaited_once_with([7, 8])
    index_repository.upsert.assert_not_awaited()
    index_repository.delete.assert_not_awaited()
