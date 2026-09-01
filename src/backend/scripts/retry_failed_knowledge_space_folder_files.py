#!/usr/bin/env python3
"""Retry parse for failed files under a named knowledge-space folder.

Looks up a knowledge space by display name, resolves a (possibly nested)
folder by name path, lists files whose status is FAILED under that folder
(including nested subfolders), then optionally enqueues worker retry tasks.

By default this is a dry-run. Pass ``--apply`` to update each still-failed
file to ``WAITING`` and publish ``retry_knowledge_file_celery``.

Folder paths use ``/`` (also ``>`` or ``->``). A single unique folder name
in the space is accepted without the full path.

Usage (from ``src/backend``):

    export config=/path/to/config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/retry_failed_knowledge_space_folder_files.py \\
      --space-name "安全生产知识库" --folder "安全生产/消防安全"
    PYTHONPATH=./ .venv/bin/python scripts/retry_failed_knowledge_space_folder_files.py \\
      --space-name "安全生产知识库" --folder "消防安全" --apply
    PYTHONPATH=./ .venv/bin/python scripts/retry_failed_knowledge_space_folder_files.py \\
      --space-name "安全生产知识库" --folder "安全生产/消防安全" --tenant-id 1 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from scripts.enqueue_reparse_knowledge_space_files import (  # noqa: E402
    apply_selection,
    exit_code_for_report,
)
from scripts.reparse_knowledge_space_files import (  # noqa: E402
    _folder_descendant_prefix,
    collect_candidate_files,
    print_selection_report,
)

_FOLDER_PATH_SPLIT = re.compile(r"\s*(?:->|/|>)\s*")
_REMARK_DISPLAY_LIMIT = 160


class TargetLookupError(RuntimeError):
    """Raised when a space or folder name cannot be resolved uniquely."""


@dataclass(frozen=True)
class ResolvedTarget:
    space: Knowledge
    folder: KnowledgeFile
    folder_path: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space-name", required=True, help="knowledge-space display name")
    parser.add_argument(
        "--folder",
        required=True,
        help='folder name or nested path, e.g. "消防安全" or "安全生产/消防安全"',
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=None,
        help="disambiguate when multiple spaces share the same name",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="enqueue retry tasks; default is dry-run",
    )
    parser.add_argument(
        "--include-timeout",
        action="store_true",
        help="also select TIMEOUT files in addition to FAILED",
    )
    return parser.parse_args(argv)


def split_folder_path(raw: str) -> list[str]:
    parts = [part.strip() for part in _FOLDER_PATH_SPLIT.split(raw.strip()) if part.strip()]
    if not parts:
        raise TargetLookupError("folder path is empty")
    return parts


def normalize_parent_path(file_level_path: str | None) -> str:
    return (file_level_path or "").rstrip("/")


def folder_name_path(folder: KnowledgeFile, folders_by_id: dict[int, KnowledgeFile]) -> str:
    ancestor_ids = [int(part) for part in normalize_parent_path(folder.file_level_path).split("/") if part]
    names: list[str] = []
    for ancestor_id in ancestor_ids:
        ancestor = folders_by_id.get(ancestor_id)
        names.append(ancestor.file_name if ancestor is not None else f"#{ancestor_id}")
    names.append(folder.file_name)
    return "/".join(names)


def _format_space(space: Knowledge) -> str:
    return f"id={space.id} tenant_id={space.tenant_id} name={space.name}"


def _format_folder(folder: KnowledgeFile, folders_by_id: dict[int, KnowledgeFile]) -> str:
    return f"id={folder.id} path={folder_name_path(folder, folders_by_id)}"


def resolve_folder(
    folders: Sequence[KnowledgeFile],
    raw_path: str,
) -> KnowledgeFile:
    parts = split_folder_path(raw_path)
    folders_by_id = {int(folder.id): folder for folder in folders if folder.id is not None}

    current_parent = ""
    current: KnowledgeFile | None = None
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        matches = [
            folder
            for folder in folders
            if (folder.file_name or "").strip() == part
            and normalize_parent_path(folder.file_level_path) == current_parent
        ]
        if not matches:
            raise TargetLookupError(
                f'folder not found at "{"/".join(walked)}"'
                + (f" under parent {current_parent or '(root)'}" if current_parent else "")
            )
        if len(matches) > 1:
            listed = ", ".join(_format_folder(item, folders_by_id) for item in matches)
            raise TargetLookupError(
                f'folder name "{part}" is not unique under "{"/".join(walked[:-1]) or "(root)"}": {listed}'
            )
        current = matches[0]
        current_parent = _folder_descendant_prefix(current)

    if current is None:
        raise TargetLookupError("folder path is empty")
    return current


def resolve_unique_folder_by_name(
    folders: Sequence[KnowledgeFile],
    name: str,
) -> KnowledgeFile:
    matches = [folder for folder in folders if (folder.file_name or "").strip() == name]
    folders_by_id = {int(folder.id): folder for folder in folders if folder.id is not None}
    if not matches:
        raise TargetLookupError(f'folder "{name}" not found in this knowledge space')
    if len(matches) > 1:
        listed = "; ".join(_format_folder(item, folders_by_id) for item in matches)
        raise TargetLookupError(
            f'folder "{name}" is not unique; pass the full path, for example --folder "{folder_name_path(matches[0], folders_by_id)}". '
            f"candidates: {listed}"
        )
    return matches[0]


def resolve_named_folder(folders: Sequence[KnowledgeFile], raw_path: str) -> tuple[KnowledgeFile, str]:
    parts = split_folder_path(raw_path)
    folders_by_id = {int(folder.id): folder for folder in folders if folder.id is not None}
    if len(parts) == 1:
        folder = resolve_unique_folder_by_name(folders, parts[0])
    else:
        folder = resolve_folder(folders, raw_path)
    return folder, folder_name_path(folder, folders_by_id)


async def find_spaces_by_name(
    session: AsyncSession,
    *,
    name: str,
    tenant_id: int | None,
) -> list[Knowledge]:
    normalized = name.strip()
    statement = (
        select(Knowledge)
        .where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            Knowledge.state != KnowledgeState.DELETING.value,
            func.trim(Knowledge.name) == normalized,
        )
        .order_by(col(Knowledge.id).asc())
    )
    if tenant_id is not None:
        statement = statement.where(Knowledge.tenant_id == tenant_id)
    result = await session.exec(statement)
    return list(result.all())


async def list_space_folders(session: AsyncSession, space_id: int) -> list[KnowledgeFile]:
    result = await session.exec(
        select(KnowledgeFile)
        .where(
            KnowledgeFile.knowledge_id == space_id,
            KnowledgeFile.file_type == FileType.DIR.value,
            col(KnowledgeFile.deleted_at).is_(None),
        )
        .order_by(col(KnowledgeFile.level).asc(), col(KnowledgeFile.id).asc())
    )
    return list(result.all())


async def resolve_target(
    session: AsyncSession,
    *,
    space_name: str,
    folder_path: str,
    tenant_id: int | None,
) -> ResolvedTarget:
    spaces = await find_spaces_by_name(session, name=space_name, tenant_id=tenant_id)
    if not spaces:
        suffix = f" tenant_id={tenant_id}" if tenant_id is not None else ""
        raise TargetLookupError(f'knowledge space "{space_name}" not found{suffix}')
    if len(spaces) > 1:
        listed = "; ".join(_format_space(space) for space in spaces)
        raise TargetLookupError(f'knowledge space "{space_name}" is not unique; pass --tenant-id. candidates: {listed}')
    space = spaces[0]
    if space.id is None:
        raise TargetLookupError(f'knowledge space "{space_name}" has no id')
    folders = await list_space_folders(session, int(space.id))
    folder, folder_path_names = resolve_named_folder(folders, folder_path)
    return ResolvedTarget(space=space, folder=folder, folder_path=folder_path_names)


def eligible_statuses(*, include_timeout: bool) -> tuple[int, ...]:
    statuses = [KnowledgeFileStatus.FAILED.value]
    if include_timeout:
        statuses.append(KnowledgeFileStatus.TIMEOUT.value)
    return tuple(statuses)


def print_failed_files(files: Sequence[KnowledgeFile]) -> None:
    if not files:
        print("No failed files under this folder.")
        return
    print(f"Failed files ({len(files)}):")
    for record in files:
        remark = (record.remark or "").replace("\n", " ").strip()
        if len(remark) > _REMARK_DISPLAY_LIMIT:
            remark = f"{remark[:_REMARK_DISPLAY_LIMIT]}..."
        status_name = KnowledgeFileStatus(record.status).name if record.status is not None else "UNKNOWN"
        print(f"  file_id={record.id} status={status_name} file_name={record.file_name} remark={remark or '-'}")


async def run(args: argparse.Namespace) -> int:
    statuses = eligible_statuses(include_timeout=args.include_timeout)
    try:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                try:
                    target = await resolve_target(
                        session,
                        space_name=args.space_name,
                        folder_path=args.folder,
                        tenant_id=args.tenant_id,
                    )
                except TargetLookupError as exc:
                    print(f"[ERROR] {exc}", file=sys.stderr)
                    return 1

                print(
                    f"[INFO] space {_format_space(target.space)}; "
                    f"folder id={target.folder.id} path={target.folder_path}"
                )
                selection = await collect_candidate_files(
                    session,
                    folder_ids=[int(target.folder.id)],
                    eligible_statuses=statuses,
                )

        print_failed_files(selection.selected_files)
        print_selection_report(selection)
        if args.include_timeout:
            print("[INFO] selecting FAILED and TIMEOUT files.")
        else:
            print("[INFO] selecting FAILED files only.")

        report = apply_selection(
            selection,
            apply=args.apply,
            eligible_statuses=statuses,
        )
        return exit_code_for_report(report) if report is not None else 0
    finally:
        await close_app_context()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
