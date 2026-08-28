"""Repair the cross-file SimHash-collision incident (false "100% similar" documents).

Background: a still-unexplained defect (diagnosed but not yet root-caused — see
the `[simhash.diag]` logging added to
`bisheng/knowledge/rag/pipeline/transformer/simhash.py`) has left some files
sharing the exact same `knowledgefile.simhash` value despite having genuinely
different content (different `md5`). Downstream, this makes the version-
management similarity feature report those files as "100% similar" to each
other and to anything else that happens to share the same value, even when
the documents are unrelated.

This script:

1. Finds every SimHash value shared by 3+ files with distinct `md5` — the
   signature of the collision (legitimate near-duplicate clustering never
   produces an *exact* match across that many genuinely different documents;
   see the investigation notes for the SQL this mirrors).
2. For every file carrying one of those SimHash values, re-reads the file
   through the same loader the live parse pipeline uses and recomputes its
   SimHash from the actual content — mirroring
   `scripts/init_knowledge_document_versions.py`'s `_extract_file_simhash_sync`.
3. On success, writes only `knowledgefile.simhash` — nothing else (not
   `status`, not `split_rule`, not any other field) changes.
4. On any read/parse error for a file, clears its SimHash to the algorithm's
   own defined empty-text sentinel (`compute_simhash_64_hex("")` == "0"*16)
   instead of leaving it wrong or half-written; `_has_valid_simhash` already
   treats that sentinel as "no SimHash" everywhere it's checked, so the file
   simply drops out of similarity comparisons until it's naturally
   re-parsed.
5. Either way, purges the file's cached similarity-candidate rows
   (`knowledge_file_similarity_candidate`, both as source and as candidate)
   so no stale false match keeps surfacing in the UI after this run. Nothing
   else about the file (status, tags, embeddings, etc.) is touched.

Runs strictly serially (no concurrency) — one file at a time, to avoid
loading etl4lm/OCR — since this repair is expected to be run at whatever
pace the target environment can absorb, not on a deadline.

Usage (dry-run by default; add --apply to write):

    cd src/backend
    PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py
    PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py --apply --limit 50
    PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py --apply --min-distinct-content 5
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import func, select  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile  # noqa: E402
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_similarity_candidate_repository_impl import (  # noqa: E402
    KnowledgeFileSimilarityCandidateRepositoryImpl,
)

_ZERO_SIMHASH = "0" * 16
_DEFAULT_MIN_DISTINCT_CONTENT = 3


@dataclass
class RepairReport:
    flagged_groups: int = 0
    flagged_files: int = 0
    recomputed: int = 0
    cleared_on_error: int = 0
    candidates_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"flagged_groups={self.flagged_groups} flagged_files={self.flagged_files} "
            f"recomputed={self.recomputed} cleared_on_error={self.cleared_on_error} "
            f"candidates_deleted={self.candidates_deleted} errors={len(self.errors)}"
        )


async def _find_flagged_simhash_values(session: AsyncSession, min_distinct_content: int) -> list[str]:
    """SimHash values shared by files with >= min_distinct_content distinct md5.

    Mirrors the investigation query:
        SELECT simhash FROM knowledgefile
        WHERE simhash IS NOT NULL AND simhash != '0'*16
        GROUP BY simhash
        HAVING COUNT(DISTINCT md5) >= :min_distinct_content
    """
    stmt = (
        select(KnowledgeFile.simhash)
        .where(KnowledgeFile.simhash.is_not(None))
        .where(KnowledgeFile.simhash != _ZERO_SIMHASH)
        .group_by(KnowledgeFile.simhash)
        .having(func.count(func.distinct(KnowledgeFile.md5)) >= min_distinct_content)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _find_flagged_files(session: AsyncSession, simhash_values: list[str]) -> list[KnowledgeFile]:
    if not simhash_values:
        return []
    stmt = select(KnowledgeFile).where(KnowledgeFile.simhash.in_(simhash_values)).order_by(KnowledgeFile.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _recompute_file_simhash_sync(kf: KnowledgeFile) -> str:
    """Re-read a file through the parse pipeline's loader and compute its SimHash.

    Deliberately not imported from scripts/init_knowledge_document_versions.py:
    that helper's docstring and idempotent-skip semantics are scoped to
    backfilling files that have *no* SimHash yet, not to overwriting an
    existing (possibly wrong) one. The extraction logic itself is identical —
    same loader selection, same "loader output, pre-split, joined with \\n"
    concatenation — so results from the two scripts remain comparable.
    """
    from bisheng.common.utils.simhash_utils import compute_simhash_64_hex
    from bisheng.knowledge.rag.base_file_pipeline import FileExtensionMap
    from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline

    if not kf.object_name:
        raise ValueError("no object_name")

    pipeline = KnowledgeFilePipeline(invoke_user_id=kf.user_id or 0, db_file=kf, no_summary=True)
    file_process_config = FileExtensionMap.get(pipeline.file_extension)
    if not file_process_config:
        raise ValueError(f"unsupported extension: {pipeline.file_extension}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline.tmp_dir = tmp_dir
        pipeline.prepare_local_file()  # downloads object_name from MinIO into tmp_dir
        loader = getattr(pipeline, file_process_config["loader"])()
        documents = loader.load()

    text = "\n".join((d.page_content or "") for d in documents)
    return compute_simhash_64_hex(text)


async def repair(*, dry_run: bool, limit: int | None, min_distinct_content: int) -> RepairReport:
    report = RepairReport()
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            flagged_values = await _find_flagged_simhash_values(session, min_distinct_content)
            report.flagged_groups = len(flagged_values)

            files = await _find_flagged_files(session, flagged_values)
            if limit is not None:
                files = files[:limit]
            report.flagged_files = len(files)

            candidate_repo = KnowledgeFileSimilarityCandidateRepositoryImpl(session)

            for kf in files:
                old_simhash = kf.simhash
                try:
                    new_simhash = await asyncio.to_thread(_recompute_file_simhash_sync, kf)
                    outcome = "recomputed"
                except Exception as exc:  # noqa: BLE001 — one bad file must not abort the run
                    new_simhash = _ZERO_SIMHASH
                    outcome = "cleared_on_error"
                    report.errors.append(f"file_id={kf.id}: {exc}")

                print(
                    f"file_id={kf.id} knowledge_id={kf.knowledge_id} outcome={outcome} "
                    f"old_simhash={old_simhash} new_simhash={new_simhash}"
                )

                if dry_run:
                    continue

                kf.simhash = new_simhash
                session.add(kf)
                await session.commit()

                deleted = await candidate_repo.delete_by_file_ids([int(kf.id)])
                report.candidates_deleted += deleted

                if outcome == "recomputed":
                    report.recomputed += 1
                else:
                    report.cleared_on_error += 1

    return report


async def _main(*, dry_run: bool, limit: int | None, min_distinct_content: int) -> None:
    report = await repair(dry_run=dry_run, limit=limit, min_distinct_content=min_distinct_content)
    print(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write. Without this flag the script only reports what it would do.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most N flagged files.")
    parser.add_argument(
        "--min-distinct-content", type=int, default=_DEFAULT_MIN_DISTINCT_CONTENT,
        help=(
            "Minimum number of distinct md5 values sharing one SimHash for that "
            f"SimHash to be flagged (default: {_DEFAULT_MIN_DISTINCT_CONTENT})."
        ),
    )
    args = parser.parse_args()

    dry_run = not args.apply
    if dry_run:
        print("Dry-run (no writes). Pass --apply to actually repair.")

    asyncio.run(_main(dry_run=dry_run, limit=args.limit, min_distinct_content=args.min_distinct_content))
    return 0


if __name__ == "__main__":
    sys.exit(main())
