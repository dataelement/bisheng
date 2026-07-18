"""One-shot historical-data init for the file version management feature.

For every existing knowledge-space file (excluding QA/NORMAL/PRIVATE bases and folders),
create a KnowledgeDocument and a V1 KnowledgeDocumentVersion with V1 set as the primary
version — regardless of parse status. Failed-parse files have no indexed chunks so they
naturally don't surface in retrieval; the UI hides version-management entries for non-SUCCESS
files via `knowledgefile.status`. SimHash is NOT computed for historical data (only on
newly uploaded files at parse time).

Usage:
    uv run python -m scripts.init_knowledge_document_versions [--dry-run] [--limit N]
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


@dataclass
class BackfillReport:
    total_files_scanned: int = 0
    documents_created: int = 0
    versions_created: int = 0
    skipped_non_space: int = 0
    skipped_folder: int = 0
    skipped_already_done: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"total_files_scanned={self.total_files_scanned} "
            f"documents_created={self.documents_created} "
            f"versions_created={self.versions_created} "
            f"skipped_non_space={self.skipped_non_space} "
            f"skipped_folder={self.skipped_folder} "
            f"skipped_already_done={self.skipped_already_done} "
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


async def backfill(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> BackfillReport:
    """Initialize one logical document + V1 per existing knowledge-space file.

    Idempotent: skips files that already have a version row.
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
        if kf.id in already_done:
            report.skipped_already_done += 1
            continue

        report.documents_created += 1
        report.versions_created += 1

        if dry_run:
            continue

        try:
            doc = KnowledgeDocument(
                knowledge_id=kf.knowledge_id,
                file_level_path=kf.file_level_path,
                level=kf.level or 0,
            )
            session.add(doc)
            await session.flush()  # populates doc.id without committing

            # Historical V1 is always primary regardless of parse status.
            # (Failed files have no indexed chunks anyway, so they won't surface in retrieval;
            #  the UI hides version-management entries for non-SUCCESS files via knowledgefile.status.)
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
            report.errors.append(f"file_id={kf.id}: {exc}")

    return report


async def _main(dry_run: bool, limit: Optional[int]) -> None:
    # Cross-tenant initialization: bypass auto tenant filter so we can scan
    # every tenant's Knowledge / KnowledgeFile rows. KnowledgeDocument and
    # KnowledgeDocumentVersion have no tenant_id column, so writes are
    # unaffected by the bypass.
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            report = await backfill(session, dry_run=dry_run, limit=limit)
            print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill knowledge_document / knowledge_document_version for existing files."
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute the plan without writing.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N files.")
    args = parser.parse_args()
    asyncio.run(_main(dry_run=args.dry_run, limit=args.limit))
