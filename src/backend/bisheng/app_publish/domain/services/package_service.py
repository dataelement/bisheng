"""Application package: volume gates, unpack safety, snapshot storage, orphan sweep (design D2).

Four things here are load-bearing and each has a failure mode that is invisible
until it bites:

* **Six illegal entry kinds, not two.** The repository's only prior unpack path
  guards a zip, which can carry absolute paths and ``..`` and nothing else. A
  tar additionally carries symlinks, hardlinks, device nodes and FIFOs: a
  symlink to ``/etc/passwd`` makes the next write a host escape, a hardlink
  hands the unpacked tree read access to any file the backend user can open
  (design 坑 15). Copying the zip guard would look complete and cover a third
  of the surface.
* **Three volume gates, because they catch different things.** The upload gate
  weighs compressed bytes; a tar bomb (8 MB of zeros → a few KB gzipped) sails
  straight through it and is only stopped by the unpacked gate; a million empty
  files trip neither and need the entry gate. All three read deployment
  configuration rather than constants — F053 AC-32 has the CLI refuse an
  oversized package *before* uploading, "according to the limits of this
  deployment", which it can only do if those limits are configuration.
* **The archive is walked as a stream** (``r|gz``) with the gates checked
  member by member. ``getmembers()`` would decompress the whole archive before
  the first check, i.e. the bomb would be paid for in full before being
  rejected.
* **Code snapshots live in their own private bucket.** ``bisheng-apps`` is
  created here, on first use, and never through ``MinioStorage._init_bucket_conf``
  — that function attaches an anonymous read policy, and nginx proxies the
  public bucket's keys to the internet (design K5 / 坑 13/14). Putting source
  code behind a guessable anonymous URL is the one mistake in this file that
  cannot be walked back after a release.

The upload itself is handed to MinIO **as a path**, never as bytes: a 50 MB
package read with ``await file.read()`` sits in an API worker's heap for the
duration of the upload.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from loguru import logger

from bisheng.app_publish.domain.models.app_deployment import STATUS_FAILED, AppDeploymentDao
from bisheng.common.errcode.app_publish import (
    AppManifestMissingError,
    AppPackageInvalidError,
    AppPackageTooLargeError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.app_version import AppVersionDao

#: Private bucket for code snapshots. **Not** the public bucket — see the module
#: docstring.
APPS_BUCKET = "bisheng-apps"

#: Manifest file name at the package root.
MANIFEST_FILENAME = "bisheng-app.yaml"

#: How long a failed attempt's snapshot is kept for debugging before the next
#: deploy of the same app sweeps it (AC-02). Not a Beat schedule: 114 has been
#: burned by a feature that silently did nothing because Beat was not running
#: (repo memory ``project_channel_information_sync_tenant_fix``).
ORPHAN_RETENTION_DAYS = 7

_CHUNK = 1024 * 1024

#: Buckets already ensured in this process. ``create_bucket`` is idempotent, but
#: issuing a ``bucket_exists`` round trip on every upload is a pointless
#: dependency on MinIO being reachable a second time.
_ensured_buckets: set[str] = set()


def reset_bucket_cache() -> None:
    """Forget which buckets were ensured — for tests, which get a fresh storage stub each time."""
    _ensured_buckets.clear()


@dataclass(slots=True)
class ExtractResult:
    """Where the package was unpacked and what it cost."""

    root: Path
    entries: int
    unpacked_bytes: int


# ---------------------------------------------------------------------------
# Volume gates
# ---------------------------------------------------------------------------


def deploy_limits() -> dict[str, int]:
    """The three gate values — also the body of ``GET /api/v2/apps/deploy-limits`` (F053 AC-32)."""
    conf = settings.app_runtime
    return {
        "max_package_mb": int(conf.max_package_mb),
        "max_unpacked_mb": int(conf.max_unpacked_mb),
        "max_package_entries": int(conf.max_package_entries),
    }


def check_upload_size(size_bytes: int) -> None:
    """Gate ①: compressed upload size (16201)."""
    limit_mb = deploy_limits()["max_package_mb"]
    if size_bytes > limit_mb * 1024 * 1024:
        raise AppPackageTooLargeError(
            msg=f"应用包 {size_bytes / 1024 / 1024:.1f} MB 超过本部署上限 {limit_mb} MB",
            details={"gate": "package_mb", "limit": limit_mb, "actual_mb": round(size_bytes / 1024 / 1024, 2)},
            hints=["检查 .gitignore 是否漏掉了虚拟环境 / 数据文件 / 构建产物", "上限由部署配置 app_runtime.max_package_mb 决定"],
        )


async def spool_upload(upload, *, suffix: str = ".tar.gz") -> Path:
    """Stream an ``UploadFile`` to a temp file, enforcing gate ① as it goes.

    Takes anything with an async ``read(size)`` — the endpoint layer's
    ``UploadFile``, or a plain stub in tests. The size is checked while
    streaming rather than afterwards so an oversized package is rejected
    without ever having been fully written, and is never held in memory.
    """
    limit_bytes = deploy_limits()["max_package_mb"] * 1024 * 1024
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    target = Path(handle.name)
    written = 0
    try:
        with handle:
            while True:
                chunk = await upload.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit_bytes:
                    raise AppPackageTooLargeError(
                        msg=f"应用包超过本部署上限 {limit_bytes // 1024 // 1024} MB",
                        details={"gate": "package_mb", "limit": limit_bytes // 1024 // 1024},
                        hints=["检查 .gitignore 是否漏掉了虚拟环境 / 数据文件 / 构建产物"],
                    )
                handle.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


# ---------------------------------------------------------------------------
# Unpacking
# ---------------------------------------------------------------------------


def safe_extract(tar_path: Path, dest: Path) -> ExtractResult:
    """Unpack ``tar_path`` into ``dest``, refusing every entry kind that can escape it.

    Streams the archive (``r|gz``) and checks the gates member by member, so a
    bomb is abandoned at the first member that crosses a limit instead of after
    the whole thing has been decompressed.
    """
    limits = deploy_limits()
    max_entries = limits["max_package_entries"]
    max_unpacked = limits["max_unpacked_mb"] * 1024 * 1024

    dest.mkdir(parents=True, exist_ok=True)
    entries = 0
    total = 0
    try:
        with tarfile.open(tar_path, "r|gz") as tar:
            for member in tar:
                entries += 1
                if entries > max_entries:
                    raise AppPackageTooLargeError(
                        msg=f"应用包条目数超过本部署上限 {max_entries}",
                        details={"gate": "entries", "limit": max_entries},
                        hints=["检查是否把 node_modules / .git / 缓存目录打进了包"],
                    )
                relative = _safe_member_path(member)
                total += max(0, member.size)
                if total > max_unpacked:
                    raise AppPackageTooLargeError(
                        msg=f"应用包解压后超过本部署上限 {limits['max_unpacked_mb']} MB",
                        details={"gate": "unpacked_mb", "limit": limits["max_unpacked_mb"]},
                        hints=["解压后体积远大于上传体积通常意味着包里有大体积可压缩文件(日志 / 数据集 / 模型权重)"],
                    )
                _write_member(tar, member, dest / relative)
    except tarfile.TarError as exc:
        raise AppPackageInvalidError(
            msg="应用包无法解析",
            details={"reason": "unreadable_archive"},
            hints=["应用包需要是 gzip 压缩的 tar 归档(.tar.gz)"],
        ) from exc

    return ExtractResult(root=_resolve_root(dest), entries=entries, unpacked_bytes=total)


def _safe_member_path(member: tarfile.TarInfo) -> PurePosixPath:
    """Reject the six entry kinds that must never be extracted; return the safe relative path.

    ``details.reason`` names the kind rather than saying "illegal entry": a
    developer whose build tool emitted a symlink needs to know it was the
    symlink, and a developer who was attacked needs the audit trail to say so.
    """
    raw = member.name.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute():
        _reject("absolute_path", member.name, "包内条目使用了绝对路径")
    if any(part == ".." for part in path.parts):
        _reject("traversal", member.name, "包内条目试图跳出解包目录")
    if member.issym():
        _reject("symlink", member.name, "包内含符号链接")
    if member.islnk():
        _reject("hardlink", member.name, "包内含硬链接")
    # ``isdev()`` is true for FIFOs as well, so the narrower check goes first —
    # otherwise a named pipe is reported as a device file and the developer
    # goes looking for the wrong thing in their build.
    if member.isfifo():
        _reject("fifo", member.name, "包内含命名管道")
    if member.isdev() or member.ischr() or member.isblk():
        _reject("device", member.name, "包内含设备文件")
    if not (member.isfile() or member.isdir()):
        _reject("unsupported_entry", member.name, "包内含不支持的条目类型")
    return PurePosixPath(*[part for part in path.parts if part not in ("", ".")])


def _reject(reason: str, entry: str, message: str) -> None:
    raise AppPackageInvalidError(
        msg=f"{message}: {entry}",
        details={"reason": reason, "entry": entry},
        hints=["应用包只允许普通文件与目录; 请用 tar --dereference 或在打包前解开链接"],
    )


def _write_member(tar: tarfile.TarFile, member: tarfile.TarInfo, target: Path) -> None:
    """Materialise one member. Modes are never taken from the archive."""
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    source = tar.extractfile(member)
    if source is None:
        return
    with open(target, "wb") as handle:
        shutil.copyfileobj(source, handle, _CHUNK)
    os.chmod(target, 0o644)


def _resolve_root(dest: Path) -> Path:
    """The package root: ``dest``, or its single top-level directory if the manifest is in there.

    ``tar czf pkg.tar.gz myapp/`` is what a developer types without thinking,
    and rejecting it with "bisheng-app.yaml is missing" would be technically
    true and practically useless. Only a *single* top-level directory is
    unwrapped, so a package with real content at the root is never
    misinterpreted.
    """
    if (dest / MANIFEST_FILENAME).is_file():
        return dest
    children = list(dest.iterdir())
    if len(children) == 1 and children[0].is_dir() and (children[0] / MANIFEST_FILENAME).is_file():
        return children[0]
    return dest


def read_manifest_bytes(root: Path) -> bytes:
    """The manifest at the package root, or 16203."""
    manifest = root / MANIFEST_FILENAME
    if not manifest.is_file():
        raise AppManifestMissingError(
            msg=f"应用包根目录缺少 {MANIFEST_FILENAME}",
            details={"reason": "manifest_missing", "expected": MANIFEST_FILENAME},
            hints=[f"在项目根目录创建 {MANIFEST_FILENAME}, 至少声明 name / runtime / port"],
        )
    return manifest.read_bytes()


# ---------------------------------------------------------------------------
# Snapshot storage
# ---------------------------------------------------------------------------


def snapshot_key(app_id: str, version_id: str) -> str:
    """F054's snapshot layout. The version id is minted at receive time (design D2).

    There is deliberately no ``deployments/{id}/…`` staging key followed by a
    server-side copy: a server-side copy is a full read and write inside MinIO,
    i.e. a hallucinated optimisation (repo memory
    ``project_linsight_skill_object_storage``), and nothing forces the version
    id to be minted late.
    """
    return f"apps/{app_id}/versions/{version_id}/code.tar.gz"


async def _ensure_bucket() -> None:
    if APPS_BUCKET in _ensured_buckets:
        return
    storage = await get_minio_storage()
    await storage.create_bucket(APPS_BUCKET)
    _ensured_buckets.add(APPS_BUCKET)


async def store_package(package_path: Path, *, app_id: str, version_id: str) -> str:
    """Upload the snapshot and return its object key.

    ``file=Path`` on purpose — the facade turns that into ``fput_object`` on a
    worker thread, so the package never enters this process's heap.
    """
    await _ensure_bucket()
    key = snapshot_key(app_id, version_id)
    storage = await get_minio_storage()
    await storage.put_object(
        bucket_name=APPS_BUCKET,
        object_name=key,
        file=Path(package_path),
        content_type="application/gzip",
    )
    return key


async def fetch_package(object_key: str) -> bytes | None:
    """Retrieve a snapshot (AC-43: review view, preview start-up, future rollback)."""
    storage = await get_minio_storage()
    return await storage.get_object(bucket_name=APPS_BUCKET, object_name=object_key)


async def cleanup_orphans(app_id: str) -> list[str]:
    """Delete snapshots of this app's long-failed attempts; return the keys removed.

    Runs on the receive leg of the *next* deploy of the same app rather than on
    a schedule (design D2) — a Beat job that is not running fails silently, and
    this one only needs to be eventually correct.

    Driven from ``app_deployment``: every key the pipeline ever wrote is on a
    row, and rows are never deleted, so the table is a complete index. A sweep
    that listed the bucket instead could delete a key it does not understand.
    """
    cutoff = datetime.now() - timedelta(days=ORPHAN_RETENTION_DAYS)
    removed: list[str] = []
    async with get_async_db_session() as session:
        attempts = await AppDeploymentDao.alist_by_app(session, app_id, limit=200)
        for attempt in attempts:
            if attempt.status != STATUS_FAILED or not attempt.code_object_key:
                continue
            if attempt.create_time and attempt.create_time > cutoff:
                continue
            if attempt.version_id and await AppVersionDao.aget(session, app_id, attempt.version_id) is not None:
                continue  # a version record points at it: it is a snapshot, not an orphan
            removed.append(attempt.code_object_key)

    if removed:
        storage = await get_minio_storage()
        for key in removed:
            await storage.remove_object(bucket_name=APPS_BUCKET, object_name=key)
        logger.info(f"app_publish.orphan_sweep app_id={app_id} removed={len(removed)}")
    return removed
