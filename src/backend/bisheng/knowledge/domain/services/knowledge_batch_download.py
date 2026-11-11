"""The original ZIP/CHANNEL export, with explicit per-file transport failures."""

import os
import tempfile
import zipfile
from pathlib import Path

from loguru import logger

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.repositories.knowledge_batch_repository import ancestors


def component(name):
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("invalid archive path component")
    return name


async def export_batch(*, scope, files, object_key, reuse=False, storage=None):
    storage = storage or get_minio_storage_sync()
    failures = []
    if not reuse:
        names = {row["id"]: row["file_name"] for row in scope["files"] if row["file_type"] == 0}
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for row in files:
                response = None
                target = None
                owned = False
                try:
                    parts = [component(names.get(ident, str(ident))) for ident in ancestors(row)]
                    parent = base.joinpath(*parts)
                    parent.mkdir(parents=True, exist_ok=True)
                    name = component(row["file_name"])
                    target = parent / name
                    if row["file_type"] == 0:
                        target.mkdir(exist_ok=True)
                        continue
                    source = row["object_name"]
                    if row["file_source"] == "channel" and row["preview_file_object_name"]:
                        source = row["preview_file_object_name"]
                        target = parent / (os.path.splitext(name)[0] + ".html")
                    if not source:
                        raise ValueError("original download source unavailable")
                    if target.exists():
                        raise ValueError("archive path collision")
                    owned = True
                    response = storage.download_object_sync(object_name=source)
                    with target.open("wb") as output:
                        for block in response.stream(65536):
                            output.write(block)
                except Exception:
                    logger.exception("batch download failed file_id={}", row["id"])
                    failures.append(row["id"])
                    if owned and target is not None and target.is_file():
                        target.unlink()
                finally:
                    if response is not None:
                        try:
                            response.close()
                            response.release_conn()
                        except Exception:
                            # The downloaded bytes are complete; connection cleanup
                            # is best effort and cannot change the archive content.
                            logger.exception("batch download connection cleanup failed file_id={}", row["id"])
            archive = base / "archive.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
                for directory, folders, names in os.walk(base):
                    for name in folders + names:
                        target = Path(directory) / name
                        if target != archive:
                            output.write(target, target.relative_to(base))
            try:
                await storage.put_object_tmp(object_key, archive, content_type="application/zip")
            except Exception:
                logger.exception("batch archive upload acknowledgement unknown")
                return {"url": None, "failed_file_ids": [row["id"] for row in files]}
    try:
        url = await storage.get_share_link(object_key, bucket=storage.tmp_bucket, clear_host=True, expire_days=7)
    except Exception:
        logger.exception("batch archive URL unavailable")
        return {"url": None, "failed_file_ids": [row["id"] for row in files]}
    return {"url": url, "failed_file_ids": failures}
