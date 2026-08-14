"""通过文件级 Outbox 显式回填存量全文索引。

默认仅执行只读 dry-run。只有显式传入 ``--apply`` 才会创建或合并 Outbox; 脚本
自身不读取 RAG Chunk、不拼接正文, 也不直接写 Elasticsearch。正式全量 apply 必须在
审核全量 dry-run 报告、完成单文件/单知识库灰度并取得独立运维确认后执行。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.search.elasticsearch.manager import get_es_connection  # noqa: E402
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants  # noqa: E402
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (  # noqa: E402
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl import (  # noqa: E402
    KnowledgeFulltextOutboxRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (  # noqa: E402
    KnowledgeFulltextSourceRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_backfill_service import (  # noqa: E402
    KnowledgeFulltextBackfillService,
    KnowledgeFulltextBackfillTarget,
)

DEFAULT_REPORT_DIR = Path("migration_reports/knowledge_fulltext_backfill")
REPORT_SCHEMA_VERSION = 1
MAX_FAILURE_SAMPLES = 20

EXIT_OK = 0
EXIT_PREFLIGHT = 2
EXIT_EXECUTION = 3
EXIT_WAIT = 4
EXIT_REPORT = 5


@dataclass(frozen=True)
class BackfillTargetRecord:
    file_id: int
    outbox_id: int
    target_revision: int

    def to_domain(self) -> KnowledgeFulltextBackfillTarget:
        return KnowledgeFulltextBackfillTarget(**asdict(self))


class BackfillReportStore:
    def __init__(self, summary_path: Path, summary: dict):
        self.summary_path = summary_path
        self.summary = summary
        target_name = summary.get("targets_file")
        if not isinstance(target_name, str) or not target_name:
            raise ValueError("report targets_file is invalid")
        if Path(target_name).name != target_name:
            raise ValueError("report targets_file must stay in the report directory")
        targets_path = summary_path.parent / target_name
        if targets_path.resolve().parent != summary_path.parent.resolve():
            raise ValueError("report targets_file resolves outside the report directory")
        self.targets_path = targets_path

    @classmethod
    def create(
        cls,
        *,
        report_dir: Path,
        run_id: str,
        parameters: dict,
    ) -> BackfillReportStore:
        report_dir.mkdir(parents=True, exist_ok=True)
        summary_path = report_dir / f"{run_id}.json"
        targets_path = report_dir / f"{run_id}.targets.jsonl"
        now = datetime.now(timezone.utc).isoformat()
        summary = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "mode": "apply" if parameters.get("apply") else "dry-run",
            "index_schema_version": constants.KNOWLEDGE_FULLTEXT_INDEX_SCHEMA_VERSION,
            "parameters": parameters,
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "status": "running",
            "scanned_count": 0,
            "candidate_count": 0,
            "submitted_count": 0,
            "excluded_counts": {},
            "error_count": 0,
            "error_samples": [],
            "next_start_after_id": int(parameters.get("start_after_id") or 0),
            "target_line_count": 0,
            "targets_file": targets_path.name,
            "wait_status_counts": {},
            "verification": None,
        }
        store = cls(summary_path, summary)
        targets_path.touch(exist_ok=False)
        store.save()
        return store

    @classmethod
    def resume(cls, summary_path: Path | str) -> BackfillReportStore:
        resolved = Path(summary_path)
        with resolved.open("r", encoding="utf-8") as stream:
            summary = json.load(stream)
        if summary.get("schema_version") != REPORT_SCHEMA_VERSION:
            raise ValueError("unsupported report schema_version")
        if summary.get("mode") != "apply":
            raise ValueError("only an apply report can resume waiting")
        store = cls(resolved, summary)
        store._truncate_uncommitted_target_tail()
        return store

    def save(self) -> None:
        self.summary["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary = self.summary_path.with_name(f".{self.summary_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.summary, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.summary_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def append_committed_batch(
        self,
        targets: list[BackfillTargetRecord],
        *,
        next_start_after_id: int,
        progress: dict | None = None,
    ) -> None:
        with self.targets_path.open("a", encoding="utf-8") as stream:
            for target in targets:
                stream.write(json.dumps(asdict(target), ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.summary["target_line_count"] = int(self.summary["target_line_count"]) + len(targets)
        self.summary["submitted_count"] = int(self.summary["submitted_count"]) + len(targets)
        self.summary["next_start_after_id"] = next_start_after_id
        if progress:
            self._merge_progress(progress)
        self.save()

    def update_progress(self, *, next_start_after_id: int, progress: dict) -> None:
        self.summary["next_start_after_id"] = next_start_after_id
        self._merge_progress(progress)
        self.save()

    def add_error(self, *, file_id: int | None, error_type: str) -> None:
        self.summary["error_count"] = int(self.summary["error_count"]) + 1
        samples = self.summary["error_samples"]
        if len(samples) < MAX_FAILURE_SAMPLES:
            samples.append({"file_id": file_id, "error_type": error_type[:64]})

    def iter_target_batches(self, *, batch_size: int) -> Iterator[list[BackfillTargetRecord]]:
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        remaining = int(self.summary.get("target_line_count") or 0)
        batch: list[BackfillTargetRecord] = []
        with self.targets_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if remaining <= 0:
                    break
                payload = json.loads(line)
                batch.append(BackfillTargetRecord(**payload))
                remaining -= 1
                if len(batch) == batch_size:
                    yield batch
                    batch = []
        if remaining != 0:
            raise ValueError("target report is shorter than committed target_line_count")
        if batch:
            yield batch

    def _merge_progress(self, progress: dict) -> None:
        self.summary["scanned_count"] = int(self.summary["scanned_count"]) + int(
            progress.get("scanned_count", 0)
        )
        self.summary["candidate_count"] = int(self.summary["candidate_count"]) + int(
            progress.get("candidate_count", 0)
        )
        excluded = Counter(self.summary.get("excluded_counts") or {})
        excluded.update(progress.get("excluded_counts") or {})
        self.summary["excluded_counts"] = dict(sorted(excluded.items()))

    def _truncate_uncommitted_target_tail(self) -> None:
        expected_lines = int(self.summary.get("target_line_count") or 0)
        with self.targets_path.open("rb+") as stream:
            offset = 0
            for _ in range(expected_lines):
                line = stream.readline()
                if not line:
                    raise ValueError("target report is shorter than committed target_line_count")
                offset = stream.tell()
            stream.truncate(offset)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="创建或合并文件级 Outbox; 默认 dry-run。")
    parser.add_argument("--wait", action="store_true", help="等待本批 target revision 收敛。")
    parser.add_argument("--resume-report", type=Path, help="从 apply 报告恢复等待, 不产生新 revision。")
    parser.add_argument("--verify-es", action="store_true", help="只读核对当前候选 ID 与全文别名。")
    parser.add_argument("--knowledge-id", type=int)
    parser.add_argument("--file-id", type=int)
    parser.add_argument("--limit", type=int, help="最多扫描的文件 ID 数, 不是候选数。")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--start-after-id", type=int, default=0)
    parser.add_argument("--sleep-ms", type=int, default=0)
    parser.add_argument("--wait-timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")
    for name in ("knowledge_id", "file_id", "limit"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be greater than 0")
    if args.start_after_id < 0:
        parser.error("--start-after-id must be greater than or equal to 0")
    if args.sleep_ms < 0:
        parser.error("--sleep-ms must be greater than or equal to 0")
    if args.wait_timeout_seconds <= 0:
        parser.error("--wait-timeout-seconds must be greater than 0")
    if args.poll_interval_seconds < 1:
        parser.error("--poll-interval-seconds must be at least 1")
    if args.wait and not (args.apply or args.resume_report):
        parser.error("--wait requires --apply or --resume-report")
    if args.resume_report and not args.wait:
        parser.error("--resume-report requires --wait")
    if args.resume_report and (
        args.apply
        or args.knowledge_id is not None
        or args.file_id is not None
        or args.limit is not None
        or args.start_after_id != 0
        or args.sleep_ms != 0
    ):
        parser.error("--resume-report --wait cannot be combined with apply or scan scope options")
    return args


def _parameters(args: argparse.Namespace) -> dict:
    return {
        "apply": bool(args.apply),
        "knowledge_id": args.knowledge_id,
        "file_id": args.file_id,
        "limit": args.limit,
        "batch_size": args.batch_size,
        "start_after_id": args.start_after_id,
        "sleep_ms": args.sleep_ms,
    }


async def _scan(args, session, service, report: BackfillReportStore) -> int:
    cursor = args.start_after_id
    remaining = args.limit
    while remaining is None or remaining > 0:
        page_limit = args.batch_size if remaining is None else min(args.batch_size, remaining)
        page = await service.inspect_page(
            after_file_id=cursor,
            limit=page_limit,
            knowledge_id=args.knowledge_id,
            file_id=args.file_id,
        )
        if page.scanned_count == 0:
            await session.rollback()
            break
        progress = {
            "scanned_count": page.scanned_count,
            "candidate_count": len(page.candidates),
            "excluded_counts": page.excluded_counts,
        }
        targets: list[BackfillTargetRecord] = []
        if args.apply:
            for candidate in page.candidates:
                try:
                    async with session.begin_nested():
                        target = await service.request_target(candidate)
                    targets.append(BackfillTargetRecord(**asdict(target)))
                except Exception as exc:  # 单文件保存点失败不阻断本批其他文件。
                    report.add_error(file_id=candidate.file_id, error_type=type(exc).__name__)
            await session.commit()
            report.append_committed_batch(
                targets,
                next_start_after_id=page.next_start_after_id,
                progress=progress,
            )
            if args.sleep_ms:
                await asyncio.sleep(args.sleep_ms / 1000)
        else:
            await session.rollback()
            report.update_progress(
                next_start_after_id=page.next_start_after_id,
                progress=progress,
            )
        cursor = page.next_start_after_id
        if remaining is not None:
            remaining -= page.scanned_count
    return EXIT_EXECUTION if report.summary["error_count"] else EXIT_OK


async def _wait_for_targets(args, session, service, report: BackfillReportStore) -> int:
    deadline = time.monotonic() + args.wait_timeout_seconds
    while True:
        totals = Counter({"success": 0, "failed": 0, "pending": 0, "processing": 0})
        failure_samples: list[dict] = []
        for records in report.iter_target_batches(batch_size=args.batch_size):
            targets = [record.to_domain() for record in records]
            states = await service.classify_target_states(targets)
            for record in records:
                state = states[record.outbox_id]
                totals[state] += 1
                if state == "failed" and len(failure_samples) < MAX_FAILURE_SAMPLES:
                    failure_samples.append(
                        {"file_id": record.file_id, "outbox_id": record.outbox_id}
                    )
        await session.rollback()
        report.summary["wait_status_counts"] = dict(totals)
        report.summary["wait_failure_samples"] = failure_samples
        if totals["pending"] + totals["processing"] == 0:
            report.summary["wait_completed_at"] = datetime.now(timezone.utc).isoformat()
            report.save()
            return EXIT_WAIT if totals["failed"] else EXIT_OK
        if time.monotonic() >= deadline:
            report.summary["wait_status_counts"]["timeout"] = totals["pending"] + totals["processing"]
            report.summary["wait_timed_out_at"] = datetime.now(timezone.utc).isoformat()
            report.save()
            return EXIT_WAIT
        report.save()
        await asyncio.sleep(args.poll_interval_seconds)


async def _verify_es(args, session, service, index_repository, report: BackfillReportStore) -> None:
    cursor = args.start_after_id
    remaining = args.limit
    expected = 0
    existing = 0
    missing_samples: list[int] = []
    while remaining is None or remaining > 0:
        page_limit = args.batch_size if remaining is None else min(args.batch_size, remaining)
        page = await service.inspect_page(
            after_file_id=cursor,
            limit=page_limit,
            knowledge_id=args.knowledge_id,
            file_id=args.file_id,
        )
        if page.scanned_count == 0:
            await session.rollback()
            break
        candidate_ids = [candidate.file_id for candidate in page.candidates]
        found = await index_repository.existing_file_ids(candidate_ids)
        expected += len(candidate_ids)
        existing += len(found)
        for missing_id in (file_id for file_id in candidate_ids if file_id not in found):
            if len(missing_samples) < MAX_FAILURE_SAMPLES:
                missing_samples.append(missing_id)
        cursor = page.next_start_after_id
        if remaining is not None:
            remaining -= page.scanned_count
        await session.rollback()
    report.summary["verification"] = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": expected,
        "existing_count": existing,
        "missing_count": expected - existing,
        "missing_file_id_samples": missing_samples,
        "concurrent_drift_possible": True,
    }
    report.save()


async def run(args: argparse.Namespace) -> int:
    try:
        constants.ensure_runtime_compatible(
            multi_tenant_enabled=bool(settings.multi_tenant.enabled)
        )
    except Exception as exc:
        print(f"preflight failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_PREFLIGHT

    try:
        report = (
            BackfillReportStore.resume(args.resume_report)
            if args.resume_report
            else BackfillReportStore.create(
                report_dir=DEFAULT_REPORT_DIR,
                run_id=f"backfill-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
                parameters=_parameters(args),
            )
        )
    except Exception as exc:
        print(f"report initialization failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_REPORT

    initialized = False
    try:
        await initialize_app_context(config=settings)
        initialized = True
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                outbox_repository = KnowledgeFulltextOutboxRepositoryImpl(session)
                service = KnowledgeFulltextBackfillService(
                    source_repository=KnowledgeFulltextSourceRepositoryImpl(session),
                    outbox_repository=outbox_repository,
                    max_retries=constants.KNOWLEDGE_FULLTEXT_MAX_RETRIES,
                )
                index_repository = KnowledgeFulltextIndexRepositoryImpl(await get_es_connection())
                try:
                    await outbox_repository.validate_storage()
                    await index_repository.validate_read_index()
                    await session.rollback()
                except Exception as exc:
                    await session.rollback()
                    report.add_error(file_id=None, error_type=type(exc).__name__)
                    report.summary["status"] = "preflight_failed"
                    report.save()
                    print(f"preflight failed: {type(exc).__name__}", file=sys.stderr)
                    return EXIT_PREFLIGHT

                effective_args = args
                if args.resume_report:
                    parameters = report.summary["parameters"]
                    effective_args = argparse.Namespace(**vars(args))
                    for name in (
                        "knowledge_id",
                        "file_id",
                        "limit",
                        "batch_size",
                        "start_after_id",
                        "sleep_ms",
                    ):
                        setattr(effective_args, name, parameters.get(name))
                exit_code = EXIT_OK
                if not args.resume_report:
                    exit_code = await _scan(effective_args, session, service, report)
                if args.wait:
                    wait_exit_code = await _wait_for_targets(
                        effective_args,
                        session,
                        service,
                        report,
                    )
                    if wait_exit_code != EXIT_OK:
                        exit_code = wait_exit_code
                if args.verify_es:
                    await _verify_es(
                        effective_args,
                        session,
                        service,
                        index_repository,
                        report,
                    )
                report.summary["status"] = "completed" if exit_code == EXIT_OK else "completed_with_errors"
                report.summary["completed_at"] = datetime.now(timezone.utc).isoformat()
                report.save()
                print(json.dumps(report.summary, ensure_ascii=False, sort_keys=True))
                return exit_code
    except Exception as exc:
        report.add_error(file_id=None, error_type=type(exc).__name__)
        report.summary["status"] = "execution_failed"
        try:
            report.save()
        except Exception:
            print("report persistence failed after execution error", file=sys.stderr)
            return EXIT_REPORT
        print(f"execution failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_EXECUTION
    finally:
        if initialized:
            await close_app_context()


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
