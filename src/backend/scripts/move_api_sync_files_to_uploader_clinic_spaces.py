#!/usr/bin/env python3
"""Move API-sync files into each uploader's clinic knowledge space.

Looks up a knowledge space and folder (possibly nested) by name, selects
files whose ingest method is OpenAPI / filelib sync ("接口同步"), resolves
each uploader's clinic space the same way as filelib_sync
``responsible_person_id`` targeting, then copies those files into that
clinic space.

The destination folder is the input folder path. Missing segments are
created in the clinic space. Nested source files are flattened into that
path. Default mode is dry-run; pass ``--apply`` to write.

Usage (from ``src/backend``):

    export config=/path/to/config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/move_api_sync_files_to_uploader_clinic_spaces.py \\
      --space-name "安全生产知识库" --folder "安全生产/消防安全"
    PYTHONPATH=./ .venv/bin/python scripts/move_api_sync_files_to_uploader_clinic_spaces.py \\
      --space-name "安全生产知识库" --folder "安全生产/消防安全" --apply
    bash scripts/move_api_sync_files_to_uploader_clinic_spaces.sh \\
      --space-name "安全生产知识库" --folder "消防安全" --tenant-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.user.domain.models.user import User  # noqa: E402
from scripts.audit_api_sync_uploader_clinic_spaces import (  # noqa: E402
    MissingClinicSpaceUser,
    build_uploader_audits,
    close_resources,
    collect_chain_ids,
    display_fields,
    is_api_sync_file,
    list_folder_files,
    load_bindings_by_department,
    load_departments,
    load_scopes,
    load_spaces,
    load_user_departments,
    load_users,
    primary_clinic_snapshot,
    resolve_uploader_id,
)
from scripts.move_knowledge_space_files import (  # noqa: E402
    BishengMoveOperations,
    TargetContext,
    _folder_child_path,
    _replace_resource_permission_tuples,
    _tenant_scope,
    move_one_file,
)
from scripts.retry_failed_knowledge_space_folder_files import (  # noqa: E402
    TargetLookupError,
    is_space_root_path,
    resolve_target,
    split_folder_path,
)

_MAX_FOLDER_DEPTH = 10


@dataclass
class MoveRow:
    source_file_id: int
    source_file_name: str
    uploader: str
    uploader_id: int | None
    department_name: str
    clinic_space_id: int | None
    clinic_space_name: str
    target_folder_path: str
    folder_action: str
    status: str
    reason: str
    target_file_id: int | None = None


@dataclass
class MoveReport:
    mode: str
    space_id: int
    space_name: str
    folder_path: str
    api_sync_file_count: int
    ready_count: int
    skipped_count: int
    success_count: int
    failed_count: int
    rows: list[MoveRow] = field(default_factory=list)


class ClinicMoveOperations(BishengMoveOperations):
    """Same copy/delete saga, but root files parent to the clinic space."""

    async def write_permissions(self, target_file: KnowledgeFile, target: TargetContext) -> None:
        if int(getattr(target.folder, "id", 0) or 0) <= 0:
            object_ref = f"knowledge_file:{target_file.id}"
            await _replace_resource_permission_tuples(
                object_ref,
                (
                    {
                        "user": f"user:{target.owner.user_id}",
                        "relation": "owner",
                        "object": object_ref,
                    },
                    {
                        "user": f"knowledge_space:{int(target.space.id)}",
                        "relation": "parent",
                        "object": object_ref,
                    },
                ),
            )
            return
        await super().write_permissions(target_file, target)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space-name", required=True, help="source knowledge-space display name")
    parser.add_argument(
        "--folder",
        required=True,
        help='folder name, nested path, or "/" for the whole knowledge space',
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
        help="write folders and move files; default is dry-run",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format; default is text",
    )
    return parser.parse_args(argv)


def target_folder_segments(folder_path: str) -> list[str]:
    if is_space_root_path(folder_path):
        return []
    return split_folder_path(folder_path)


def _normalize_parent_path(path: str | None) -> str:
    return (path or "").rstrip("/")


def _is_root_parent(path: str | None) -> bool:
    return _normalize_parent_path(path) == ""


def find_folder_by_segments(
    folders: Sequence[KnowledgeFile],
    segments: Sequence[str],
) -> KnowledgeFile | None:
    if not segments:
        return None
    parent_path = ""
    current: KnowledgeFile | None = None
    for name in segments:
        matches = [
            folder
            for folder in folders
            if folder.file_name == name
            and (
                _is_root_parent(folder.file_level_path)
                if parent_path == ""
                else _normalize_parent_path(folder.file_level_path) == parent_path
            )
        ]
        if len(matches) != 1:
            return None
        current = matches[0]
        parent_path = _folder_child_path(current)
    return current


def _target_file_parent_path(folder: KnowledgeFile | None) -> str:
    if folder is None:
        return ""
    return _folder_child_path(folder)


def _files_in_folder(files: Sequence[KnowledgeFile], folder: KnowledgeFile | None) -> list[KnowledgeFile]:
    parent = _target_file_parent_path(folder)
    rows: list[KnowledgeFile] = []
    for record in files:
        path = _normalize_parent_path(record.file_level_path)
        if parent == "":
            if path == "":
                rows.append(record)
            continue
        if path == parent:
            rows.append(record)
    return rows


def _file_status(record: KnowledgeFile) -> int:
    return int(getattr(record, "status", 0) or 0)


def plan_moves(
    *,
    source_space: Knowledge,
    folder_path: str,
    api_sync_files: Sequence[KnowledgeFile],
    uploader_rows: Sequence[MissingClinicSpaceUser],
    clinic_spaces: dict[int, Knowledge],
    clinic_owners: dict[int, User],
    clinic_folders: dict[int, list[KnowledgeFile]],
    clinic_files: dict[int, list[KnowledgeFile]],
) -> list[MoveRow]:
    segments = target_folder_segments(folder_path)
    display_folder = "/" if not segments else "/".join(segments)
    rows_by_user: dict[int | None, MissingClinicSpaceUser] = {item.user_id: item for item in uploader_rows}
    reserved_names: dict[tuple[int, str], int] = {}
    planned: list[MoveRow] = []

    for record in api_sync_files:
        file_id = int(record.id or 0)
        file_name = str(record.file_name or "")
        uploader_id = resolve_uploader_id(record)
        uploader_row = rows_by_user.get(uploader_id)
        fields = (
            display_fields(uploader_row)
            if uploader_row is not None
            else {"uploader": "-", "department_name": "-", "clinic_space_name": "-"}
        )
        row = MoveRow(
            source_file_id=file_id,
            source_file_name=file_name,
            uploader=fields["uploader"],
            uploader_id=uploader_id,
            department_name=fields["department_name"],
            clinic_space_id=None,
            clinic_space_name=fields["clinic_space_name"],
            target_folder_path=display_folder,
            folder_action="none",
            status="skipped",
            reason="",
        )
        if uploader_row is None:
            row.reason = "missing_uploader"
            planned.append(row)
            continue
        if uploader_row.reason != "has_clinic_space":
            row.reason = uploader_row.reason
            planned.append(row)
            continue
        clinic_snap = primary_clinic_snapshot(uploader_row.departments)
        if clinic_snap is None or clinic_snap.clinic_space_id is None:
            row.reason = "no_clinic_space"
            planned.append(row)
            continue
        clinic = clinic_spaces.get(int(clinic_snap.clinic_space_id))
        row.clinic_space_id = int(clinic_snap.clinic_space_id)
        row.clinic_space_name = clinic_snap.clinic_space_name or fields["clinic_space_name"]
        if clinic is None:
            row.reason = "clinic_space_missing"
            planned.append(row)
            continue
        if int(clinic.tenant_id or 1) != int(source_space.tenant_id or 1):
            row.reason = "clinic_tenant_mismatch"
            planned.append(row)
            continue
        owner = clinic_owners.get(int(clinic.user_id or 0))
        if owner is None or int(owner.delete or 0) != 0:
            row.reason = "clinic_owner_missing"
            planned.append(row)
            continue
        if str(source_space.model or "") != str(clinic.model or ""):
            row.reason = "embedding_model_mismatch"
            planned.append(row)
            continue
        if len(segments) > _MAX_FOLDER_DEPTH:
            row.reason = "folder_too_deep"
            planned.append(row)
            continue
        if _file_status(record) != KnowledgeFileStatus.SUCCESS.value:
            row.reason = "source_not_success"
            planned.append(row)
            continue
        if int(record.knowledge_id) == int(clinic.id or 0):
            row.reason = "already_in_clinic_space"
            planned.append(row)
            continue
        existing_folder = find_folder_by_segments(clinic_folders.get(int(clinic.id), []), segments)
        if not segments:
            row.folder_action = "none"
        elif existing_folder is None:
            row.folder_action = "create"
        else:
            row.folder_action = "reused"
        target_files = _files_in_folder(clinic_files.get(int(clinic.id), []), existing_folder)
        if any(item.file_name == file_name for item in target_files):
            row.reason = "target_name_conflict"
            planned.append(row)
            continue
        reserve_key = (int(clinic.id), file_name)
        if reserve_key in reserved_names:
            row.reason = "batch_name_conflict"
            planned.append(row)
            continue
        reserved_names[reserve_key] = file_id
        row.status = "ready"
        row.reason = "ready"
        planned.append(row)
    return planned


def build_clinic_target_context(
    *,
    tenant_id: int,
    space: Knowledge,
    folder: KnowledgeFile | None,
    owner: User,
) -> TargetContext:
    if folder is None:
        sentinel = KnowledgeFile(
            id=0,
            knowledge_id=int(space.id or 0),
            file_name="",
            file_type=FileType.DIR.value,
            file_level_path="",
            level=-1,
        )
        return TargetContext(
            tenant_id=tenant_id,
            space=space,
            folder=sentinel,
            owner=owner,
            file_level_path="",
            level=0,
        )
    return TargetContext(
        tenant_id=tenant_id,
        space=space,
        folder=folder,
        owner=owner,
        file_level_path=_folder_child_path(folder),
        level=int(folder.level or 0) + 1,
    )


async def _create_folder(
    *,
    space: Knowledge,
    owner: User,
    name: str,
    parent: KnowledgeFile | None,
) -> KnowledgeFile:
    if parent is None:
        level = 0
        file_level_path = ""
        parent_ref = f"knowledge_space:{int(space.id)}"
    else:
        level = int(parent.level or 0) + 1
        if level > _MAX_FOLDER_DEPTH:
            raise RuntimeError(f"folder depth exceeds {_MAX_FOLDER_DEPTH}")
        file_level_path = _folder_child_path(parent)
        parent_ref = f"folder:{int(parent.id)}"
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    folder = await KnowledgeFileDao.aadd_file(
        KnowledgeFile(
            tenant_id=int(space.tenant_id or 1),
            knowledge_id=int(space.id or 0),
            user_id=int(owner.user_id),
            user_name=owner.user_name,
            updater_id=int(owner.user_id),
            updater_name=owner.user_name,
            file_name=name,
            file_type=FileType.DIR.value,
            level=level,
            file_level_path=file_level_path,
            status=KnowledgeFileStatus.SUCCESS.value,
        )
    )
    object_ref = f"folder:{int(folder.id)}"
    await _replace_resource_permission_tuples(
        object_ref,
        (
            {"user": f"user:{owner.user_id}", "relation": "owner", "object": object_ref},
            {"user": parent_ref, "relation": "parent", "object": object_ref},
        ),
    )
    return folder


async def ensure_folder_path(
    *,
    space: Knowledge,
    owner: User,
    segments: Sequence[str],
    folders: list[KnowledgeFile],
    apply: bool,
) -> KnowledgeFile | None:
    if not segments:
        return None
    existing = find_folder_by_segments(folders, segments)
    if existing is not None:
        return existing
    if not apply:
        return None
    parent: KnowledgeFile | None = None
    walked: list[str] = []
    for name in segments:
        walked.append(name)
        current = find_folder_by_segments(folders, walked)
        if current is None:
            current = await _create_folder(space=space, owner=owner, name=name, parent=parent)
            folders.append(current)
        parent = current
    return parent


async def load_space_files(session: AsyncSession, space_ids: Iterable[int]) -> dict[int, list[KnowledgeFile]]:
    ids = sorted({int(space_id) for space_id in space_ids})
    grouped: dict[int, list[KnowledgeFile]] = {space_id: [] for space_id in ids}
    if not ids:
        return grouped
    result = await session.exec(
        select(KnowledgeFile).where(
            col(KnowledgeFile.knowledge_id).in_(ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.deleted_at).is_(None),
        )
    )
    for record in result.all():
        grouped[int(record.knowledge_id)].append(record)
    return grouped


async def load_space_folders(session: AsyncSession, space_ids: Iterable[int]) -> dict[int, list[KnowledgeFile]]:
    ids = sorted({int(space_id) for space_id in space_ids})
    grouped: dict[int, list[KnowledgeFile]] = {space_id: [] for space_id in ids}
    if not ids:
        return grouped
    result = await session.exec(
        select(KnowledgeFile).where(
            col(KnowledgeFile.knowledge_id).in_(ids),
            KnowledgeFile.file_type == FileType.DIR.value,
            col(KnowledgeFile.deleted_at).is_(None),
        )
    )
    for record in result.all():
        grouped[int(record.knowledge_id)].append(record)
    return grouped


def report_to_dict(report: MoveReport) -> dict[str, Any]:
    return {
        "mode": report.mode,
        "space": {"id": report.space_id, "name": report.space_name},
        "folder_path": report.folder_path,
        "api_sync_file_count": report.api_sync_file_count,
        "ready_count": report.ready_count,
        "skipped_count": report.skipped_count,
        "success_count": report.success_count,
        "failed_count": report.failed_count,
        "rows": [asdict(row) for row in report.rows],
    }


def print_text_report(report: MoveReport) -> None:
    print(f"[INFO] mode={report.mode} space id={report.space_id} name={report.space_name} folder={report.folder_path}")
    print(
        f"[INFO] api-sync files={report.api_sync_file_count} ready={report.ready_count} "
        f"skipped={report.skipped_count} migrated={report.success_count} failed={report.failed_count}"
    )
    if not report.rows:
        print("No API-sync files.")
        return
    for row in report.rows:
        if row.status == "skipped":
            print(
                f"跳过 文件={row.source_file_name} 上传人={row.uploader} "
                f"科室名称={row.department_name} 科室库名称={row.clinic_space_name} 原因={row.reason}"
            )
            continue
        print(
            f"迁移文件={row.source_file_name} 科室库名称={row.clinic_space_name} "
            f"上传人={row.uploader} 科室名称={row.department_name} "
            f"目录={row.target_folder_path} status={row.status}"
        )


async def _discover(
    args: argparse.Namespace,
) -> tuple[
    Knowledge,
    str,
    list[KnowledgeFile],
    list[MoveRow],
    dict[int, Knowledge],
    dict[int, User],
    dict[int, list[KnowledgeFile]],
]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            target = await resolve_target(
                session,
                space_name=args.space_name,
                folder_path=args.folder,
                tenant_id=args.tenant_id,
            )
            files = await list_folder_files(
                session,
                space_id=int(target.space.id),
                folder=target.folder,
            )
            api_sync_files = [record for record in files if is_api_sync_file(record)]
            uploader_ids = [
                user_id for user_id in {resolve_uploader_id(record) for record in api_sync_files} if user_id is not None
            ]
            users = await load_users(session, uploader_ids)
            memberships_by_user = await load_user_departments(session, uploader_ids)
            membership_department_ids = {
                int(row.department_id) for rows in memberships_by_user.values() for row in rows
            }
            departments = await load_departments(session, membership_department_ids)
            chain_ids = collect_chain_ids(departments, membership_department_ids)
            ancestor_ids = chain_ids - set(departments)
            if ancestor_ids:
                departments.update(await load_departments(session, ancestor_ids))
            bindings = await load_bindings_by_department(session, chain_ids)
            binding_space_ids = {int(binding.space_id) for rows in bindings.values() for binding in rows}
            clinic_spaces = await load_spaces(session, binding_space_ids)
            scopes = await load_scopes(session, binding_space_ids)
            with_clinic, missing = build_uploader_audits(
                api_sync_files,
                users=users,
                memberships_by_user=memberships_by_user,
                departments=departments,
                bindings=bindings,
                spaces=clinic_spaces,
                sample_limit=8,
                scopes=scopes,
            )
            owner_ids = [int(space.user_id) for space in clinic_spaces.values() if space.user_id is not None]
            clinic_owners = await load_users(session, owner_ids)
            clinic_ids = [int(space.id) for space in clinic_spaces.values() if space.id is not None]
            clinic_folders = await load_space_folders(session, clinic_ids)
            clinic_files = await load_space_files(session, clinic_ids)
            rows = plan_moves(
                source_space=target.space,
                folder_path=target.folder_path,
                api_sync_files=api_sync_files,
                uploader_rows=[*with_clinic, *missing],
                clinic_spaces=clinic_spaces,
                clinic_owners=clinic_owners,
                clinic_folders=clinic_folders,
                clinic_files=clinic_files,
            )
            return target.space, target.folder_path, api_sync_files, rows, clinic_spaces, clinic_owners, clinic_folders


async def _apply_moves(
    *,
    source_space: Knowledge,
    folder_path: str,
    api_sync_files: Sequence[KnowledgeFile],
    rows: list[MoveRow],
    clinic_spaces: dict[int, Knowledge],
    clinic_owners: dict[int, User],
    clinic_folders: dict[int, list[KnowledgeFile]],
) -> None:
    tenant_id = int(source_space.tenant_id or 1)
    files_by_id = {int(record.id): record for record in api_sync_files if record.id is not None}
    segments = target_folder_segments(folder_path)
    operations = ClinicMoveOperations(tenant_id, {int(source_space.id): source_space})
    with _tenant_scope(tenant_id):
        for row in rows:
            if row.status != "ready" or row.clinic_space_id is None:
                continue
            clinic = clinic_spaces.get(int(row.clinic_space_id))
            owner = clinic_owners.get(int(clinic.user_id or 0)) if clinic is not None else None
            source_file = files_by_id.get(row.source_file_id)
            if clinic is None or owner is None or source_file is None:
                row.status = "failed"
                row.reason = "apply_context_missing"
                continue
            folders = clinic_folders.setdefault(int(clinic.id), [])
            try:
                folder = await ensure_folder_path(
                    space=clinic,
                    owner=owner,
                    segments=segments,
                    folders=folders,
                    apply=True,
                )
                target = build_clinic_target_context(
                    tenant_id=tenant_id,
                    space=clinic,
                    folder=folder,
                    owner=owner,
                )
                result = await move_one_file(source_file, target, operations)
            except Exception as exc:
                row.status = "failed"
                row.reason = f"{type(exc).__name__}: {exc}"
                continue
            if result.status == "success":
                row.status = "success"
                row.reason = "migrated"
                row.target_file_id = result.target_file_id
                row.folder_action = "reused" if folder is not None or not segments else "none"
            else:
                row.status = "failed"
                row.reason = result.error or result.reason_code or "move_failed"
                row.target_file_id = result.target_file_id


async def collect_report(args: argparse.Namespace) -> tuple[MoveReport | None, int]:
    try:
        source_space, folder_path, api_sync_files, rows, clinic_spaces, clinic_owners, clinic_folders = await _discover(
            args
        )
        if args.apply:
            await initialize_app_context(config=settings)
            await _apply_moves(
                source_space=source_space,
                folder_path=folder_path,
                api_sync_files=api_sync_files,
                rows=rows,
                clinic_spaces=clinic_spaces,
                clinic_owners=clinic_owners,
                clinic_folders=clinic_folders,
            )
        report = MoveReport(
            mode="apply" if args.apply else "dry-run",
            space_id=int(source_space.id),
            space_name=source_space.name,
            folder_path=folder_path,
            api_sync_file_count=len(api_sync_files),
            ready_count=sum(1 for row in rows if row.status == "ready"),
            skipped_count=sum(1 for row in rows if row.status == "skipped"),
            success_count=sum(1 for row in rows if row.status == "success"),
            failed_count=sum(1 for row in rows if row.status == "failed"),
            rows=rows,
        )
        return report, 0
    except TargetLookupError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return None, 1
    finally:
        await close_resources()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report, code = asyncio.run(collect_report(args))
    if code != 0 or report is None:
        return code
    if args.format == "json":
        print(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2))
    else:
        print_text_report(report)
        if report.mode == "dry-run":
            print("[INFO] dry-run only; re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
