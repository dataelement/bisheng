#!/usr/bin/env python3
"""F045 — one-off normalization to the single-space-admin model.

Department knowledge spaces used to derive their admins from two sources: the
creating super admin (CREATOR member row + OpenFGA ``owner`` tuple) and the
auto-synced department admins (ADMIN rows with ``membership_source=
'department_admin'`` + ``manager`` tuples). F045 replaces both with one explicit
space admin stored in ``department_knowledge_space.admin_user_id``.

Per binding row with ``admin_user_id IS NULL`` (already-normalized rows are
skipped, so re-running is safe):

1. Adopt: exactly ONE active ADMIN member whose user account is valid
   (``user.delete=0``) → that user becomes the space admin (column + member row
   normalized to ``membership_source='space_admin'`` + manager tuple). Zero or
   multiple valid ADMINs → the space stays pending (column stays NULL) for the
   super admin to fix via the management UI.
2. Demote every non-adopted ADMIN member: ``department_admin``-sourced rows are
   reverted to their pre-promotion role (or removed when they were pure
   derived rows); ``manual`` ADMIN rows are demoted to MEMBER. Their ``manager``
   tuples are revoked either way.
3. Clear the creator footprint: CREATOR member rows are deleted and the
   creator's ``owner`` tuple revoked. ``Knowledge.user_id`` /
   ``department_knowledge_space.created_by`` stay as the audit record.

Run from ``src/backend/`` (dry-run prints the plan; ``--apply`` writes):

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/migrate_department_space_admin.py            # dry-run
    python scripts/migrate_department_space_admin.py --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.models.space_channel_member import (  # noqa: E402
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.department_knowledge_space import (  # noqa: E402
    DepartmentKnowledgeSpace,
)
from bisheng.user.domain.models.user import User  # noqa: E402


@dataclass
class Report:
    bindings: int = 0
    adopted: int = 0
    pending: int = 0
    demoted_department_admin: int = 0
    demoted_manual_admin: int = 0
    creator_rows_removed: int = 0
    notes: list[str] = field(default_factory=list)


async def _revoke_relation(space_id: int, user_id: int, relation: str, apply: bool) -> None:
    if not apply:
        return
    from bisheng.permission.domain.schemas.permission_schema import AuthorizeRevokeItem
    from bisheng.permission.domain.services.permission_service import PermissionService

    try:
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(space_id),
            revokes=[
                AuthorizeRevokeItem(
                    subject_type="user",
                    subject_id=user_id,
                    relation=relation,
                    include_children=False,
                ),
            ],
        )
    except Exception as exc:
        print(f"  ! FGA revoke {relation} failed for space={space_id} user={user_id}: {exc}")


async def _grant_manager(space_id: int, user_id: int, apply: bool) -> None:
    if not apply:
        return
    from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
    from bisheng.permission.domain.services.permission_service import PermissionService

    try:
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(space_id),
            grants=[
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=user_id,
                    relation="manager",
                    include_children=False,
                ),
            ],
        )
    except Exception as exc:
        print(f"  ! FGA grant manager failed for space={space_id} user={user_id}: {exc}")


async def _valid_user_ids(user_ids: set[int]) -> set[int]:
    if not user_ids:
        return set()
    async with get_async_db_session() as session:
        result = await session.exec(select(User).where(User.user_id.in_(sorted(user_ids))))
        return {int(u.user_id) for u in result.all() if not u.delete}


async def _process_binding(binding: DepartmentKnowledgeSpace, apply: bool, report: Report) -> None:
    space_id = int(binding.space_id)
    async with get_async_db_session() as session:
        result = await session.exec(
            select(SpaceChannelMember).where(
                SpaceChannelMember.business_id == str(space_id),
                SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
            )
        )
        members = result.all()

    admins = [m for m in members if m.user_role == UserRoleEnum.ADMIN and m.status == MembershipStatusEnum.ACTIVE]
    creators = [m for m in members if m.user_role == UserRoleEnum.CREATOR]
    valid_ids = await _valid_user_ids({int(m.user_id) for m in admins})
    valid_admins = [m for m in admins if int(m.user_id) in valid_ids]

    adopted = valid_admins[0] if len(valid_admins) == 1 else None
    label = f"space={space_id} dept={binding.department_id}"
    if adopted is not None:
        report.adopted += 1
        print(f"  {label}: adopt user={adopted.user_id} as space admin")
        if apply:
            async with get_async_db_session() as session:
                binding.admin_user_id = int(adopted.user_id)
                session.add(binding)
                adopted.membership_source = "space_admin"
                session.add(adopted)
                await session.commit()
            await _grant_manager(space_id, int(adopted.user_id), apply)
    else:
        report.pending += 1
        print(f"  {label}: PENDING ({len(valid_admins)} valid admin(s) among {len(admins)})")

    for member in admins:
        if adopted is not None and member.user_id == adopted.user_id:
            continue
        if member.membership_source == "department_admin":
            report.demoted_department_admin += 1
            previous = member.department_admin_promoted_from_role
            action = f"revert to {previous}" if previous else "remove"
            print(f"  {label}: demote department_admin user={member.user_id} ({action})")
            if apply:
                async with get_async_db_session() as session:
                    if previous:
                        member.user_role = UserRoleEnum(previous)
                        member.membership_source = "manual"
                        member.department_admin_promoted_from_role = None
                        session.add(member)
                    else:
                        await session.delete(member)
                    await session.commit()
        else:
            report.demoted_manual_admin += 1
            print(f"  {label}: demote manual admin user={member.user_id} to member")
            if apply:
                async with get_async_db_session() as session:
                    member.user_role = UserRoleEnum.MEMBER
                    session.add(member)
                    await session.commit()
        await _revoke_relation(space_id, int(member.user_id), "manager", apply)

    for creator in creators:
        report.creator_rows_removed += 1
        print(f"  {label}: remove creator footprint user={creator.user_id}")
        if apply:
            async with get_async_db_session() as session:
                await session.delete(creator)
                await session.commit()
        await _revoke_relation(space_id, int(creator.user_id), "owner", apply)


async def run(apply: bool) -> Report:
    report = Report()
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            result = await session.exec(select(DepartmentKnowledgeSpace))
            bindings = result.all()

    for binding in bindings:
        if binding.admin_user_id is not None:
            continue  # already normalized — idempotent re-run
        report.bindings += 1
        # Mirror the Celery-Beat multi-tenant pattern: each row is processed
        # under its own tenant context so tenant-filtered SELECTs stay scoped.
        if binding.tenant_id:
            set_current_tenant_id(int(binding.tenant_id))
        await _process_binding(binding, apply, report)
    return report


async def _main(apply: bool) -> Report:
    # The script writes OpenFGA tuples → needs the full app context (DB alone
    # is lazily registered, FGA/Redis are not). Mirror the FastAPI lifespan.
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context

    await initialize_app_context(config=settings)
    try:
        return await run(apply=apply)
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(description="F045: normalize department spaces to the single-admin model")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[migrate_department_space_admin] mode={mode}")
    report = asyncio.run(_main(apply=args.apply))
    print(
        f"[migrate_department_space_admin] done: bindings={report.bindings} adopted={report.adopted} "
        f"pending={report.pending} demoted_department_admin={report.demoted_department_admin} "
        f"demoted_manual_admin={report.demoted_manual_admin} creator_rows_removed={report.creator_rows_removed}"
    )
    if not args.apply:
        print("[migrate_department_space_admin] dry-run only — re-run with --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
