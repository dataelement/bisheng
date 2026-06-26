"""One-shot historical-data init for the file version management feature.

For every existing knowledge-space file (excluding QA/NORMAL/PRIVATE bases and folders),
create a KnowledgeDocument and a V1 KnowledgeDocumentVersion with V1 set as the primary
version — regardless of parse status. Failed-parse files have no indexed chunks so they
naturally don't surface in retrieval; the UI hides version-management entries for non-SUCCESS
files via `knowledgefile.status`.

In addition, for every successfully-parsed file that has no SimHash yet, re-read the file
through the same loader the parse pipeline uses and compute its 64-bit content SimHash, then
persist it to `knowledgefile.simhash`. This is what makes historical files comparable in the
version-management similarity checks (recommendations + manual link), exactly like newly
uploaded files (which get their SimHash at parse time via SimHashTransformer). Pass
``--skip-simhash`` to only backfill the version chain.

Usage:
    uv run python -m scripts.init_knowledge_document_versions [--dry-run] [--limit N] [--skip-simhash]
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

# Constants — mirror the enum values without coupling the script to enum imports.
# KnowledgeTypeEnum: 0=NORMAL, 1=QA, 2=PRIVATE, 3=SPACE — version management is for SPACE only.
KNOWLEDGE_TYPE_SPACE = 3
FILE_TYPE_FILE = 1  # 0=DIR, 1=FILE
FILE_STATUS_SUCCESS = 2  # KnowledgeFileStatus.SUCCESS
_ZERO_SIMHASH = "0" * 16


@dataclass
class BackfillReport:
    total_files_scanned: int = 0
    documents_created: int = 0
    versions_created: int = 0
    skipped_non_space: int = 0
    skipped_folder: int = 0
    skipped_already_done: int = 0
    simhash_computed: int = 0
    simhash_skipped_has_value: int = 0
    simhash_skipped_not_success: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"total_files_scanned={self.total_files_scanned} "
            f"documents_created={self.documents_created} "
            f"versions_created={self.versions_created} "
            f"skipped_non_space={self.skipped_non_space} "
            f"skipped_folder={self.skipped_folder} "
            f"skipped_already_done={self.skipped_already_done} "
            f"simhash_computed={self.simhash_computed} "
            f"simhash_skipped_has_value={self.simhash_skipped_has_value} "
            f"simhash_skipped_not_success={self.simhash_skipped_not_success} "
            f"errors={len(self.errors)}"
        )


async def _get_space_knowledge_ids(session: AsyncSession) -> set[int]:
    """Return knowledge IDs whose type is SPACE — the only candidates for versioning."""
    stmt = select(Knowledge.id).where(Knowledge.type == KNOWLEDGE_TYPE_SPACE)
    result = await session.execute(stmt)
    return {row for row in result.scalars().all()}


async def _already_initialized_file_ids(session: AsyncSession) -> set[int]:
    stmt = select(KnowledgeDocumentVersion.knowledge_file_id)
    result = await session.execute(stmt)
    return {row for row in result.scalars().all()}


def _extract_file_simhash_sync(kf: KnowledgeFile) -> Optional[str]:
    """Re-read a parsed file through the parse pipeline's loader and compute its SimHash.

    Mirrors SimHashTransformer: the transformer runs *before* the splitter, so it sees the
    loader's documents (pre-split). We therefore reuse the exact same loader selection +
    loader implementation, concatenate the document page_content with "\\n", and hash it —
    producing a fingerprint consistent with files parsed live. Heavy loaders (PDF/image OCR,
    etc.) re-run here; this is a one-shot backfill meant to run in the parse-worker
    environment where those services are reachable.

    Returns the 16-char hex SimHash, or None when the file cannot be read (no object,
    unsupported extension). Empty text yields the zero hash ("0" * 16), same as live parse.
    """
    import tempfile

    from bisheng.common.utils.simhash_utils import compute_simhash_64_hex
    from bisheng.knowledge.rag.base_file_pipeline import FileExtensionMap
    from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline

    if not kf.object_name:
        return None

    pipeline = KnowledgeFilePipeline(invoke_user_id=kf.user_id or 0, db_file=kf, no_summary=True)
    file_process_config = FileExtensionMap.get(pipeline.file_extension)
    if not file_process_config:
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        pipeline.tmp_dir = tmp_dir
        pipeline.prepare_local_file()  # downloads object_name from MinIO into tmp_dir
        loader = getattr(pipeline, file_process_config["loader"])()
        documents = loader.load()

    text = "\n".join((d.page_content or "") for d in documents)
    return compute_simhash_64_hex(text)


async def _extract_file_simhash(kf: KnowledgeFile) -> Optional[str]:
    """Async wrapper so the blocking loader runs off the event loop."""
    return await asyncio.to_thread(_extract_file_simhash_sync, kf)


async def backfill(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
    compute_simhash: bool = True,
) -> BackfillReport:
    """Initialize one logical document + V1 per existing knowledge-space file, and backfill
    SimHash for successfully-parsed files that don't have one yet.

    Idempotent: skips files that already have a version row, and skips SimHash for files that
    already have a (non-empty) value.
    """
    report = BackfillReport()

    space_ids = await _get_space_knowledge_ids(session)
    already_done = await _already_initialized_file_ids(session)

    stmt = select(KnowledgeFile)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    files = list(result.scalars().all())
    report.total_files_scanned = len(files)

    for kf in files:
        if kf.knowledge_id not in space_ids:
            report.skipped_non_space += 1
            continue
        if kf.file_type != FILE_TYPE_FILE:
            report.skipped_folder += 1
            continue

        # ── Version chain (document + V1) ──────────────────────────────────
        if kf.id in already_done:
            report.skipped_already_done += 1
        else:
            report.documents_created += 1
            report.versions_created += 1
            if not dry_run:
                try:
                    doc = KnowledgeDocument(
                        knowledge_id=kf.knowledge_id,
                        file_level_path=kf.file_level_path,
                        level=kf.level or 0,
                    )
                    session.add(doc)
                    await session.flush()  # populates doc.id without committing

                    # Historical V1 is always primary regardless of parse status.
                    # (Failed files have no indexed chunks anyway, so they won't surface in
                    #  retrieval; the UI hides version-management entries for non-SUCCESS files
                    #  via knowledgefile.status.)
                    version = KnowledgeDocumentVersion(
                        document_id=doc.id,
                        knowledge_file_id=kf.id,
                        version_no=1,
                        is_primary=True,
                    )
                    session.add(version)
                    await session.flush()  # populates version.id without committing

                    doc.primary_version_id = version.id
                    session.add(doc)

                    await session.commit()  # atomic: all-or-nothing for this file
                except Exception as exc:  # pragma: no cover
                    await session.rollback()
                    report.errors.append(f"file_id={kf.id} doc: {exc}")

        # ── SimHash backfill ───────────────────────────────────────────────
        if compute_simhash:
            await _backfill_simhash_for_file(session, kf, report, dry_run=dry_run)

    return report


async def _backfill_simhash_for_file(
    session: AsyncSession,
    kf: KnowledgeFile,
    report: BackfillReport,
    *,
    dry_run: bool,
) -> None:
    """Compute and persist SimHash for one file when eligible.

    Eligible = parsed SUCCESS and has no SimHash yet. Idempotent: a file that already has a
    value (including a previously-computed zero hash for empty content) is left untouched.
    """
    if kf.status != FILE_STATUS_SUCCESS:
        report.simhash_skipped_not_success += 1
        return
    if kf.simhash:
        report.simhash_skipped_has_value += 1
        return
    if not kf.object_name:
        # SUCCESS but nothing stored to read — abnormal; record and move on.
        report.errors.append(f"file_id={kf.id} simhash: no object_name")
        return

    if dry_run:
        # Count it as work that would be done, but don't read files / write.
        report.simhash_computed += 1
        return

    try:
        simhash = await _extract_file_simhash(kf)
    except Exception as exc:  # noqa: BLE001 — one bad file must not abort the whole run
        report.errors.append(f"file_id={kf.id} simhash: {exc}")
        return

    if not simhash:
        # Unreadable / unsupported — leave NULL so a later run can retry.
        report.errors.append(f"file_id={kf.id} simhash: no content extracted")
        return

    try:
        kf.simhash = simhash
        session.add(kf)
        await session.commit()
        report.simhash_computed += 1
    except Exception as exc:  # pragma: no cover
        await session.rollback()
        report.errors.append(f"file_id={kf.id} simhash-write: {exc}")


async def _main(dry_run: bool, limit: Optional[int], compute_simhash: bool) -> None:
    # Cross-tenant initialization: bypass auto tenant filter so we can scan
    # every tenant's Knowledge / KnowledgeFile rows. KnowledgeDocument and
    # KnowledgeDocumentVersion have no tenant_id column, so writes are
    # unaffected by the bypass.
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            report = await backfill(
                session, dry_run=dry_run, limit=limit, compute_simhash=compute_simhash,
            )
            print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill knowledge_document / knowledge_document_version and SimHash for existing files."
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute the plan without writing.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files.")
    parser.add_argument(
        "--skip-simhash", action="store_true",
        help="Only backfill the version chain; do not read files to compute SimHash.",
    )
    args = parser.parse_args()
    asyncio.run(_main(dry_run=args.dry_run, limit=args.limit, compute_simhash=not args.skip_simhash))
