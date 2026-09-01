#!/usr/bin/env python3
"""Audit API-sync files whose uploaders have no clinic knowledge space.

Looks up a knowledge space by display name, resolves a (possibly nested)
folder by name path, lists files under that folder (including nested
subfolders) whose ingest method is OpenAPI / filelib sync ("接口同步"),
then checks whether each uploader currently has a clinic knowledge space
(科室库).

Clinic lookup matches filelib_sync ``responsible_person_id`` targeting: walk
the primary department path from self to root and take the first
organization that has a clinic binding (team / team_ks + owner=user).
org_level is not consulted. Users with no such binding are reported once
at the end. This script is read-only.

Folder paths use ``/`` (also ``>`` or ``->``). A single unique folder name
in the space is accepted without the full path. Pass ``--folder /`` to scan
the entire knowledge space.

Usage (from ``src/backend``):

    export config=/path/to/config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/audit_api_sync_uploader_clinic_spaces.py \\
      --space-name "安全生产知识库" --folder "安全生产/消防安全"
    PYTHONPATH=./ .venv/bin/python scripts/audit_api_sync_uploader_clinic_spaces.py \\
      --space-name "安全生产知识库" --folder / --format json
    bash scripts/audit_api_sync_uploader_clinic_spaces.sh \\
      --space-name "安全生产知识库" --folder "消防安全" --tenant-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.database.manager import get_database_connection  # noqa: E402
from bisheng.database.models.department import Department, UserDepartment  # noqa: E402
from bisheng.knowledge.domain.models.department_knowledge_space import (  # noqa: E402
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_space_scope import (  # noqa: E402
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.user.domain.models.user import User  # noqa: E402
from scripts.reparse_knowledge_space_files import _folder_descendant_prefix  # noqa: E402
from scripts.retry_failed_knowledge_space_folder_files import (  # noqa: E402
    TargetLookupError,
    resolve_target,
)

_IN_CHUNK = 500
_SAMPLE_FILE_LIMIT_DEFAULT = 8


@dataclass
class DepartmentSnapshot:
    department_id: int
    name: str
    dept_id: str
    path: str
    status: str
    is_primary: bool
    clinic_space_id: int | None = None
    clinic_space_name: str | None = None
    clinic_bound_department_id: int | None = None
    clinic_bound_department_name: str | None = None


@dataclass
class SyncDepartmentSnapshot:
    department_id: int | None
    name: str


@dataclass
class MissingClinicSpaceUser:
    user_id: int | None
    user_name: str | None
    user_exists: bool
    delete: int | None
    reason: str
    departments: list[DepartmentSnapshot]
    file_count: int
    sample_file_ids: list[int]
    sync_departments: list[SyncDepartmentSnapshot] = field(default_factory=list)


@dataclass
class AuditReport:
    space_id: int
    space_tenant_id: int | None
    space_name: str
    folder_path: str
    folder_id: int | None
    file_count: int
    api_sync_file_count: int
    uploader_count: int
    missing_users: list[MissingClinicSpaceUser]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space-name", required=True, help="knowledge-space display name")
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
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format; default is text",
    )
    parser.add_argument(
        "--sample-files",
        type=int,
        default=_SAMPLE_FILE_LIMIT_DEFAULT,
        help="max file IDs to show per missing user (default: 8)",
    )
    return parser.parse_args(argv)


def _as_metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def is_api_sync_file(file: KnowledgeFile) -> bool:
    """Match portal ingest-method label 接口同步."""
    if file.file_type == FileType.DIR.value:
        return False
    meta = _as_metadata_dict(file.user_metadata)
    return bool(meta.get("filelib_sync_endpoint") or meta.get("external_file_id"))


def resolve_uploader_id(file: KnowledgeFile) -> int | None:
    if file.original_uploader_id:
        return int(file.original_uploader_id)
    if file.user_id:
        return int(file.user_id)
    return None


def sync_department_from_file(file: KnowledgeFile) -> SyncDepartmentSnapshot:
    meta = _as_metadata_dict(file.user_metadata)
    raw_id = meta.get("department_id")
    department_id: int | None
    try:
        department_id = int(raw_id) if raw_id is not None and str(raw_id).strip() != "" else None
    except (TypeError, ValueError):
        department_id = None
    name = str(meta.get("department") or "").strip()
    return SyncDepartmentSnapshot(department_id=department_id, name=name)


def missing_reason(*, user_exists: bool, user_id: int | None, departments: Sequence[DepartmentSnapshot]) -> str:
    if user_id is None:
        return "missing_uploader"
    if not user_exists:
        return "user_not_found"
    if not departments:
        return "no_department"
    return "no_clinic_space"


def department_chain_ids(department: Any) -> list[int]:
    """Self → parent → root, matching FilelibSyncService._department_chain."""
    raw_id = getattr(department, "id", None)
    if raw_id is None:
        return []
    dept_id = int(raw_id)
    path_ids = [int(part) for part in str(getattr(department, "path", "") or "").split("/") if part.strip().isdigit()]
    if dept_id not in path_ids:
        path_ids.append(dept_id)
    return list(dict.fromkeys(reversed(path_ids)))


def is_clinic_binding_scope(scope: Any) -> bool:
    """Same clinic-space rule as DepartmentSpaceTargetResolver._is_clinic_scope."""
    if scope is None:
        return False
    return KnowledgeSpaceLevelEnum.is_team_level(getattr(scope, "level", None)) and (
        getattr(scope, "owner_type", None) == KnowledgeSpaceOwnerTypeEnum.USER
    )


def _bindings_for_department(bindings: dict[int, Any], department_id: int) -> list[Any]:
    raw = bindings.get(int(department_id))
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    return [raw]


def resolve_nearest_clinic(
    chain_ids: Sequence[int],
    *,
    bindings: dict[int, Any],
    scopes: dict[int, Any],
    spaces: dict[int, Any],
) -> tuple[Any | None, int | None]:
    """Return (space, bound_department_id) for the first clinic library on the chain."""
    for department_id in chain_ids:
        candidates: list[Any] = []
        for binding in _bindings_for_department(bindings, int(department_id)):
            space_id = int(getattr(binding, "space_id", 0) or 0)
            space = spaces.get(space_id)
            if space is None:
                continue
            if is_clinic_binding_scope(scopes.get(space_id)):
                candidates.append(space)
        if candidates:
            space = sorted(candidates, key=lambda item: int(item.id))[0]
            return space, int(department_id)
    return None, None


def collect_chain_ids(departments: dict[int, Any], department_ids: Iterable[int]) -> set[int]:
    chain_ids: set[int] = set()
    for department_id in department_ids:
        department = departments.get(int(department_id))
        if department is None:
            chain_ids.add(int(department_id))
            continue
        chain_ids.update(department_chain_ids(department))
    return chain_ids


def _chunks(values: Iterable[int], size: int = _IN_CHUNK) -> list[list[int]]:
    items = sorted({int(value) for value in values})
    return [items[index : index + size] for index in range(0, len(items), size)]


async def list_folder_files(
    session: AsyncSession,
    *,
    space_id: int,
    folder: KnowledgeFile | None,
) -> list[KnowledgeFile]:
    conditions = [
        KnowledgeFile.knowledge_id == space_id,
        KnowledgeFile.file_type == FileType.FILE.value,
        col(KnowledgeFile.deleted_at).is_(None),
    ]
    if folder is not None:
        prefix = _folder_descendant_prefix(folder)
        conditions.append(
            or_(
                KnowledgeFile.file_level_path == prefix,
                col(KnowledgeFile.file_level_path).like(f"{prefix}/%"),
            )
        )
    result = await session.exec(select(KnowledgeFile).where(*conditions).order_by(col(KnowledgeFile.id).asc()))
    return list(result.all())


async def _load_by_ids(
    session: AsyncSession,
    model: type,
    id_attr: str,
    ids: Iterable[int],
) -> list[Any]:
    rows: list[Any] = []
    column = getattr(model, id_attr)
    for chunk in _chunks(ids):
        result = await session.exec(select(model).where(col(column).in_(chunk)))
        rows.extend(result.all())
    return rows


async def load_users(session: AsyncSession, user_ids: Iterable[int]) -> dict[int, User]:
    users = await _load_by_ids(session, User, "user_id", user_ids)
    return {int(user.user_id): user for user in users if user.user_id is not None}


async def load_user_departments(
    session: AsyncSession,
    user_ids: Iterable[int],
) -> dict[int, list[UserDepartment]]:
    grouped: dict[int, list[UserDepartment]] = defaultdict(list)
    rows = await _load_by_ids(session, UserDepartment, "user_id", user_ids)
    for row in rows:
        grouped[int(row.user_id)].append(row)
    return grouped


async def load_departments(session: AsyncSession, department_ids: Iterable[int]) -> dict[int, Department]:
    departments = await _load_by_ids(session, Department, "id", department_ids)
    return {int(department.id): department for department in departments if department.id is not None}


async def load_bindings_by_department(
    session: AsyncSession,
    department_ids: Iterable[int],
) -> dict[int, list[DepartmentKnowledgeSpace]]:
    grouped: dict[int, list[DepartmentKnowledgeSpace]] = defaultdict(list)
    rows = await _load_by_ids(session, DepartmentKnowledgeSpace, "department_id", department_ids)
    for row in rows:
        grouped[int(row.department_id)].append(row)
    return grouped


async def load_scopes(session: AsyncSession, space_ids: Iterable[int]) -> dict[int, KnowledgeSpaceScope]:
    rows = await _load_by_ids(session, KnowledgeSpaceScope, "space_id", space_ids)
    return {int(row.space_id): row for row in rows if row.space_id is not None}


async def load_spaces(session: AsyncSession, space_ids: Iterable[int]) -> dict[int, Knowledge]:
    spaces = await _load_by_ids(session, Knowledge, "id", space_ids)
    return {
        int(space.id): space
        for space in spaces
        if space.id is not None
        and space.type == KnowledgeTypeEnum.SPACE.value
        and space.state != KnowledgeState.DELETING.value
    }


def build_department_snapshots(
    memberships: Sequence[UserDepartment],
    departments: dict[int, Any],
    bindings: dict[int, Any],
    spaces: dict[int, Any],
    scopes: dict[int, Any],
) -> list[DepartmentSnapshot]:
    snapshots: list[DepartmentSnapshot] = []
    for membership in sorted(
        memberships,
        key=lambda row: (0 if int(row.is_primary or 0) == 1 else 1, int(row.department_id)),
    ):
        department = departments.get(int(membership.department_id))
        chain_ids = department_chain_ids(department) if department is not None else [int(membership.department_id)]
        space, bound_department_id = resolve_nearest_clinic(
            chain_ids,
            bindings=bindings,
            scopes=scopes,
            spaces=spaces,
        )
        bound_department = departments.get(int(bound_department_id)) if bound_department_id is not None else None
        snapshots.append(
            DepartmentSnapshot(
                department_id=int(membership.department_id),
                name=department.name if department is not None else f"#{membership.department_id}",
                dept_id=department.dept_id if department is not None else "",
                path=department.path if department is not None else "",
                status=department.status if department is not None else "missing",
                is_primary=int(membership.is_primary or 0) == 1,
                clinic_space_id=int(space.id) if space is not None and getattr(space, "id", None) is not None else None,
                clinic_space_name=space.name if space is not None else None,
                clinic_bound_department_id=bound_department_id,
                clinic_bound_department_name=(
                    bound_department.name
                    if bound_department is not None
                    else (f"#{bound_department_id}" if bound_department_id is not None else None)
                ),
            )
        )
    return snapshots


def unique_sync_departments(files: Sequence[KnowledgeFile]) -> list[SyncDepartmentSnapshot]:
    seen: dict[tuple[int | None, str], SyncDepartmentSnapshot] = {}
    for record in files:
        snapshot = sync_department_from_file(record)
        key = (snapshot.department_id, snapshot.name)
        if key not in seen and (snapshot.department_id is not None or snapshot.name):
            seen[key] = snapshot
    return list(seen.values())


def user_has_clinic_space(snapshots: Sequence[DepartmentSnapshot]) -> bool:
    """Match filelib_sync: clinic lookup starts from the primary department chain."""
    primary = [item for item in snapshots if item.is_primary]
    pool = primary or list(snapshots)
    return any(item.clinic_space_id is not None for item in pool)


def build_missing_users(
    api_sync_files: Sequence[KnowledgeFile],
    *,
    users: dict[int, User],
    memberships_by_user: dict[int, list[UserDepartment]],
    departments: dict[int, Any],
    bindings: dict[int, Any],
    spaces: dict[int, Any],
    sample_limit: int,
    scopes: dict[int, Any] | None = None,
) -> list[MissingClinicSpaceUser]:
    files_by_user: dict[int | None, list[KnowledgeFile]] = defaultdict(list)
    for record in api_sync_files:
        files_by_user[resolve_uploader_id(record)].append(record)
    scope_map = scopes or {}

    missing: list[MissingClinicSpaceUser] = []
    for user_id, records in files_by_user.items():
        memberships = memberships_by_user.get(int(user_id), []) if user_id is not None else []
        snapshots = build_department_snapshots(memberships, departments, bindings, spaces, scope_map)
        if user_id is not None and user_has_clinic_space(snapshots):
            continue
        user = users.get(int(user_id)) if user_id is not None else None
        fallback_name = next((record.user_name for record in records if record.user_name), None)
        sample_ids = [int(record.id) for record in records if record.id is not None][: max(sample_limit, 0)]
        missing.append(
            MissingClinicSpaceUser(
                user_id=user_id,
                user_name=user.user_name if user is not None else fallback_name,
                user_exists=user is not None,
                delete=int(user.delete) if user is not None else None,
                reason=missing_reason(user_exists=user is not None, user_id=user_id, departments=snapshots),
                departments=snapshots,
                file_count=len(records),
                sample_file_ids=sample_ids,
                sync_departments=unique_sync_departments(records),
            )
        )
    missing.sort(key=lambda item: (item.user_id is None, item.user_id or 0, item.user_name or ""))
    return missing


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    return {
        "space": {
            "id": report.space_id,
            "tenant_id": report.space_tenant_id,
            "name": report.space_name,
        },
        "folder_path": report.folder_path,
        "folder_id": report.folder_id,
        "file_count": report.file_count,
        "api_sync_file_count": report.api_sync_file_count,
        "uploader_count": report.uploader_count,
        "missing_clinic_space_user_count": len(report.missing_users),
        "users_without_clinic_space": [
            {
                "user_id": item.user_id,
                "user_name": item.user_name,
                "user_exists": item.user_exists,
                "delete": item.delete,
                "reason": item.reason,
                "file_count": item.file_count,
                "sample_file_ids": item.sample_file_ids,
                "departments": [
                    {
                        "id": department.department_id,
                        "name": department.name,
                        "dept_id": department.dept_id,
                        "path": department.path,
                        "status": department.status,
                        "is_primary": department.is_primary,
                        "clinic_space_id": department.clinic_space_id,
                        "clinic_space_name": department.clinic_space_name,
                        "clinic_bound_department_id": department.clinic_bound_department_id,
                        "clinic_bound_department_name": department.clinic_bound_department_name,
                    }
                    for department in item.departments
                ],
                "sync_departments": [
                    {"id": department.department_id, "name": department.name} for department in item.sync_departments
                ],
            }
            for item in report.missing_users
        ],
    }


def print_text_report(report: AuditReport) -> None:
    print(
        f"[INFO] space id={report.space_id} tenant_id={report.space_tenant_id} "
        f"name={report.space_name}; folder path={report.folder_path}"
        + (f" folder_id={report.folder_id}" if report.folder_id is not None else "")
    )
    print(f"[INFO] files under folder={report.file_count}")
    print(f"[INFO] api-sync files={report.api_sync_file_count}")
    print(f"[INFO] unique uploaders={report.uploader_count}")
    print(f"[INFO] uploaders without clinic space={len(report.missing_users)}")
    if not report.missing_users:
        print("No uploaders without clinic knowledge space.")
        return
    print("Users without clinic knowledge space:")
    for item in report.missing_users:
        user_id = item.user_id if item.user_id is not None else "-"
        user_name = item.user_name or "-"
        delete = item.delete if item.delete is not None else "-"
        print(
            f"  user_id={user_id} user_name={user_name} exists={str(item.user_exists).lower()} "
            f"delete={delete} reason={item.reason} file_count={item.file_count}"
        )
        if item.departments:
            for department in item.departments:
                primary = "yes" if department.is_primary else "no"
                clinic = (
                    f"id={department.clinic_space_id} name={department.clinic_space_name}"
                    if department.clinic_space_id is not None
                    else "none"
                )
                if (
                    department.clinic_space_id is not None
                    and department.clinic_bound_department_id is not None
                    and int(department.clinic_bound_department_id) != int(department.department_id)
                ):
                    clinic += (
                        f" via department id={department.clinic_bound_department_id} "
                        f"name={department.clinic_bound_department_name or '-'}"
                    )
                print(
                    f"    department id={department.department_id} name={department.name} "
                    f"dept_id={department.dept_id or '-'} status={department.status} "
                    f"primary={primary} clinic_space={clinic}"
                )
        else:
            print("    departments: none")
        if item.sync_departments:
            listed = ", ".join(
                f"id={department.department_id if department.department_id is not None else '-'} "
                f"name={department.name or '-'}"
                for department in item.sync_departments
            )
            print(f"    sync_departments: {listed}")
        if item.sample_file_ids:
            print(f"    sample_file_ids: {','.join(str(file_id) for file_id in item.sample_file_ids)}")


async def close_resources() -> None:
    """Dispose the async pool before asyncio.run() closes the event loop.

    Scripts skip ``initialize_app_context``, so ``close_app_context()`` is a
    no-op and leftover aiomysql connections print ``Event loop is closed``.
    """
    try:
        connection = await get_database_connection()
        await connection.close()
    except Exception:
        # Best-effort teardown; interpreter shutdown would otherwise hide the
        # real script result behind an aiomysql "Event loop is closed" traceback.
        pass
    try:
        await close_app_context()
    except Exception:
        # App context is often uninitialized in scripts; ignore close failures.
        pass
    gc.collect()
    await asyncio.sleep(0)


async def collect_report(args: argparse.Namespace) -> tuple[AuditReport | None, int]:
    sample_limit = max(int(args.sample_files), 0)
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
                    return None, 1

                files = await list_folder_files(
                    session,
                    space_id=int(target.space.id),
                    folder=target.folder,
                )
                api_sync_files = [record for record in files if is_api_sync_file(record)]
                uploader_ids = {resolve_uploader_id(record) for record in api_sync_files}
                known_user_ids = [user_id for user_id in uploader_ids if user_id is not None]
                users = await load_users(session, known_user_ids)
                memberships_by_user = await load_user_departments(session, known_user_ids)
                membership_department_ids = {
                    int(row.department_id) for rows in memberships_by_user.values() for row in rows
                }
                departments = await load_departments(session, membership_department_ids)
                chain_ids = collect_chain_ids(departments, membership_department_ids)
                ancestor_ids = chain_ids - set(departments)
                if ancestor_ids:
                    departments.update(await load_departments(session, ancestor_ids))
                bindings = await load_bindings_by_department(session, chain_ids)
                space_ids = {int(binding.space_id) for rows in bindings.values() for binding in rows}
                spaces = await load_spaces(session, space_ids)
                scopes = await load_scopes(session, space_ids)
                missing_users = build_missing_users(
                    api_sync_files,
                    users=users,
                    memberships_by_user=memberships_by_user,
                    departments=departments,
                    bindings=bindings,
                    spaces=spaces,
                    sample_limit=sample_limit,
                    scopes=scopes,
                )
                report = AuditReport(
                    space_id=int(target.space.id),
                    space_tenant_id=target.space.tenant_id,
                    space_name=target.space.name,
                    folder_path=target.folder_path,
                    folder_id=int(target.folder.id) if target.folder is not None else None,
                    file_count=len(files),
                    api_sync_file_count=len(api_sync_files),
                    uploader_count=len(uploader_ids),
                    missing_users=missing_users,
                )
                return report, 0
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
