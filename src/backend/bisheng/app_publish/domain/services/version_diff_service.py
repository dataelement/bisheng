"""Server-side diff of two version snapshots (AC-41 / T063 / design D15).

The design sentence this module exists for: **the diff is computed here and
the two tars never reach the browser.** Shipping both packages to the client
would hand the source in clear to whoever can open the page, and a 50 MB
package would lock the tab before the first hunk rendered. What goes out is a
change list plus unified-diff text, both bounded.

Bounds, and why each is where it is:

* **Per-file preview ceiling = the scanner's** (``MAX_SCAN_FILE_BYTES``) and
  the same binary sniff. A file the scan never read is reported as changed
  but ``comparable: false`` — its bytes are not decoded, let alone diffed.
* **Per-file patch cap** (:data:`MAX_PATCH_LINES_PER_FILE`): a regenerated
  lockfile diffs to tens of thousands of lines nobody reads; the first lines
  and a ``truncated`` flag say all there is to say.
* **Total patch budget** (:data:`MAX_TOTAL_PATCH_BYTES`): once spent, later
  files still appear in ``files`` with their counts but their patch is
  ``None``. The change *list* is always complete up to
  :data:`MAX_DIFF_FILES`; only the *text* is rationed.
* **Secrets are masked before diffing**, not after: masking the output would
  leave a credential that straddles a hunk boundary half visible.

Both snapshots are materialised through :func:`package_service.safe_extract`
— the six-entry-kind guard and the volume gates run again on the frozen bytes,
which costs nothing and means a snapshot tampered with in object storage is
refused here the way it would be at deploy.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.secret_scanner import mask_secrets, skip_reason
from bisheng.app_publish.domain.services.snapshot_browse_service import ReviewAccess, SnapshotBrowseService
from bisheng.common.errcode.app_publish import AppPublishError, AppVersionSnapshotUnavailableError

#: Files listed at most. Beyond it ``summary.truncated`` is set and the list
#: stops — a package that changed more files than this is not reviewable as a
#: diff anyway, and the entry gate keeps it under 20 000 in the first place.
MAX_DIFF_FILES = 5000

#: Unified-diff lines kept per file before the hunk text is cut.
MAX_PATCH_LINES_PER_FILE = 2000

#: Total bytes of patch text one response may carry.
MAX_TOTAL_PATCH_BYTES = 2 * 1024 * 1024

#: Context lines around each hunk — git's default, which is what reviewers read.
_CONTEXT_LINES = 3

_SNIFF_BYTES = 8192

CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"
CHANGE_MODIFIED = "modified"


@dataclass(slots=True)
class _Side:
    """One file on one side of the comparison."""

    path: Path
    size: int
    head: bytes

    @classmethod
    def read(cls, path: Path) -> _Side:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            head = handle.read(_SNIFF_BYTES)
        return cls(path=path, size=size, head=head)

    def reason(self) -> str | None:
        return skip_reason(self.size, self.head)


@dataclass(slots=True)
class _Budget:
    """Mutable counters threaded through the walk."""

    patch_bytes: int = 0
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0
    truncated: bool = False
    files: list[dict[str, Any]] = field(default_factory=list)
    patches: list[dict[str, Any]] = field(default_factory=list)


class VersionDiffService:
    """``diff(app_id, base, target)`` — what changed from ``base`` to ``target``."""

    @classmethod
    async def diff(cls, app_id: str, base_version_id: str, target_version_id: str, *, actor) -> dict[str, Any]:
        """Design §4.2 ⑨. ``base`` is the older side ("a/"), ``target`` the newer ("b/").

        Access is the review view's rule (:class:`ReviewAccess`) asked about
        *both* versions: an approver holding a task on the pending version is
        thereby admitted to compare it with the published one, which is the
        only diff AC-41 asks for and the one side that never has a request of
        its own.
        """
        app = await ReviewAccess.load_app(app_id)
        role = await ReviewAccess.require(app, actor, (base_version_id, target_version_id))
        base = await SnapshotBrowseService.load_version(app.id, base_version_id)
        target = await SnapshotBrowseService.load_version(app.id, target_version_id)
        base_bytes = await SnapshotBrowseService.load_snapshot_bytes(app.id, base)
        target_bytes = await SnapshotBrowseService.load_snapshot_bytes(app.id, target)

        try:
            budget = await asyncio.to_thread(cls._compute, base_bytes, target_bytes)
        except AppPublishError as exc:
            # ``safe_extract`` speaks in deploy-time codes (16201 / 16202). At
            # review time the developer did nothing wrong — the stored bytes
            # are — so the caller hears "snapshot unavailable" with the cause.
            logger.warning(
                f"app_publish.diff_snapshot_invalid app_id={app.id} base={base_version_id} "
                f"target={target_version_id} code={exc.Code}"
            )
            raise AppVersionSnapshotUnavailableError(
                msg="快照无法解析, 无法比较",
                details={"app_id": app.id, "reason": "unreadable_archive", "cause": exc.Code},
                hints=["请联系管理员检查对象存储中的快照"],
            ) from exc

        return {
            "base": SnapshotBrowseService.version_payload(base),
            "target": SnapshotBrowseService.version_payload(target),
            "role": role,
            "summary": {
                "files_changed": budget.files_changed,
                "additions": budget.additions,
                "deletions": budget.deletions,
                "truncated": budget.truncated,
            },
            "files": budget.files,
            "patches": budget.patches,
        }

    # ------------------------------------------------------------------
    # the walk (runs on a worker thread)
    # ------------------------------------------------------------------

    @classmethod
    def _compute(cls, base_bytes: bytes, target_bytes: bytes) -> _Budget:
        with tempfile.TemporaryDirectory(prefix="bisheng-diff-") as workdir:
            work = Path(workdir)
            base_root = cls._materialise(base_bytes, work / "a")
            target_root = cls._materialise(target_bytes, work / "b")
            base_files = cls._index(base_root)
            target_files = cls._index(target_root)

            budget = _Budget()
            for path in sorted(set(base_files) | set(target_files)):
                if len(budget.files) >= MAX_DIFF_FILES:
                    budget.truncated = True
                    break
                cls._compare_one(path, base_files.get(path), target_files.get(path), budget)
            return budget

    @staticmethod
    def _materialise(data: bytes, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest.with_suffix(".tar.gz")
        archive.write_bytes(data)
        try:
            return package_service.safe_extract(archive, dest).root
        finally:
            archive.unlink(missing_ok=True)

    @staticmethod
    def _index(root: Path) -> dict[str, _Side]:
        """Package-relative POSIX path → file, regular files only.

        ``safe_extract`` never writes a symlink, so ``is_file`` here cannot
        follow one out of the tree; the check is kept as belt and braces.
        """
        index: dict[str, _Side] = {}
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                path = Path(dirpath) / name
                if path.is_symlink() or not path.is_file():
                    continue
                index[path.relative_to(root).as_posix()] = _Side.read(path)
        return index

    @classmethod
    def _compare_one(cls, path: str, base: _Side | None, target: _Side | None, budget: _Budget) -> None:
        if base is None and target is None:
            return
        if base is not None and target is not None and cls._same_bytes(base, target):
            return
        change = CHANGE_ADDED if base is None else CHANGE_REMOVED if target is None else CHANGE_MODIFIED

        reason = next((r for r in (target.reason() if target else None, base.reason() if base else None) if r), None)
        entry: dict[str, Any] = {
            "path": path,
            "change": change,
            "additions": 0,
            "deletions": 0,
            "comparable": reason is None,
            "reason": reason,
        }
        budget.files.append(entry)
        budget.files_changed += 1
        if reason is not None:
            return

        old_text, masked_old = mask_secrets(cls._text(base)) if base else ("", 0)
        new_text, masked_new = mask_secrets(cls._text(target)) if target else ("", 0)
        old = old_text.splitlines(keepends=True)
        new = new_text.splitlines(keepends=True)
        masked = masked_old + masked_new

        lines = list(
            difflib.unified_diff(
                old,
                new,
                fromfile=f"a/{path}" if base else "/dev/null",
                tofile=f"b/{path}" if target else "/dev/null",
                n=_CONTEXT_LINES,
            )
        )
        additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        entry["additions"] = additions
        entry["deletions"] = deletions
        budget.additions += additions
        budget.deletions += deletions

        truncated = len(lines) > MAX_PATCH_LINES_PER_FILE
        patch = "".join(cls._terminated(line) for line in lines[:MAX_PATCH_LINES_PER_FILE])
        if budget.patch_bytes >= MAX_TOTAL_PATCH_BYTES:
            budget.patches.append(
                {"path": path, "change": change, "patch": None, "truncated": True, "masked_secrets": masked}
            )
            budget.truncated = True
            return
        budget.patch_bytes += len(patch.encode("utf-8"))
        budget.patches.append(
            {"path": path, "change": change, "patch": patch, "truncated": truncated, "masked_secrets": masked}
        )

    @staticmethod
    def _same_bytes(base: _Side, target: _Side) -> bool:
        if base.size != target.size or base.head != target.head:
            return False
        return base.path.read_bytes() == target.path.read_bytes()

    @staticmethod
    def _text(side: _Side) -> str:
        return side.path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _terminated(line: str) -> str:
        """``difflib`` echoes a missing trailing newline as-is; a patch must stay line-shaped."""
        return line if line.endswith("\n") else line + "\n"
