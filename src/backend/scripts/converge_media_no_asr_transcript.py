#!/usr/bin/env python3
"""Converge media knowledge files whose "transcript" is the raw ASR JSON envelope.

Why this exists: before the fix in
``KnowledgeMediaTranscriptionService._call_aliyun_asr``, an audio/video file
whose ASR call returned HTTP 200 but no recognized sentences (``output: null``)
had the *stringified response object* stored as its transcript, e.g.::

    {"status_code": 200, "request_id": "...", "code": "", "message": "", "output": null, "usage": null}

Such files were marked SUCCESS, are clickable in the knowledge space UI, and
show that JSON garbage as recognized text. The desired state (matching every
other unrecognizable-audio case) is FAILED with error code 10956
("未检测到可识别音频"), which the client renders as a 失败 badge with tooltip and
makes the row non-clickable.

This script finds those rows and converges them:

1. Select ``knowledgefile`` rows with a media extension and status SUCCESS.
2. Download each file's transcript preview (``preview/{id}.md``) from MinIO and
   extract the 入库文本 section.
3. If the ingested text is empty or is the raw ASR JSON envelope, the row is a
   candidate: delete its Milvus/ES vectors (source file in MinIO is kept) and
   set status=FAILED with the 10956 error json in ``remark``.

Dry-run is the default; nothing is written without ``--apply``.

Run from ``src/backend/`` with the same config the live service uses::

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/converge_media_no_asr_transcript.py                 # dry-run
    python scripts/converge_media_no_asr_transcript.py --apply         # write
    python scripts/converge_media_no_asr_transcript.py --knowledge-id 123
    python scripts/converge_media_no_asr_transcript.py --file-id 456 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402
from sqlmodel import col, or_, select  # noqa: E402

from bisheng.common.errcode.knowledge import (  # noqa: E402
    KnowledgeMediaNoRecognizableAudioError,
)
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    close_app_context,
    initialize_app_context,
)
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database.manager import get_sync_db_session  # noqa: E402
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils  # noqa: E402

MEDIA_EXTENSIONS = (
    "mp3", "wav", "m4a", "aac", "flac", "ogg",
    "mp4", "mov", "avi", "mkv", "webm",
)

# The legacy bug stored str(RecognitionResult) — a JSON envelope carrying
# status_code / request_id and a null/empty output — as the transcript text.
_ENVELOPE_PATTERN = re.compile(r'^\{"status_code":\s*\d+,\s*"request_id"')


@dataclass
class ConvergeReport:
    media_success_files: int = 0
    converged: list[int] = field(default_factory=list)
    healthy: int = 0
    preview_missing: list[int] = field(default_factory=list)
    errors: list[int] = field(default_factory=list)


def _extract_ingested_text(markdown: str) -> str:
    """Return the 入库文本 section body (or the whole document as fallback)."""
    match = re.search(r"##\s*入库文本\s*\n(.*?)(?:\n##\s|\Z)", markdown, re.DOTALL)
    body = match.group(1) if match else markdown
    return body.strip()


def _is_garbage_transcript(text: str) -> bool:
    if not text:
        return True
    if _ENVELOPE_PATTERN.match(text):
        return True
    # Defensive: a transcript that parses as a JSON object with a status_code
    # key is the envelope regardless of key order.
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return False
        return isinstance(parsed, dict) and "status_code" in parsed and "request_id" in parsed
    return False


def _select_candidates(knowledge_id: int | None, file_id: int | None) -> list[KnowledgeFile]:
    name_filters = [col(KnowledgeFile.file_name).ilike(f"%.{ext}") for ext in MEDIA_EXTENSIONS]
    statement = select(KnowledgeFile).where(
        KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
        or_(*name_filters),
    )
    if knowledge_id is not None:
        statement = statement.where(KnowledgeFile.knowledge_id == knowledge_id)
    if file_id is not None:
        statement = statement.where(KnowledgeFile.id == file_id)
    with get_sync_db_session() as session:
        return list(session.exec(statement).all())


def _converge_file(db_file: KnowledgeFile, preview_object_name: str, minio_client) -> None:
    # Import here: knowledge_imp pulls in the full RAG stack, keep startup lean.
    from bisheng.api.services.knowledge_imp import delete_knowledge_file_vectors

    # Remove Milvus/ES entries so the garbage text can never be recalled;
    # the source media object in MinIO is kept (clear_minio=False) so the
    # file can still be re-parsed or downloaded.
    delete_knowledge_file_vectors([db_file.id], clear_minio=False)
    KnowledgeFileDao.update_file_status(
        [db_file.id],
        KnowledgeFileStatus.FAILED,
        KnowledgeMediaNoRecognizableAudioError().to_json_str(),
    )
    # Drop the garbage transcript preview too, so stale direct-preview URLs
    # can't render the JSON envelope; a later re-parse re-uploads it.
    minio_client.remove_object_sync(
        bucket_name=minio_client.bucket, object_name=preview_object_name
    )


def run(*, apply: bool, knowledge_id: int | None, file_id: int | None) -> ConvergeReport:
    report = ConvergeReport()
    minio_client = get_minio_storage_sync()

    with bypass_tenant_filter():
        candidates = _select_candidates(knowledge_id, file_id)
        report.media_success_files = len(candidates)
        logger.info("media files with status SUCCESS: {}", len(candidates))

        for db_file in candidates:
            preview_object_name = (
                db_file.preview_file_object_name
                or KnowledgeUtils.get_knowledge_preview_file_object_name(
                    file_id=db_file.id, file_name=db_file.file_name
                )
            )
            try:
                content = (
                    minio_client.get_object_sync(object_name=preview_object_name)
                    if preview_object_name
                    else None
                )
            except Exception:
                logger.exception(
                    "file_id={} preview download failed ({})", db_file.id, preview_object_name
                )
                report.errors.append(db_file.id)
                continue

            if not content:
                # SUCCESS media file without a transcript preview — can't judge
                # its ingested text, so it is reported but never touched.
                logger.warning(
                    "file_id={} name={} has no transcript preview; skipped",
                    db_file.id,
                    db_file.file_name,
                )
                report.preview_missing.append(db_file.id)
                continue

            ingested_text = _extract_ingested_text(content.decode("utf-8", errors="replace"))
            if not _is_garbage_transcript(ingested_text):
                report.healthy += 1
                continue

            logger.info(
                "{} file_id={} knowledge_id={} name={} transcript={!r}",
                "CONVERGING" if apply else "WOULD CONVERGE",
                db_file.id,
                db_file.knowledge_id,
                db_file.file_name,
                ingested_text[:120],
            )
            if apply:
                try:
                    _converge_file(db_file, preview_object_name, minio_client)
                except Exception:
                    logger.exception("file_id={} converge failed", db_file.id)
                    report.errors.append(db_file.id)
                    continue
            report.converged.append(db_file.id)

    return report


async def _main(args: argparse.Namespace) -> int:
    await initialize_app_context(config=settings)
    try:
        report = run(apply=args.apply, knowledge_id=args.knowledge_id, file_id=args.file_id)
    finally:
        await close_app_context()

    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info(
        "[{}] media SUCCESS files scanned: {} | healthy: {} | converged to FAILED(10956): {} {} | "
        "no preview (skipped): {} {} | errors: {} {}",
        mode,
        report.media_success_files,
        report.healthy,
        len(report.converged),
        report.converged,
        len(report.preview_missing),
        report.preview_missing,
        len(report.errors),
        report.errors,
    )
    return 1 if report.errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    parser.add_argument("--knowledge-id", type=int, default=None, help="limit to one knowledge base / space")
    parser.add_argument("--file-id", type=int, default=None, help="limit to one knowledge file id")
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
