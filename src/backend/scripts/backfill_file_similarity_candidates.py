"""Backfill persisted similarity candidates for historical knowledge-space files.

Why:
    New uploads refresh ``knowledge_file_similarity_candidate`` asynchronously after
    parse. Historical files need a one-shot backfill so ``similar-pending`` and
    ``file/{id}/similar`` can read cached rows instead of recalculating on request.

How to run from ``src/backend``:
    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py
    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply --knowledge-id 3516
    PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply --limit 200 --sleep-ms 100

Default is dry-run. Pass ``--apply`` to write candidate rows and update
``knowledgefile.similar_status``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile  # noqa: E402
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (  # noqa: E402
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (  # noqa: E402
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (  # noqa: E402
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_similarity_candidate_repository_impl import (  # noqa: E402
    KnowledgeFileSimilarityCandidateRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService  # noqa: E402

KNOWLEDGE_TYPE_SPACE = 3
FILE_TYPE_FILE = 1
FILE_STATUS_SUCCESS = 2
SIMILAR_STATUS_RESOLVED = 2
ZERO_SIMHASH = "0" * 16


@dataclass
class BackfillReport:
    total_files_scanned: int = 0
    skipped_invalid_encoding: int = 0
    would_refresh: int = 0
    refreshed_files: int = 0
    candidates_written: int = 0
    no_candidates: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"total_files_scanned={self.total_files_scanned} "
            f"skipped_invalid_encoding={self.skipped_invalid_encoding} "
            f"would_refresh={self.would_refresh} "
            f"refreshed_files={self.refreshed_files} "
            f"candidates_written={self.candidates_written} "
            f"no_candidates={self.no_candidates} "
            f"errors={len(self.errors)}"
        )


def _encoding_first_three_segments(file_encoding: str | None) -> tuple[str, str, str] | None:
    parts = [part.strip() for part in (file_encoding or "").split("-")]
    if len(parts) < 3 or not all(parts[:3]):
        return None
    return parts[0], parts[1], parts[2]


def _build_service(session: AsyncSession) -> KnowledgeVersionService:
    return KnowledgeVersionService(
        request=None,
        login_user=SimpleNamespace(user_id=0, user_name="system"),
        doc_repo=KnowledgeDocumentRepositoryImpl(session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(session),
        similar_candidate_repo=KnowledgeFileSimilarityCandidateRepositoryImpl(session),
    )


def _candidate_stmt(*, knowledge_id: int | None, last_id: int, batch_size: int):
    stmt = (
        select(KnowledgeFile)
        .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
        .where(
            Knowledge.type == KNOWLEDGE_TYPE_SPACE,
            KnowledgeFile.id > last_id,
            KnowledgeFile.file_type == FILE_TYPE_FILE,
            KnowledgeFile.status == FILE_STATUS_SUCCESS,
            KnowledgeFile.similar_status != SIMILAR_STATUS_RESOLVED,
            KnowledgeFile.simhash.is_not(None),
            KnowledgeFile.simhash != ZERO_SIMHASH,
            KnowledgeFile.file_encoding.is_not(None),
        )
        .order_by(KnowledgeFile.id)
        .limit(batch_size)
    )
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeFile.knowledge_id == knowledge_id)
    return stmt


async def backfill(
    session: AsyncSession,
    *,
    apply: bool = False,
    knowledge_id: int | None = None,
    limit: int | None = None,
    batch_size: int = 50,
    sleep_ms: int = 0,
) -> BackfillReport:
    report = BackfillReport()
    service = _build_service(session)
    last_id = 0
    remaining = limit

    while True:
        if remaining is not None and remaining <= 0:
            break
        current_batch_size = batch_size if remaining is None else min(batch_size, remaining)
        result = await session.exec(
            _candidate_stmt(
                knowledge_id=knowledge_id,
                last_id=last_id,
                batch_size=current_batch_size,
            )
        )
        files = list(result.all())
        if not files:
            break

        report.total_files_scanned += len(files)
        for kf in files:
            last_id = max(last_id, int(kf.id))
            if _encoding_first_three_segments(getattr(kf, "file_encoding", None)) is None:
                report.skipped_invalid_encoding += 1
                continue
            if not apply:
                report.would_refresh += 1
                continue
            try:
                candidate_count = await service.refresh_similar_candidates_for_file(int(kf.id))
            except Exception as exc:
                report.errors.append(f"file_id={kf.id}: {exc}")
                continue
            report.refreshed_files += 1
            report.candidates_written += candidate_count
            if candidate_count == 0:
                report.no_candidates += 1

        if remaining is not None:
            remaining -= len(files)
        if sleep_ms > 0:
            await asyncio.sleep(sleep_ms / 1000)

    return report


async def _run(args: argparse.Namespace) -> int:
    if args.batch_size <= 0:
        print("--batch-size must be greater than 0", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit <= 0:
        print("--limit must be greater than 0", file=sys.stderr)
        return 2
    if args.sleep_ms < 0:
        print("--sleep-ms must be >= 0", file=sys.stderr)
        return 2

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            report = await backfill(
                session,
                apply=args.apply,
                knowledge_id=args.knowledge_id,
                limit=args.limit,
                batch_size=args.batch_size,
                sleep_ms=args.sleep_ms,
            )
    print(report)
    if report.errors:
        for error in report.errors[:20]:
            print(f"error: {error}", file=sys.stderr)
        if len(report.errors) > 20:
            print(f"error: ... {len(report.errors) - 20} more", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="Write rows. Default is dry-run.")
    parser.add_argument("--knowledge-id", type=int, default=None, help="Only process one knowledge space.")
    parser.add_argument("--limit", type=int, default=None, help="Scan at most N eligible files.")
    parser.add_argument("--batch-size", type=int, default=50, help="DB batch size. Default: 50.")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Sleep after each batch to reduce CPU pressure.")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
