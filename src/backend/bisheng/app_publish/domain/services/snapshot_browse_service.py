"""Edit or current-task access to bounded, masked frozen source snapshots."""

from __future__ import annotations

import asyncio
import io
import tarfile
from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.secret_scanner import mask_secrets, skip_reason
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.app_runtime.application.authorization import authorize_app
from bisheng.approval.application.app_review import pending_app_reviews
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.app_publish import (
    AppPackageInvalidError,
    AppSnapshotFileNotFoundError,
    AppVersionNotFoundError,
    AppVersionReviewForbiddenError,
    AppVersionSnapshotUnavailableError,
)
from bisheng.common.errcode.permission import InvalidCatalogActionError, PermissionDeniedError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.open_api.application.access_context import get_current_open_api_principal

#: Bytes read from the head of each file to decide "binary" — the scanner's
#: own sniff width, restated here because the listing reads it off a stream.
_SNIFF_BYTES = 8192

ROLE_EDITOR = "editor"
ROLE_APPROVER = "approver"


class ReviewAccess:
    """A temporary task never becomes a lasting application-management grant."""

    @staticmethod
    async def load_app(app_id: str):
        app = await VersionService.get_app_scoped(app_id)
        if app is None or app.state == "deleted":
            raise AppVersionReviewForbiddenError()
        return app

    @staticmethod
    def _natural_viewer(actor) -> int | None:
        principal = get_current_open_api_principal()
        if principal is not None:
            if principal.actor_kind != "natural_person":
                return None
            return int(principal.authorization_subject_id)
        if getattr(actor, "subject_type", "user") != "user":
            return None
        return int(getattr(actor, "user_id", 0) or 0) or None

    @classmethod
    @asynccontextmanager
    async def scope(cls, app_id: str, actor, version_ids: Iterable[str]):
        requested = {str(value) for value in version_ids}
        viewer = cls._natural_viewer(actor)
        grants = await pending_app_reviews(viewer, app_id, requested) if viewer else ()
        if grants:
            tenants = {grant.tenant_id for grant in grants}
            if len(tenants) != 1 or any(grant.app_id != app_id for grant in grants):
                raise AppVersionReviewForbiddenError()
            target_tenant = next(iter(tenants))
            if int(getattr(actor, "tenant_id", 0) or 0) != target_tenant and not bool(
                getattr(actor, "is_global_super", False)
            ):
                raise AppVersionReviewForbiddenError()
            with tenant_execution_scope(target_tenant):
                app = await cls.load_app(app_id)
                permitted = {grant.version_id for grant in grants} | {app.current_version_id}
                if app.tenant_id != target_tenant or not requested.issubset(permitted):
                    raise AppVersionReviewForbiddenError()
                yield app, ROLE_APPROVER
            return
        app = await cls.load_app(app_id)
        try:
            await authorize_app(actor, app_id, "content_read")
        except (AppNotFoundError, PermissionDeniedError, InvalidCatalogActionError) as exc:
            raise AppVersionReviewForbiddenError() from exc
        yield app, ROLE_EDITOR

    @classmethod
    async def require(cls, app, actor, version_ids: Iterable[str]) -> str:
        async with cls.scope(app.id, actor, version_ids) as (current, role):
            if current.tenant_id != app.tenant_id:
                raise AppVersionReviewForbiddenError()
            return role


# ---------------------------------------------------------------------------
# Snapshot reads
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Member:
    """One regular-file member as seen while streaming the archive."""

    path: str
    size: int
    head: bytes
    content: bytes | None = None


class SnapshotBrowseService:
    """Tree listing and single-file read over a version's snapshot. Never writes."""

    @classmethod
    async def review_context(cls, app_id: str, version_id: str, *, actor) -> dict[str, Any]:
        """What the review view needs *around* the source: the version history and the two diff sides.

        An approver cannot get this anywhere else. ``publish-status`` and
        F054's ``GET /apps/{app_id}/versions`` both admit owner / tenant admin
        / super admin only, so the approver opening a review view would have
        an empty 版本历史 tab and no way to learn which version the pending one
        should be diffed against (AC-25 / AC-41). This read hangs off the same
        :class:`ReviewAccess` rule as the tree and the file, and answers with
        the same ``role`` — one access rule for the whole face.

        Read-only and free of the snapshot: no object storage is touched.
        """
        async with ReviewAccess.scope(app_id, actor, (version_id,)) as (app, role):
            version = await cls.load_version(app.id, version_id)
            rows = await VersionService.list_versions(app.id)
            return {
                "version": cls.version_payload(version),
                "role": role,
                "current_version_id": app.current_version_id,
                "pending_version_id": app.pending_version_id,
                "versions": [
                    {
                        **cls.version_payload(row),
                        "is_current": row.id == app.current_version_id,
                        "is_pending": row.id == app.pending_version_id,
                    }
                    for row in rows
                ],
            }

    @classmethod
    async def list_tree(cls, app_id: str, version_id: str, *, actor) -> dict[str, Any]:
        """Every entry of the snapshot as a flat, sorted list the client folds into a tree.

        Directories are listed explicitly (derived from file paths, so an
        archive that omitted directory members still yields a complete tree).
        ``previewable`` is decided per file from size plus a head sniff — the
        same two checks the scanner applies — so the client can grey a file
        out before asking for it.
        """
        async with ReviewAccess.scope(app_id, actor, (version_id,)) as (app, role):
            version = await cls.load_version(app.id, version_id)
            data = await cls.load_snapshot_bytes(app.id, version)
            limit = package_service.deploy_limits()["max_package_entries"]
            members, truncated = await asyncio.to_thread(cls._walk, data, version_id, None, limit)

            prefix = package_service.snapshot_root_prefix([member.path for member in members])
            entries: list[dict[str, Any]] = []
            seen_dirs: set[str] = set()
            for member in members:
                if prefix and not member.path.startswith(prefix):
                    continue  # a sibling of the single wrapping directory: not part of the app
                relative = member.path[len(prefix) :]
                parts = PurePosixPath(relative).parts
                for depth in range(1, len(parts)):
                    directory = "/".join(parts[:depth])
                    if directory not in seen_dirs:
                        seen_dirs.add(directory)
                        entries.append({"path": directory, "name": parts[depth - 1], "type": "dir", "size": None})
                reason = skip_reason(member.size, member.head)
                entries.append(
                    {
                        "path": relative,
                        "name": parts[-1],
                        "type": "file",
                        "size": member.size,
                        "previewable": reason is None,
                        "reason": reason,
                    }
                )
            entries.sort(key=lambda item: item["path"])
            return {
                "version": cls.version_payload(version),
                "role": role,
                "entries": entries,
                "total_files": sum(1 for item in entries if item["type"] == "file"),
                "truncated": truncated,
            }

    @classmethod
    async def read_file(cls, app_id: str, version_id: str, path: str, *, actor) -> dict[str, Any]:
        """One file's text, masked; or ``previewable: false`` with the reason.

        A file the scanner would have skipped is not decoded at all: its bytes
        never left object storage. The 1 MiB ceiling is the scanner's
        ``MAX_SCAN_FILE_BYTES``, not a UI preference — it is the size above
        which the platform has not vetted the content.
        """
        async with ReviewAccess.scope(app_id, actor, (version_id,)) as (app, role):
            version = await cls.load_version(app.id, version_id)
            wanted = cls._normalise_request_path(path)
            data = await cls.load_snapshot_bytes(app.id, version)
            limit = package_service.deploy_limits()["max_package_entries"]
            members, _truncated = await asyncio.to_thread(cls._walk, data, version_id, wanted, limit)

            prefix = package_service.snapshot_root_prefix([member.path for member in members])
            member = next((m for m in members if m.path == prefix + wanted), None)
            if member is None:
                raise AppSnapshotFileNotFoundError(
                    msg=f"快照中没有这个文件: {wanted}",
                    details={"path": wanted, "reason": "not_found"},
                )
            reason = skip_reason(member.size, member.head)
            payload: dict[str, Any] = {
                "version": cls.version_payload(version),
                "role": role,
                "path": wanted,
                "size": member.size,
                "previewable": reason is None,
                "reason": reason,
                "content": None,
                "masked_secrets": 0,
                "line_count": 0,
            }
            if reason is not None or member.content is None:
                return payload
            text, masked = mask_secrets(member.content.decode("utf-8", errors="replace"))
            payload.update(
                {
                    "content": text,
                    "masked_secrets": masked,
                    "line_count": len(text.splitlines()),
                }
            )
            if masked:
                logger.warning(
                    f"app_publish.snapshot_masked app_id={app.id} version_id={version_id} path={wanted} masked={masked}"
                )
            return payload

        # ------------------------------------------------------------------
        # internals
        # ------------------------------------------------------------------

    @staticmethod
    async def load_version(app_id: str, version_id: str):
        version = await VersionService.get_version(app_id, version_id)
        if version is None:
            raise AppVersionNotFoundError(
                msg="版本记录不存在",
                details={"app_id": app_id, "version_id": version_id},
            )
        return version

    @staticmethod
    async def load_snapshot_bytes(app_id: str, version) -> bytes:
        """The frozen package, or 16256. The object key is on the version row (AC-43)."""
        try:
            data = await VersionService.get_snapshot(app_id, str(version.id))
        except Exception:
            logger.exception(f"app_publish.snapshot_fetch_failed app_id={app_id} version_id={version.id}")
            raise AppVersionSnapshotUnavailableError(
                msg="该版本的代码快照读取失败",
                details={"app_id": app_id, "version_id": version.id, "reason": "storage_error"},
                hints=["请联系管理员检查对象存储"],
            )
        if not data:
            raise AppVersionSnapshotUnavailableError(
                msg="该版本的代码快照不存在",
                details={"app_id": app_id, "version_id": version.id, "reason": "missing"},
                hints=["快照可能已被清理; 请联系管理员"],
            )
        return data

    @staticmethod
    def _normalise_request_path(path: str) -> str:
        raw = (path or "").replace("\\", "/").strip()
        candidate = PurePosixPath(raw)
        if not raw or candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise AppSnapshotFileNotFoundError(
                msg="非法的文件路径",
                details={"path": path, "reason": "illegal_path"},
            )
        parts = [part for part in candidate.parts if part not in ("", ".")]
        if not parts:
            raise AppSnapshotFileNotFoundError(
                msg="非法的文件路径",
                details={"path": path, "reason": "illegal_path"},
            )
        return "/".join(parts)

    @staticmethod
    def _walk(data: bytes, version_id: str, wanted: str | None, limit: int) -> tuple[list[_Member], bool]:
        """Stream the archive once; return its regular files and whether the walk was cut short.

        ``wanted`` (a root-relative path) asks for one file's content to be
        kept. The root prefix is only known after the whole archive has been
        seen, so both spellings — ``wanted`` and ``<top>/wanted`` — are kept
        and the caller picks; at most two members are ever held in memory,
        and only when they are under the preview ceiling.
        """
        members: list[_Member] = []
        truncated = False
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r|gz") as tar:
                for info in tar:
                    relative = package_service.safe_member_path(info)
                    if not info.isfile():
                        continue
                    if len(members) >= limit:
                        truncated = True
                        break
                    path = relative.as_posix()
                    handle = tar.extractfile(info)
                    head = handle.read(_SNIFF_BYTES) if handle is not None else b""
                    member = _Member(path=path, size=max(0, info.size), head=head)
                    if wanted is not None and handle is not None and _matches(path, wanted):
                        if skip_reason(member.size, head) is None:
                            member.content = head + handle.read()
                    members.append(member)
        except (tarfile.TarError, EOFError, OSError, AppPackageInvalidError) as exc:
            logger.warning(f"app_publish.snapshot_unreadable version_id={version_id} error={exc!r}")
            raise AppVersionSnapshotUnavailableError(
                msg="该版本的代码快照无法解析",
                details={"version_id": version_id, "reason": "unreadable_archive"},
                hints=["请联系管理员检查对象存储中的快照"],
            ) from exc
        return members, truncated

    @staticmethod
    def version_payload(version) -> dict[str, Any]:
        return {
            "version_id": version.id,
            "version_no": version.version_no,
            "kind": version.kind,
            "terminal_state": version.terminal_state,
            "submitted_at": version.submitted_at,
        }


def _matches(path: str, wanted: str) -> bool:
    """``path`` is ``wanted`` at the root, or ``wanted`` under a single wrapping directory."""
    if path == wanted:
        return True
    top, _, rest = path.partition("/")
    return bool(top) and rest == wanted
