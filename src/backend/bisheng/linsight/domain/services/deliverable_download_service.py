"""Server side of the task-mode "save as" downloads that need the run's workspace.

A markdown deliverable references workspace images by path. The run's workspace
is persisted in object storage under ``workspace/<svid>/`` (see
``WorkspaceBackend._object_key``), so a download long after the run can still
resolve those images — this module reads them for the zip bundle and for the
pdf / docx conversion.
"""

from __future__ import annotations

import asyncio
import posixpath

from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services.md_image_refs import FetchFiles
from bisheng.linsight.domain.services.workspace_backend import WORKSPACE_PREFIX


def find_deliverable(version: LinsightSessionVersion, file_key: str, bucket: str) -> dict | None:
    """The final_files entry of this version stored at object ``file_key``; None if it isn't one."""
    for f in (version.output_result or {}).get("final_files") or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get("file_url") or "").lstrip("/")
        if key.startswith(bucket + "/"):
            key = key[len(bucket) + 1 :]
        if key == file_key:
            return f
    return None


def deliverable_workspace_path(version: LinsightSessionVersion, file_info: dict) -> str | None:
    """Workspace-relative path of a deliverable (``output/report.md``).

    ``final_files`` records the run's local path, ``<cache>/linsight/<svid[:8]>/<rel>``
    (``LinsightWorkflowTask._init_file_directory``); the part after that run
    directory is the workspace path.
    """
    if file_info.get("rel_path"):
        return str(file_info["rel_path"]).lstrip("/")
    marker = f"/linsight/{version.id[:8]}/"
    file_path = str(file_info.get("file_path") or "").replace("\\", "/")
    if marker not in file_path:
        return None
    rel = posixpath.normpath(file_path.split(marker, 1)[1])
    return None if rel.startswith("..") else rel


def workspace_fetcher(session_version_id: str) -> FetchFiles:
    """Read files from a run's persisted workspace; missing objects are left out."""

    async def _fetch(paths: list[str]) -> dict[str, bytes]:
        minio = await get_minio_storage()

        async def _one(path: str) -> bytes | None:
            try:
                return await minio.get_object(
                    bucket_name=minio.bucket, object_name=f"{WORKSPACE_PREFIX}/{session_version_id}/{path}"
                )
            except Exception as e:
                # The storage layer re-raises S3Error as a thawed mirror; match on the code.
                if getattr(e, "code", None) == "NoSuchKey":
                    return None
                raise

        results = await asyncio.gather(*(_one(p) for p in paths))
        return {path: data for path, data in zip(paths, results, strict=True) if data}

    return _fetch
