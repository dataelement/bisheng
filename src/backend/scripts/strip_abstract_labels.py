"""Strip redundant LLM label prefixes from historical KnowledgeFile.abstract values.

Why:
    Default abstract prompts used to ask the model to emit ``【文档类型】`` /
    ``【摘要】`` labels. The portal UI already shows a "文档摘要" heading, so
    those prefixes look duplicated. New parses strip labels in
    ``AbstractTransformer``; this script backfills MySQL rows only.

How to run from ``src/backend``:

    PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py
    PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py --apply --file-id 123
    PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py --apply --limit 500

Default is dry-run. Pass ``--apply`` to write. Scope is MySQL
``knowledgefile.abstract`` only (no ES reindex).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import or_  # noqa: E402
from sqlmodel import col, select  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile  # noqa: E402
from bisheng.knowledge.rag.pipeline.transformer.abstract import (  # noqa: E402
    strip_abstract_labels,
)


@dataclass
class StripReport:
    """Aggregated counters for a strip-abstract-labels backfill run."""

    scanned: int = 0
    would_update: int = 0
    updated: int = 0
    unchanged: int = 0
    samples: list[tuple[int, str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"scanned={self.scanned} would_update={self.would_update} updated={self.updated} unchanged={self.unchanged}"
        )


def abstract_needs_strip(abstract: str | None) -> bool:
    """Return True when abstract contains known redundant label markers."""
    if not abstract:
        return False
    return "【摘要】" in abstract or "【文档类型】" in abstract


def _candidate_stmt(*, file_id: int | None, last_id: int, batch_size: int):
    """Build a paginated query for abstracts that may still carry label prefixes."""
    stmt = (
        select(KnowledgeFile)
        .where(
            KnowledgeFile.abstract.is_not(None),
            KnowledgeFile.abstract != "",
            or_(
                col(KnowledgeFile.abstract).like("%【摘要】%"),
                col(KnowledgeFile.abstract).like("%【文档类型】%"),
            ),
            KnowledgeFile.id > last_id,
        )
        .order_by(KnowledgeFile.id)
        .limit(batch_size)
    )
    if file_id is not None:
        stmt = select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    return stmt


async def strip_labels(
    session: AsyncSession,
    *,
    apply: bool = False,
    file_id: int | None = None,
    limit: int | None = None,
    batch_size: int = 200,
    sample_limit: int = 10,
) -> StripReport:
    """Scan candidate abstracts and optionally persist stripped values."""
    report = StripReport()
    last_id = 0
    remaining = limit

    while True:
        if remaining is not None and remaining <= 0:
            break
        current_batch_size = batch_size if remaining is None else min(batch_size, remaining)
        result = await session.exec(
            _candidate_stmt(
                file_id=file_id,
                last_id=last_id,
                batch_size=current_batch_size,
            )
        )
        files = list(result.all())
        if not files:
            break

        for kf in files:
            last_id = max(last_id, int(kf.id))
            report.scanned += 1
            original = kf.abstract or ""
            cleaned = strip_abstract_labels(original)
            if cleaned == original:
                report.unchanged += 1
                continue

            if len(report.samples) < sample_limit:
                report.samples.append((int(kf.id), original[:120], cleaned[:120]))

            if not apply:
                report.would_update += 1
                continue

            kf.abstract = cleaned
            session.add(kf)
            report.updated += 1

        if apply:
            await session.commit()

        if file_id is not None:
            break
        if remaining is not None:
            remaining -= len(files)

    return report


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.batch_size <= 0:
            print("--batch-size must be greater than 0", file=sys.stderr)
            return 2
        if args.limit is not None and args.limit <= 0:
            print("--limit must be greater than 0", file=sys.stderr)
            return 2
        if args.file_id is not None and args.file_id <= 0:
            print("--file-id must be greater than 0", file=sys.stderr)
            return 2

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                report = await strip_labels(
                    session,
                    apply=args.apply,
                    file_id=args.file_id,
                    limit=args.limit,
                    batch_size=args.batch_size,
                )

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] {report}")
        for file_id, before, after in report.samples:
            print(f"  sample file_id={file_id}")
            print(f"    before: {before!r}")
            print(f"    after:  {after!r}")
        return 0
    finally:
        await close_app_context()


def main() -> int:
    """CLI entry: parse args and run the abstract-label strip backfill."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist stripped abstracts (default is dry-run)",
    )
    parser.add_argument("--file-id", type=int, default=None, help="Only process one KnowledgeFile id")
    parser.add_argument("--limit", type=int, default=None, help="Max candidate rows to scan")
    parser.add_argument("--batch-size", type=int, default=200, help="DB page size (default 200)")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
