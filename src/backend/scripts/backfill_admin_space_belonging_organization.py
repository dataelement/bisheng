"""把 admin 在部门库、科室库、团队库中的文件所属组织改成该库对应的组织。

部门库「首钢集团有限公司现行财务制度汇编」不处理。
其他部门库只读 OpenFGA 关系 manager, 排除 admin 账号。
多名 manager 按成员管理页顺序取第一个: user_name 升序, 同名再按 user_id 升序。
该用户的唯一有效主组织如果是班组, 改用直接上级科室; 否则使用主组织本身。
科室库使用 department_knowledge_space.department_id, 且必须是有效科室。
团队库优先使用部门绑定或 owner 为部门的组织; 否则使用团队创建人的唯一有效主组织。
只改 user_id 为 admin 的文件行, 不改目录、收藏引用和投影墓碑, 不改 update_time。
已等于目标组织的不写。默认只预览。--apply 写完 MySQL 后, 再跑内容统计对账, 刷新 Elasticsearch 里的所属组织。

在 src/backend 执行:
  .venv/bin/python scripts/backfill_admin_space_belonging_organization.py --tenant-id 1 --output /tmp/admin-org-plan.jsonl
  .venv/bin/python scripts/backfill_admin_space_belonging_organization.py --plan /tmp/admin-org-plan.jsonl --apply --output /tmp/admin-org-write.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

SPACE_LEVELS = ("department", "team_ks", "team")
EXCLUDED_DEPARTMENT_SPACE_NAME = "首钢集团有限公司现行财务制度汇编"


def first_displayed_manager(managers: list[tuple[int, str]], admin_user_id: int) -> int | None:
    """Pick the first manager the member page shows, skipping the admin account.

    managers are (user_id, user_name) and already limited to OpenFGA manager users.
    The member page orders one role by user_name. user_id breaks equal names so a
    rerun selects the same person; the page itself has no third sort key.
    """
    eligible = [item for item in managers if int(item[0]) != int(admin_user_id)]
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item[1] or "", int(item[0])))
    return int(eligible[0][0])


def _value(item: Any) -> str:
    return str(getattr(item, "value", item))


class JsonlJournal:
    def __init__(self, path: str | Path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.file = os.fdopen(fd, "w", encoding="utf-8")

    def write(self, value: dict) -> None:
        self.file.write(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.file.close()


@contextmanager
def tenant_scope(tenant_id: int):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter

    if tenant_id <= 0:
        raise ValueError("tenant_id必须为正整数")
    token = set_current_tenant_id(tenant_id)
    try:
        with strict_tenant_filter():
            yield
    finally:
        current_tenant_id.reset(token)


def database_key(session) -> str:
    url = session.get_bind().url
    identity = (url.drivername, url.host, url.port, url.database)
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def usable_department(department: Any, tenant_id: int) -> bool:
    if department is None:
        return False
    return (
        int(department.tenant_id) == int(tenant_id)
        and str(department.status or "") == "active"
        and not int(department.is_deleted or 0)
    )


def organization_above_squad(department: Any, parent: Any, tenant_id: int) -> tuple[int | None, str]:
    """Use the manager primary organization, or its parent office when it is a squad."""
    if not usable_department(department, tenant_id):
        return None, "department_manager_organization_missing"
    if str(department.org_level or "") != "squad":
        return int(department.id), "ok"
    parent_id = getattr(department, "parent_id", None)
    if (
        parent_id is None
        or not usable_department(parent, tenant_id)
        or str(parent.org_level or "") != "office"
        or int(parent.id) != int(parent_id)
    ):
        return None, "department_manager_squad_parent_not_office"
    return int(parent.id), "ok"


def organization_for_space(
    *,
    level: str,
    owner_type: str,
    owner_id: int,
    binding_department_id: int | None,
    department: Any,
    creator_organization_id: int | None,
    tenant_id: int,
    excluded: bool = False,
    admin_organization_id: int | None = None,
    department_manager_reason: str | None = None,
) -> tuple[int | None, str]:
    """Return the organization id to store, and a reason when it cannot be stored."""
    if level == "department":
        if excluded:
            return None, "department_space_excluded"
        if admin_organization_id is None:
            return None, department_manager_reason or "department_manager_organization_missing"
        return int(admin_organization_id), "ok"
    if level == "team_ks":
        if binding_department_id is None:
            return None, "clinic_binding_missing"
        if not usable_department(department, tenant_id) or int(department.id) != int(binding_department_id):
            return None, "clinic_org_invalid"
        if department.org_level not in (None, "", "office"):
            return None, "clinic_org_level_mismatch"
        return int(binding_department_id), "ok"
    if level == "team":
        if owner_type == "department":
            if binding_department_id is not None and int(binding_department_id) != int(owner_id):
                return None, "team_binding_conflict"
            if not usable_department(department, tenant_id) or int(department.id) != int(owner_id):
                return None, "team_org_invalid"
            return int(owner_id), "ok"
        if binding_department_id is not None:
            if not usable_department(department, tenant_id) or int(department.id) != int(binding_department_id):
                return None, "team_binding_org_invalid"
            return int(binding_department_id), "ok"
        if owner_type in {"user_group", "user"}:
            if creator_organization_id is None:
                return None, "team_creator_no_unique_primary_organization"
            return int(creator_organization_id), "ok"
        return None, "team_owner_unresolved"
    return None, "space_level_excluded"


def _creator_user_id(owner_type: str, owner_id: int, created_by: int, knowledge_user_id: int | None) -> int | None:
    if owner_type == "user_group":
        return None
    if owner_type == "user":
        if int(created_by or 0) > 0:
            return int(created_by)
        if knowledge_user_id:
            return int(knowledge_user_id)
    return None


async def _load_user_names(session, user_ids: set[int]) -> dict[int, str]:
    from sqlmodel import select

    from bisheng.user.domain.models.user import User

    if not user_ids:
        return {}
    rows = (await session.exec(select(User.user_id, User.user_name).where(User.user_id.in_(sorted(user_ids))))).all()
    return {int(row.user_id): row.user_name or "" for row in rows}


async def _load_department_managers(session, space_ids: set[int], admin_user_id: int) -> dict[int, int]:
    """First OpenFGA manager on the member page, excluding the admin account."""
    from bisheng.points.domain.services.space_fga_roles import read_space_owner_manager_ids

    if not space_ids:
        return {}
    by_space: dict[int, set[int]] = {}
    user_ids: set[int] = set()
    for space_id in sorted(space_ids):
        _owners, manager_ids = await read_space_owner_manager_ids(space_id)
        eligible = {int(user_id) for user_id in manager_ids if int(user_id) != int(admin_user_id)}
        by_space[space_id] = eligible
        user_ids.update(eligible)
    names = await _load_user_names(session, user_ids)
    chosen: dict[int, int] = {}
    for space_id, eligible in by_space.items():
        visible = [(user_id, names[user_id]) for user_id in eligible if user_id in names]
        manager_id = first_displayed_manager(visible, admin_user_id)
        if manager_id is not None:
            chosen[space_id] = manager_id
    return chosen


async def _load_departments(session, department_ids: set[int]) -> dict[int, Any]:
    from sqlmodel import select

    from bisheng.database.models.department import Department

    if not department_ids:
        return {}
    rows = (await session.exec(select(Department).where(Department.id.in_(sorted(department_ids))))).all()
    return {int(row.id): row for row in rows if row.id is not None}


async def _load_groups(session, group_ids: set[int]) -> dict[int, Any]:
    from sqlmodel import select

    from bisheng.database.models.group import Group

    if not group_ids:
        return {}
    rows = (await session.exec(select(Group).where(Group.id.in_(sorted(group_ids))))).all()
    return {int(row.id): row for row in rows if row.id is not None}


async def _load_primary_organizations(session, user_ids: set[int], tenant_id: int) -> dict[int, int | None]:
    from sqlmodel import select

    from bisheng.database.models.department import Department, UserDepartment

    if not user_ids:
        return {}
    rows = (
        await session.exec(
            select(
                UserDepartment.user_id,
                Department.id,
                Department.tenant_id,
                Department.status,
                Department.is_deleted,
            )
            .outerjoin(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id.in_(sorted(user_ids)), UserDepartment.is_primary == 1)
        )
    ).all()
    grouped: dict[int, list] = defaultdict(list)
    for row in rows:
        grouped[int(row.user_id)].append(row)
    found: dict[int, int | None] = {}
    for user_id in user_ids:
        items = grouped.get(int(user_id), [])
        if len(items) != 1:
            found[int(user_id)] = None
            continue
        _, department_id, department_tenant_id, status, is_deleted = items[0]
        if department_id is None or int(department_tenant_id) != int(tenant_id) or status != "active" or is_deleted:
            found[int(user_id)] = None
        else:
            found[int(user_id)] = int(department_id)
    return found


async def _page(session, *, tenant_id: int, admin_user_id: int, after_id: int, batch_size: int):
    from sqlalchemy import or_
    from sqlmodel import select

    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

    return (
        await session.exec(
            select(
                KnowledgeFile.id,
                KnowledgeFile.tenant_id,
                KnowledgeFile.knowledge_id,
                KnowledgeFile.belonging_organization_id,
                KnowledgeFile.update_time,
                KnowledgeSpaceScope.level,
                KnowledgeSpaceScope.owner_type,
                KnowledgeSpaceScope.owner_id,
                KnowledgeSpaceScope.created_by,
                Knowledge.user_id,
                Knowledge.name,
                DepartmentKnowledgeSpace.department_id,
            )
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
            .outerjoin(DepartmentKnowledgeSpace, DepartmentKnowledgeSpace.space_id == Knowledge.id)
            .where(
                KnowledgeFile.id > after_id,
                KnowledgeFile.user_id == admin_user_id,
                KnowledgeFile.tenant_id == tenant_id,
                KnowledgeFile.file_type == 1,
                KnowledgeFile.deleted_at.is_(None),
                or_(KnowledgeFile.file_source.is_(None), KnowledgeFile.file_source != "favorite_reference"),
                or_(KnowledgeFile.entry_type.is_(None), KnowledgeFile.entry_type != "projection_tombstone"),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.tenant_id == tenant_id,
                KnowledgeSpaceScope.tenant_id == tenant_id,
                KnowledgeSpaceScope.level.in_(SPACE_LEVELS),
            )
            .order_by(KnowledgeFile.id)
            .limit(batch_size)
        )
    ).all()


def _candidate(row, department, organization_id: int) -> dict:
    current = None if row.belonging_organization_id is None else int(row.belonging_organization_id)
    return {
        "type": "candidate",
        "file_id": int(row.id),
        "tenant_id": int(row.tenant_id),
        "knowledge_id": int(row.knowledge_id),
        "space_level": _value(row.level),
        "before": current,
        "organization_id": int(organization_id),
        "org_level": None if department is None else department.org_level,
        "update_time": row.update_time.isoformat() if isinstance(row.update_time, datetime) else row.update_time,
    }


async def preview(session, journal: JsonlJournal, *, tenant_id: int, admin_user_id: int, batch_size: int) -> dict:
    counts: Counter = Counter()
    cursor = 0
    journal.write(
        {
            "type": "header",
            "version": 3,
            "mode": "preview",
            "tenant_id": tenant_id,
            "admin_user_id": admin_user_id,
            "database_key": database_key(session),
            "rule": "admin_file_space_organization_v3",
        }
    )
    while True:
        rows = await _page(
            session, tenant_id=tenant_id, admin_user_id=admin_user_id, after_id=cursor, batch_size=batch_size
        )
        if not rows:
            break
        cursor = int(rows[-1].id)
        department_space_ids = {
            int(row.knowledge_id)
            for row in rows
            if _value(row.level) == "department" and row.name != EXCLUDED_DEPARTMENT_SPACE_NAME
        }
        department_managers = await _load_department_managers(session, department_space_ids, admin_user_id)
        department_ids = set()
        group_ids = set()
        creator_ids = set(department_managers.values())
        for row in rows:
            if row.department_id and _value(row.level) != "department":
                department_ids.add(int(row.department_id))
            if _value(row.level) == "team" and _value(row.owner_type) == "department":
                department_ids.add(int(row.owner_id))
            elif _value(row.level) == "team" and _value(row.owner_type) == "user_group":
                group_ids.add(int(row.owner_id))
        groups = await _load_groups(session, group_ids)
        for row in rows:
            if _value(row.level) != "team" or row.department_id or _value(row.owner_type) == "department":
                continue
            if _value(row.owner_type) == "user_group":
                group = groups.get(int(row.owner_id))
                if group is not None and group.create_user:
                    creator_ids.add(int(group.create_user))
            else:
                creator = _creator_user_id(
                    _value(row.owner_type), int(row.owner_id), int(row.created_by or 0), row.user_id
                )
                if creator:
                    creator_ids.add(creator)
        primaries = await _load_primary_organizations(session, creator_ids, tenant_id)
        department_ids.update(org_id for org_id in primaries.values() if org_id)
        departments = await _load_departments(session, department_ids)
        squad_parent_ids = {
            int(department.parent_id)
            for department in departments.values()
            if str(department.org_level or "") == "squad" and department.parent_id
        }
        missing_parent_ids = squad_parent_ids - set(departments)
        if missing_parent_ids:
            departments.update(await _load_departments(session, missing_parent_ids))
        for row in rows:
            counts["scanned"] += 1
            binding_id = None if row.department_id is None else int(row.department_id)
            department = None
            creator_organization_id = None
            admin_organization_id = None
            department_manager_reason = None
            excluded = _value(row.level) == "department" and row.name == EXCLUDED_DEPARTMENT_SPACE_NAME
            if _value(row.level) == "department" and not excluded:
                manager_user_id = department_managers.get(int(row.knowledge_id))
                if manager_user_id is None:
                    department_manager_reason = "department_manager_missing"
                else:
                    primary_id = primaries.get(manager_user_id)
                    primary = None if primary_id is None else departments.get(primary_id)
                    parent = None
                    if primary is not None and primary.parent_id is not None:
                        parent = departments.get(int(primary.parent_id))
                    admin_organization_id, department_manager_reason = organization_above_squad(
                        primary, parent, tenant_id
                    )
                    if admin_organization_id is not None:
                        department = departments.get(admin_organization_id)
                        department_manager_reason = None
            elif _value(row.owner_type) == "department":
                department = departments.get(int(row.owner_id))
            elif binding_id is not None:
                department = departments.get(binding_id)
            elif _value(row.level) == "team" and _value(row.owner_type) == "user_group":
                group = groups.get(int(row.owner_id))
                if group is None or int(group.tenant_id or 0) != tenant_id:
                    creator_organization_id = None
                else:
                    creator_organization_id = primaries.get(int(group.create_user or 0))
                    if creator_organization_id is not None:
                        department = departments.get(creator_organization_id)
            elif _value(row.level) == "team":
                creator = _creator_user_id(
                    _value(row.owner_type), int(row.owner_id), int(row.created_by or 0), row.user_id
                )
                creator_organization_id = None if creator is None else primaries.get(creator)
                if creator_organization_id is not None:
                    department = departments.get(creator_organization_id)
            organization_id, reason = organization_for_space(
                level=_value(row.level),
                owner_type=_value(row.owner_type),
                owner_id=int(row.owner_id),
                binding_department_id=binding_id,
                department=department,
                creator_organization_id=creator_organization_id,
                tenant_id=tenant_id,
                excluded=excluded,
                admin_organization_id=admin_organization_id,
                department_manager_reason=department_manager_reason,
            )
            if organization_id is None:
                counts["skipped"] += 1
                counts[f"skip:{reason}"] += 1
                journal.write({"type": "skipped", "file_id": int(row.id), "reason": reason})
                continue
            current = None if row.belonging_organization_id is None else int(row.belonging_organization_id)
            if current == organization_id:
                counts["unchanged"] += 1
                continue
            counts["would_update"] += 1
            journal.write(_candidate(row, department, organization_id))
        await session.rollback()
    summary = {"type": "summary", "next_start_after_id": cursor, **counts}
    journal.write(summary)
    return summary


def read_records(path: Path):
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        raise ValueError("计划文件不完整")
    for line in text.splitlines():
        if line.strip():
            yield json.loads(line)


async def apply_plan(session, path: Path, journal: JsonlJournal) -> dict:
    from sqlalchemy import update

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    records = list(read_records(path))
    header = records[0] if records else {}
    if header.get("type") != "header" or header.get("mode") != "preview" or header.get("version") != 3:
        raise ValueError("计划头无效")
    if header.get("database_key") != database_key(session):
        raise ValueError("计划与当前数据库不一致")
    if records[-1].get("type") != "summary":
        raise ValueError("计划缺少汇总")
    tenant_id = int(header["tenant_id"])
    counts: Counter = Counter()
    journal.write({**header, "mode": "apply"})
    with tenant_scope(tenant_id):
        for record in records:
            if record.get("type") != "candidate":
                continue
            if int(record["tenant_id"]) != tenant_id:
                raise ValueError(f"候选租户不一致 file_id={record['file_id']}")
            file_id = int(record["file_id"])
            before = record["before"]
            predicate = (
                KnowledgeFile.belonging_organization_id.is_(None)
                if before is None
                else KnowledgeFile.belonging_organization_id == int(before)
            )
            update_time = record["update_time"]
            if isinstance(update_time, str):
                update_time = datetime.fromisoformat(update_time)
            result = await session.exec(
                update(KnowledgeFile)
                .where(KnowledgeFile.id == file_id, KnowledgeFile.tenant_id == tenant_id, predicate)
                .values(belonging_organization_id=int(record["organization_id"]), update_time=update_time)
            )
            if result.rowcount != 1:
                await session.rollback()
                counts["skipped"] += 1
                journal.write({"type": "skipped", "file_id": file_id, "reason": "plan_state_changed"})
                continue
            await session.commit()
            counts["updated"] += 1
            journal.write({"type": "committed", "file_id": file_id, "organization_id": int(record["organization_id"])})
    summary = {"type": "summary", **counts}
    journal.write(summary)
    return summary


def sync_content_stat() -> dict:
    """Refresh file snapshots so belonging organization names match MySQL."""
    from bisheng.worker.telemetry.mid_table import sync_mid_knowledge_space_content_stat

    result = sync_mid_knowledge_space_content_stat()
    if not isinstance(result, dict):
        raise RuntimeError("内容统计对账没有返回结果")
    if result.get("degraded") or result.get("retry_state") in {"dead", "busy", "backoff"}:
        raise RuntimeError(f"内容统计对账未执行: {json.dumps(result, ensure_ascii=False, default=str)}")
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--tenant-id", type=int)
    result.add_argument("--admin-user-id", type=int, default=1)
    result.add_argument("--batch-size", type=int, default=500)
    result.add_argument("--plan", type=Path)
    result.add_argument("--apply", action="store_true")
    result.add_argument("--output", type=Path, required=True)
    return result


async def run(args: argparse.Namespace) -> int:
    from bisheng.core.database import get_async_db_session

    if args.output.exists():
        raise SystemExit("输出文件必须不存在")
    if args.plan and not args.apply:
        raise SystemExit("执行计划需要 --apply")
    if args.apply and args.plan is None:
        raise SystemExit("写入必须使用 --plan --apply")
    if not args.plan and (not args.tenant_id or args.tenant_id <= 0):
        raise SystemExit("预览必须指定 --tenant-id")
    with JsonlJournal(args.output) as journal:
        async with get_async_db_session() as session:
            if args.plan:
                summary = await apply_plan(session, args.plan, journal)
                summary["elasticsearch"] = sync_content_stat()
            else:
                with tenant_scope(args.tenant_id):
                    summary = await preview(
                        session,
                        journal,
                        tenant_id=args.tenant_id,
                        admin_user_id=args.admin_user_id,
                        batch_size=args.batch_size,
                    )
    print(json.dumps({key: value for key, value in summary.items() if key != "type"}, ensure_ascii=False))
    return 0


def main() -> int:
    return asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
