"""Read-only browsing of one version's frozen package — the review view's data (AC-25 / T052).

Three reads (tree, one file, and the surrounding review context), one access
rule, and three things that are easy to get wrong:

* **Who may look.** The owner, the app's tenant administrator and a platform
  super admin (the same set ``publish-status`` admits), **plus an approver who
  holds a task on the publish request of that very version** — AC-30 keeps a
  draft app owner-only and names the review view as the approver's sanctioned
  way in. "Holds a task" is taken literally: a task row with the caller's
  ``approver_user_id`` on an instance whose ``payload_snapshot.version_id`` is
  the version asked for. Being an approver *somewhere* admits nobody; being
  the approver of version 3 does not open version 1. Refusals ride in the 200
  envelope (design K11 ②).
* **Nothing is extracted.** A tree listing or a single file read walks the
  archive as a stream and never writes to disk — a 50 MB package per click,
  materialised in a temp directory, is how an API worker's disk fills up
  quietly. The path rule is still the extractor's (:func:`safe_member_path`),
  so a listing cannot show an entry the runtime would have refused.
* **What the scanner did not read, the browser does not show.** A binary or
  over-sized file degrades to ``previewable: false`` with the scanner's own
  reason, and what *is* shown goes through :func:`mask_secrets` first. A
  version snapshot passed the scan gate by construction (only attempts that
  did get a version row), but the rule set grows and a snapshot frozen under
  yesterday's rules is read under today's.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.app_publish_scenario_handler import SCENARIO_CODE
from bisheng.app_publish.domain.services.secret_scanner import mask_secrets, skip_reason
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.common.errcode.app_publish import (
    AppPackageInvalidError,
    AppSnapshotFileNotFoundError,
    AppVersionNotFoundError,
    AppVersionReviewForbiddenError,
    AppVersionSnapshotUnavailableError,
)
from bisheng.common.permission_identity import check_tenant_admin

#: Bytes read from the head of each file to decide "binary" — the scanner's
#: own sniff width, restated here because the listing reads it off a stream.
_SNIFF_BYTES = 8192

#: The roles :meth:`ReviewAccess.require` can answer with. Returned rather than
#: swallowed so the endpoint can tell the client *why* it is allowed in — an
#: approver's view and an owner's view differ in what else they may do.
ROLE_OWNER = "owner"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_APPROVER = "approver"


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


class ReviewAccess:
    """The single answer to "may this caller read the source of these versions"."""

    @classmethod
    async def load_app(cls, app_id: str):
        """The app row, or 16257 with ``reason: not_found``.

        Deliberately the *same* code as "not allowed": a stranger probing ids
        learns nothing from the difference, and the client renders both as
        "you cannot view this".
        """
        app = await VersionService.get_app_scoped(app_id)
        if app is None:
            raise AppVersionReviewForbiddenError(
                msg="应用不存在或无权访问",
                details={"app_id": app_id, "reason": "not_found"},
                hints=["请确认应用是否已被删除"],
            )
        return app

    @classmethod
    async def require(cls, app, actor, version_ids: Iterable[str]) -> str:
        """Return the role the caller is admitted under, or raise 16257.

        ``version_ids`` is the set of versions the read is about — one for a
        tree or file read, two for a diff. An approver is admitted when they
        hold a task on the publish request of **any** of them: the diff an
        approver needs is "pending version against the last published one",
        and the published side has no request of its own to hold a task on.
        """
        user_id = int(getattr(actor, "user_id", 0) or 0)
        if user_id and user_id == int(app.owner_user_id or 0):
            return ROLE_OWNER
        if bool(getattr(actor, "is_global_super", False)):
            return ROLE_SUPER_ADMIN
        if await check_tenant_admin(user_id, int(app.tenant_id or 0)):
            return ROLE_TENANT_ADMIN
        if await cls._holds_task(app, user_id, {str(v) for v in version_ids}):
            return ROLE_APPROVER
        raise AppVersionReviewForbiddenError(
            msg="没有查看该版本代码的权限",
            details={"app_id": app.id, "reason": "not_reviewer"},
            hints=["只有应用负责人、租户管理员和该版本的审批人可以查看"],
        )

    @staticmethod
    async def _holds_task(app, user_id: int, version_ids: set[str]) -> bool:
        if not user_id or not version_ids:
            return False
        instances = await ApprovalInstanceRepository.list_instances_by_resource(
            tenant_id=int(app.tenant_id or 0),
            scenario_code=SCENARIO_CODE,
            business_resource_type="app",
            business_resource_id=str(app.id),
        )
        for instance in instances:
            payload = instance.payload_snapshot if isinstance(instance.payload_snapshot, dict) else {}
            if str(payload.get("version_id") or "") not in version_ids:
                continue
            tasks = await ApprovalInstanceRepository.list_tasks(int(instance.id))
            if any(int(task.approver_user_id or 0) == user_id for task in tasks):
                return True
        return False


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
        app = await ReviewAccess.load_app(app_id)
        role = await ReviewAccess.require(app, actor, (version_id,))
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
        app = await ReviewAccess.load_app(app_id)
        role = await ReviewAccess.require(app, actor, (version_id,))
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
        app = await ReviewAccess.load_app(app_id)
        role = await ReviewAccess.require(app, actor, (version_id,))
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
