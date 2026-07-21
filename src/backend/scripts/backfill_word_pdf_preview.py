#!/usr/bin/env python3
"""Backfill LibreOffice-rendered PDF previews for existing Word files.

New Word uploads render a PDF preview during parse (``BishengWordLoader._build_pdf_preview``
→ ``ExtraFileTransformer._upload_pdf_preview``): the .docx preview is converted to PDF,
stored at ``preview/{file_id}.pdf``, and recorded in ``user_metadata`` as
``pdf_preview_object_name`` (+ ``pdf_preview_source_md5``). ``get_file_share_detail`` then
serves it as ``pdf_preview_url`` — the frontend prefers it because LibreOffice lays the
page out the way Word does, unlike the HTML converted from the .docx in the browser
(which drops e-seals and shape positioning). The unified PDF-artifact worker also reuses
this PDF when its md5 matches, so no double conversion.

Files parsed before this feature have no ``pdf_preview_object_name``, so their preview
falls back to the .docx. This script replays the same steps offline for those files:

    1. Read the preview .docx (``preview/{file_id}.docx``; the original .doc/.docx when
       that is missing) from MinIO.
    2. Convert it to PDF with LibreOffice (``convert_docx_to_pdf``).
    3. Upload the PDF to ``preview/{file_id}.pdf``.
    4. Set ``pdf_preview_object_name`` + ``pdf_preview_source_md5`` on the file.

Idempotent: files whose ``pdf_preview_source_md5`` already matches the current md5 are
skipped. Conversion runs serially — a preview is best-effort, and one failure logs and
moves on rather than aborting the run.

Default is dry-run (selection report only). Pass ``--apply`` to convert and write.

Usage (run from src/backend/):
    PYTHONPATH=./ .venv/bin/python scripts/backfill_word_pdf_preview.py            # dry-run
    PYTHONPATH=./ .venv/bin/python scripts/backfill_word_pdf_preview.py --apply
    bash scripts/backfill_word_pdf_preview.sh --apply --limit 50

    # Docker / production container (WORKDIR /app, system python):
    PYTHONPATH=./ python scripts/backfill_word_pdf_preview.py --apply --space-id 202
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402
from sqlmodel import select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils  # noqa: E402
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (  # noqa: E402
    convert_docx_to_pdf,
)

# Extensions previewed via a .docx→PDF rendition (mirrors
# KnowledgeUtils.get_knowledge_preview_file_object_name).
WORD_EXTENSIONS = {"doc", "docx", "wps"}
DEFAULT_SCAN_BATCH_SIZE = 500
DEFAULT_CONVERSION_TIMEOUT = 120


@dataclass(frozen=True)
class BackfillResult:
    file_id: int
    space_id: int | None
    file_name: str
    success: bool = False
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""


@dataclass
class RunReport:
    selected: int = 0
    processed: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[BackfillResult] = field(default_factory=list)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="convert and write; default is dry-run")
    parser.add_argument(
        "--space-id",
        dest="space_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="restrict to this knowledge-space ID; repeatable",
    )
    parser.add_argument(
        "--file-id",
        dest="file_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="restrict to this knowledge-file ID; repeatable",
    )
    parser.add_argument("--limit", type=_positive_int, default=None, help="max files to process")
    parser.add_argument(
        "--scan-batch-size",
        type=_positive_int,
        default=DEFAULT_SCAN_BATCH_SIZE,
        help=f"rows per keyset scan batch; default: {DEFAULT_SCAN_BATCH_SIZE}",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_int,
        default=DEFAULT_CONVERSION_TIMEOUT,
        help=f"LibreOffice conversion timeout in seconds; default: {DEFAULT_CONVERSION_TIMEOUT}",
    )
    parser.add_argument("--force", action="store_true", help="re-render even when the md5 already matches")
    return parser.parse_args(argv)


def _file_extension(file_name: str) -> str:
    return (file_name or "").rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""


def _needs_backfill(file: KnowledgeFile, *, force: bool) -> bool:
    """A file needs backfill unless it already has a PDF preview for its current md5."""
    if force:
        return True
    metadata = file.user_metadata or {}
    object_name = metadata.get("pdf_preview_object_name")
    source_md5 = metadata.get("pdf_preview_source_md5")
    # Missing preview, or the recorded preview is stale relative to the file's current
    # bytes — same freshness rule the artifact reuse hook applies.
    return not object_name or not source_md5 or source_md5 != file.md5


def scan_candidates(
    *,
    space_ids: Sequence[int],
    file_ids: Sequence[int],
    scan_batch_size: int,
    limit: int | None,
    force: bool,
) -> list[KnowledgeFile]:
    """Keyset-scan SUCCESS Word files that still lack a fresh PDF preview."""
    selected: list[KnowledgeFile] = []
    last_id = 0
    space_id_set = {int(sid) for sid in space_ids}
    file_id_set = {int(fid) for fid in file_ids}

    with bypass_tenant_filter(), get_sync_db_session() as session:
        while True:
            statement = (
                select(KnowledgeFile)
                .where(
                    KnowledgeFile.id > last_id,
                    KnowledgeFile.file_type == FileType.FILE.value,
                    KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                )
                .order_by(KnowledgeFile.id)
                .limit(scan_batch_size)
            )
            if space_id_set:
                statement = statement.where(KnowledgeFile.knowledge_id.in_(space_id_set))
            if file_id_set:
                statement = statement.where(KnowledgeFile.id.in_(file_id_set))
            batch = session.exec(statement).all()
            if not batch:
                break
            last_id = int(batch[-1].id)
            for file in batch:
                if _file_extension(file.file_name) not in WORD_EXTENSIONS:
                    continue
                if not _needs_backfill(file, force=force):
                    continue
                selected.append(file)
                if limit is not None and len(selected) >= limit:
                    return selected
    return selected


def _load_source_docx(minio_client, file: KnowledgeFile) -> tuple[str, str] | None:
    """Return (object_name, suffix) of the .docx (or .doc) to convert, or None.

    Prefers the parse-produced preview .docx; falls back to the original file, which
    convert_docx_to_pdf also accepts for .doc/.docx.
    """
    preview_object = KnowledgeUtils.resolve_preview_object_name(
        file_id=file.id,
        file_name=file.file_name,
        preview_file_object_name=file.preview_file_object_name,
    )
    if preview_object and minio_client.object_exists_sync(object_name=preview_object):
        return preview_object, ".docx"

    source_object = KnowledgeUtils.resolve_source_object_name(file.id, file.file_name, file.object_name)
    ext = _file_extension(file.file_name)
    if source_object and ext in {"doc", "docx"} and minio_client.object_exists_sync(object_name=source_object):
        return source_object, f".{ext}"
    return None


def backfill_one(file: KnowledgeFile, *, timeout: int) -> BackfillResult:
    minio_client = get_minio_storage_sync()
    space_id = int(file.knowledge_id) if file.knowledge_id is not None else None

    source = _load_source_docx(minio_client, file)
    if source is None:
        return BackfillResult(
            file_id=int(file.id),
            space_id=space_id,
            file_name=file.file_name,
            skipped=True,
            skip_reason="no preview .docx or convertible source object in MinIO",
        )
    source_object, suffix = source

    try:
        content = minio_client.get_object_sync(object_name=source_object)
        if not content:
            return BackfillResult(
                file_id=int(file.id),
                space_id=space_id,
                file_name=file.file_name,
                skipped=True,
                skip_reason=f"empty source object {source_object}",
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            local_docx = os.path.join(tmp_dir, f"{file.id}{suffix}")
            with open(local_docx, "wb") as handle:
                handle.write(content)

            pdf_path = convert_docx_to_pdf(input_path=local_docx, output_dir=tmp_dir, timeout=timeout)
            if not pdf_path or not os.path.exists(pdf_path):
                return BackfillResult(
                    file_id=int(file.id),
                    space_id=space_id,
                    file_name=file.file_name,
                    success=False,
                    error="conversion produced no PDF",
                )

            pdf_object_name = KnowledgeUtils.get_knowledge_pdf_preview_file_object_name(file.id)
            minio_client.put_object_sync(object_name=pdf_object_name, file=pdf_path)

        # Persist the pointer only after the object is safely stored, mirroring
        # ExtraFileTransformer._upload_pdf_preview so preview + artifact reuse agree.
        with bypass_tenant_filter():
            fresh = KnowledgeFileDao.query_by_id_sync(int(file.id))
            if fresh is None:
                return BackfillResult(
                    file_id=int(file.id),
                    space_id=space_id,
                    file_name=file.file_name,
                    skipped=True,
                    skip_reason="file disappeared during backfill",
                )
            fresh.user_metadata = {
                **(fresh.user_metadata or {}),
                "pdf_preview_object_name": pdf_object_name,
                "pdf_preview_source_md5": fresh.md5,
            }
            KnowledgeFileDao.update(fresh)

        return BackfillResult(
            file_id=int(file.id),
            space_id=space_id,
            file_name=file.file_name,
            success=True,
        )
    except Exception as exc:
        return BackfillResult(
            file_id=int(file.id),
            space_id=space_id,
            file_name=file.file_name,
            success=False,
            error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
        )


def print_selection(candidates: Sequence[KnowledgeFile]) -> None:
    print(f"Selected {len(candidates)} Word file(s) needing a PDF preview.")
    for file in candidates[:20]:
        print(f"  file_id={file.id} space_id={file.knowledge_id} name={file.file_name}")
    if len(candidates) > 20:
        print(f"  ... and {len(candidates) - 20} more")


def run(args: argparse.Namespace) -> int:
    candidates = scan_candidates(
        space_ids=args.space_ids,
        file_ids=args.file_ids,
        scan_batch_size=args.scan_batch_size,
        limit=args.limit,
        force=args.force,
    )
    report = RunReport(selected=len(candidates))
    print_selection(candidates)

    if not args.apply:
        print("Dry-run only. Pass --apply to convert and write.")
        return 0
    if not candidates:
        print("Nothing to backfill.")
        return 0

    for index, file in enumerate(candidates, start=1):
        result = backfill_one(file, timeout=args.timeout)
        report.results.append(result)
        report.processed += 1
        prefix = f"[{index}/{len(candidates)}]"
        if result.skipped:
            report.skipped += 1
            print(f"{prefix} [SKIP] file_id={result.file_id} reason={result.skip_reason}")
        elif result.success:
            report.success += 1
            print(f"{prefix} [OK] file_id={result.file_id} space_id={result.space_id} name={result.file_name}")
        else:
            report.failed += 1
            print(f"{prefix} [FAIL] file_id={result.file_id} error={result.error}")

    print(
        "Run summary: "
        f"selected={report.selected} processed={report.processed} "
        f"success={report.success} skipped={report.skipped} failed={report.failed}"
    )
    return 2 if report.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except Exception:
        logger.exception("backfill_word_pdf_preview failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
