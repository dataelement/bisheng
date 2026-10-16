"""Pick a run's deliverable files and store them as chat attachments (F078 design decision 6).

Selection reuses task mode's rule (``select_deliverables``): files this run
created or changed in ``output/`` win; when there are none, files this run
created anywhere else count. Skills, inputs, scratch files and spilled tool
results never count.

Unlike task mode, a file whose bytes contradict its extension is kept and
flagged (spec AC-33) instead of dropped.

Each file is copied to an attachment object with a ``file_id`` and an
``object_name``. Deleting the session then removes it through the existing
attachment clean-up, and the download endpoint can re-sign it at any time.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

from bisheng.linsight.domain.utils import deliverable_format_error, read_file_directory, select_deliverables


@dataclass(frozen=True)
class DeliverableTarget:
    """Where a run's deliverables are stored and how they are addressed."""

    object_dir: str
    use_tmp_bucket: bool
    url_for: Callable[[str], str]


async def acollect_deliverables(
    minio,
    file_dir: str,
    baseline: dict[str, str],
    target: DeliverableTarget,
) -> list[dict]:
    """Upload the run's deliverables and return their attachment descriptors.

    The descriptor keys are ``file_id``, ``file_name``, ``object_name``,
    ``bucket``, ``size``, ``file_url`` and, only for a file that fails the format
    check, ``format_error``. A file that cannot be uploaded is logged and left out.
    """
    file_details = await read_file_directory(file_dir)
    selected = select_deliverables(file_details, baseline)
    if not selected:
        return []

    bucket = minio.tmp_bucket if target.use_tmp_bucket else minio.bucket

    async def _store(info: dict) -> dict | None:
        file_id = uuid.uuid4().hex
        # ASCII-only object key: non-ASCII keys break presigned signatures on some
        # S3-compatible backends. The display name stays in ``file_name``.
        ext = os.path.splitext(info["file_name"])[1]
        object_name = f"{target.object_dir.rstrip('/')}/{file_id}{ext}"
        try:
            await minio.put_object(bucket_name=bucket, object_name=object_name, file=info["file_path"])
        except Exception:
            logger.exception("act=agent_deliverable_upload_failed file={}", info.get("rel_path"))
            return None
        descriptor = {
            "file_id": file_id,
            "file_name": info["file_name"],
            "object_name": object_name,
            "bucket": "tmp" if target.use_tmp_bucket else "public",
            "size": os.path.getsize(info["file_path"]),
            "file_url": target.url_for(file_id),
        }
        reason = deliverable_format_error(info)
        if reason:
            logger.warning("act=agent_deliverable_format_error file={} reason={}", info.get("rel_path"), reason)
            descriptor["format_error"] = reason
        return descriptor

    results = await asyncio.gather(*(_store(info) for info in selected))
    return [descriptor for descriptor in results if descriptor is not None]
