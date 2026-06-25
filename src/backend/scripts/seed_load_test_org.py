#!/usr/bin/env python3
"""压测数据脚本：批量生成部门树 + 用户，灌入数据库，用于大用户量下的体验/性能测试。

## 做什么

1. **部门树**：在平台默认根部门（``Tenant.root_dept_id``）下，按 ``--fanout``
   广度优先生成 ``--departments`` 个部门。每个部门走
   ``DepartmentDao.aupsert_by_external_id``（自动维护物化路径 ``path``），并写
   ``department:{parent}#parent department:{child}`` 的 OpenFGA 继承边。
2. **用户**：生成 ``--users`` 个本地用户，轮询分配到上面生成的部门里，每人一个主部门
   （``is_primary=1``）。可选 ``--secondary-ratio`` 给一部分用户再挂一个附属部门
   （``is_primary=0``）。每个用户写 DB（user + 默认角色 + user_department + user_tenant），
   并写 ``user:{uid} member department:{dept}`` 的 OpenFGA 成员边。

所有生成的数据都打上 ``source=<--source>``（默认 ``loadtest``）标签、``external_id``
形如 ``loadtest_dept_{n}`` / ``loadtest_user_{n}``，因此本脚本**幂等**（重复跑同一批不
会重复建），且可用 ``--purge`` 一键清掉这批压测数据（DB 行 + FGA 边）。

## 用法（必须在 src/backend 目录下运行）

    # 1) 干跑（默认）：只打印将创建多少部门/用户，不写任何东西
    config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py \
        --departments 200 --users 50000 --fanout 8

    # 2) 真正写入（DB + OpenFGA）
    config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py \
        --departments 200 --users 50000 --fanout 8 --apply

    # 3) 只写库、不碰 OpenFGA（FGA 边后续可用 --repair-fga 之类手段补；适合先快速灌库）
    config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py \
        --departments 200 --users 50000 --apply --no-fga

    # 4) 清理本脚本生成的全部压测数据（DB + FGA）
    config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py --purge --apply

## 注意

- **干跑是安全默认**；只有 ``--apply`` 才会写库 / 写 FGA / 删数据。
- 默认会写 OpenFGA（``department#parent`` 和 ``department#member`` 边）——这是 ReBAC 读路径
  压测真正需要的边。若只想先把库灌满，用 ``--no-fga`` 跳过（之后再补）。
- 默认**不**给每个用户写 RBAC 默认角色的 FGA 边（``--with-role-fga`` 才写）：那是逐用户的
  慢路径，而本脚本聚焦部门 ReBAC 读路径；DB 里的 ``user_role`` 行仍会写（保证用户可登录）。
- 触达 OpenFGA，故 ``--apply`` 时走 ``initialize_app_context`` / ``close_app_context``。
- 跨租户：运行在 ``bypass_tenant_filter()`` + ``set_current_tenant_id`` 下。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

DEFAULT_PLAIN_PASSWORD = "Test@1234ab"


# ---------------------------------------------------------------------------
# Tree shape helper
# ---------------------------------------------------------------------------
def _build_tree_plan(total: int, fanout: int) -> list[int]:
    """Return a list ``parent_index[i]`` for i in [0, total): the index (within
    the generated departments) of node i's parent, or -1 if it hangs directly
    off the platform root.

    Nodes are laid out breadth-first: node 0 is the first child of the root,
    then we fill each node's ``fanout`` children before moving on. Produces a
    balanced tree of depth ``ceil(log_fanout(total))``.
    """
    fanout = max(1, fanout)
    parents: list[int] = []
    # Queue of node indices that still have capacity for children.
    next_child_of = 0  # index of the node currently receiving children
    children_used = 0
    for i in range(total):
        if i < fanout:
            # First `fanout` nodes are top-level (under platform root).
            parents.append(-1)
            continue
        parents.append(next_child_of)
        children_used += 1
        if children_used >= fanout:
            next_child_of += 1
            children_used = 0
    return parents


def _normalize_path(p: str | None) -> str:
    base = (p or "/").strip()
    if not base.startswith("/"):
        base = "/" + base
    if not base.endswith("/"):
        base = base + "/"
    return base


# ---------------------------------------------------------------------------
# Create path
# ---------------------------------------------------------------------------
async def _create_departments(
    *,
    source: str,
    tenant_id: int,
    count: int,
    fanout: int,
    plat_root,
) -> tuple[list, list]:
    """Create ``count`` departments as a balanced tree under ``plat_root``.

    Returns ``(departments, parent_edge_ops)`` where departments is the list of
    refreshed Department rows (index-aligned with the tree plan) and
    parent_edge_ops are the FGA ``on_created`` tuple ops.
    """
    from bisheng.database.models.department import DepartmentDao
    from bisheng.department.domain.services.department_change_handler import (
        DepartmentChangeHandler,
    )

    plan = _build_tree_plan(count, fanout)
    ts = int(time.time())
    created: list = []
    ops: list = []

    for i in range(count):
        parent = plat_root if plan[i] == -1 else created[plan[i]]
        name = f"压测部门_{i:06d}"
        dept = await DepartmentDao.aupsert_by_external_id(
            source=source,
            external_id=f"{source}_dept_{i}",
            name=name,
            parent_id=int(parent.id),
            path=_normalize_path(parent.path),
            sort_order=i,
            last_sync_ts=ts,
            tenant_id=tenant_id,
        )
        refreshed = await DepartmentDao.aget_by_id(int(dept.id))
        if refreshed is None:
            raise RuntimeError(f"Failed to refresh department index={i}")
        created.append(refreshed)
        ops.extend(DepartmentChangeHandler.on_created(int(refreshed.id), int(parent.id)))

        if i == 0 or (i + 1) % 200 == 0 or i + 1 == count:
            print(f"  departments {i + 1}/{count} ...", flush=True)

    return created, ops


async def _create_users_batch(
    *,
    source: str,
    tenant_id: int,
    pwd_hash: str,
    start_seq: int,
    batch_size: int,
    dept_ids_primary: list[int],
    dept_ids_secondary: list[int | None],
) -> list[tuple[int, int, int | None]]:
    """Insert one batch of users + default role + user_department + user_tenant
    in a single transaction.

    ``dept_ids_primary[k]`` / ``dept_ids_secondary[k]`` give the primary and
    (optional) secondary department for the k-th user in the batch.

    Returns ``[(user_id, primary_dept_id, secondary_dept_id_or_None), ...]`` so
    the caller can build FGA member ops.
    """
    from bisheng.core.database import get_async_db_session
    from bisheng.database.constants import DefaultRole
    from bisheng.database.models.department import UserDepartment
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.models.user_role import UserRole

    n = len(dept_ids_primary)
    async with get_async_db_session() as session:
        users = [
            User(
                user_name=f"压测用户_{start_seq + k:07d}",
                password=pwd_hash,
                source=source,
                external_id=f"{source}_user_{start_seq + k}",
            )
            for k in range(n)
        ]
        session.add_all(users)
        await session.flush()  # assign autoincrement user_id
        uids = [int(u.user_id) for u in users]

        session.add_all([UserRole(user_id=uid, role_id=DefaultRole) for uid in uids])
        session.add_all(
            [
                UserDepartment(
                    user_id=uid,
                    department_id=dept_ids_primary[k],
                    is_primary=1,
                    source=source,
                )
                for k, uid in enumerate(uids)
            ]
        )
        secondary_rows = [
            UserDepartment(
                user_id=uid,
                department_id=dept_ids_secondary[k],
                is_primary=0,
                source=source,
            )
            for k, uid in enumerate(uids)
            if dept_ids_secondary[k] is not None
        ]
        if secondary_rows:
            session.add_all(secondary_rows)
        session.add_all([UserTenant(user_id=uid, tenant_id=tenant_id, is_default=1, status="active") for uid in uids])
        await session.commit()

    return [(uids[k], dept_ids_primary[k], dept_ids_secondary[k]) for k in range(n)]


async def _flush_fga(ops: list, chunk: int = 5000) -> None:
    """Write FGA ops in chunks. crash_safe=False to avoid depending on the
    failed_tuple pre-write table (not every env has run that migration)."""
    if not ops:
        return
    from bisheng.permission.domain.services.permission_service import PermissionService

    for i in range(0, len(ops), chunk):
        await PermissionService.batch_write_tuples(ops[i : i + chunk], crash_safe=False)
        print(f"  fga {min(i + chunk, len(ops))}/{len(ops)} tuples ...", flush=True)


# ---------------------------------------------------------------------------
# Purge path
# ---------------------------------------------------------------------------
async def _purge(*, source: str, with_fga: bool) -> int:
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.database.models.tenant import UserTenant
    from bisheng.department.domain.services.department_change_handler import (
        DepartmentChangeHandler,
    )
    from bisheng.user.domain.models.user import User
    from bisheng.user.domain.models.user_role import UserRole

    fga_ops: list = []
    async with get_async_db_session() as session:
        user_rows = (await session.exec(select(User.user_id).where(User.source == source))).all()
        uids = [int(r[0] if isinstance(r, (list, tuple)) else r) for r in user_rows]
        dept_rows = (await session.exec(select(Department.id).where(Department.source == source))).all()
        dept_pks = [int(r[0] if isinstance(r, (list, tuple)) else r) for r in dept_rows]

        print(f"purge: {len(uids)} 用户, {len(dept_pks)} 部门 (source={source})")

        if with_fga:
            ud_rows = (
                await session.exec(
                    select(UserDepartment.user_id, UserDepartment.department_id).where(
                        UserDepartment.user_id.in_(uids) if uids else False
                    )
                )
            ).all()
            for row in ud_rows:
                uid = int(row[0])
                did = int(row[1])
                fga_ops.extend(DepartmentChangeHandler.on_member_removed(did, uid))
            dept_parent = (
                await session.exec(
                    select(Department.id, Department.parent_id).where(
                        Department.id.in_(dept_pks) if dept_pks else False
                    )
                )
            ).all()
            for row in dept_parent:
                did = int(row[0])
                pid = row[1]
                if pid is not None:
                    fga_ops.extend(DepartmentChangeHandler.on_archived(did, int(pid)))

        # DB delete. FK ondelete=CASCADE on user_department clears membership
        # when the user/department row goes; user_role / user_tenant we clear
        # explicitly (no guaranteed cascade from the user side here).
        if uids:
            for model, col in ((UserRole, UserRole.user_id), (UserTenant, UserTenant.user_id)):
                for obj in (await session.exec(select(model).where(col.in_(uids)))).all():
                    await session.delete(obj)
            for obj in (await session.exec(select(User).where(User.user_id.in_(uids)))).all():
                await session.delete(obj)
        if dept_pks:
            for obj in (
                await session.exec(select(UserDepartment).where(UserDepartment.department_id.in_(dept_pks)))
            ).all():
                await session.delete(obj)
            for obj in (await session.exec(select(Department).where(Department.id.in_(dept_pks)))).all():
                await session.delete(obj)
        await session.commit()

    if with_fga and fga_ops:
        await _flush_fga(fga_ops)
    print("purge: 完成。")
    return 0


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
async def _run(args: argparse.Namespace) -> int:
    if args.purge:
        if not args.apply:
            print("[dry-run] --purge 将删除全部 source=%s 的用户/部门及其 FGA 边。确认后加 --apply。" % args.source)
            return 0
    else:
        # plan summary (no DB needed)
        plan = _build_tree_plan(args.departments, args.fanout)
        depth = 0
        # rough depth estimate
        idx = args.departments - 1
        while idx >= 0:
            depth += 1
            idx = plan[idx]
        print(
            f"计划：{args.departments} 个部门 (fanout={args.fanout}, 约 {depth} 层), "
            f"{args.users} 个用户 (轮询分配主部门"
            + (f", {int(args.secondary_ratio * 100)}% 带附属部门" if args.secondary_ratio > 0 else "")
            + f"), 写FGA={not args.no_fga}, 角色FGA={args.with_role_fga}"
        )
        if not args.apply:
            print("[dry-run] 未写库 / 未写 FGA。确认后加 --apply 执行。")
            return 0

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.tenant import TenantDao
    from bisheng.department.domain.services.department_change_handler import (
        DepartmentChangeHandler,
    )
    from bisheng.utils import md5_hash

    await initialize_app_context(config=settings)
    token = None
    try:
        with bypass_tenant_filter():
            token = set_current_tenant_id(args.tenant_id)

            if args.purge:
                return await _purge(source=args.source, with_fga=not args.no_fga)

            tenant = await TenantDao.aget_by_id(args.tenant_id)
            if tenant is None or tenant.root_dept_id is None:
                print(
                    f"租户 {args.tenant_id} 或其 root_dept_id 缺失，请先完成 BiSheng 初始化。",
                    file=sys.stderr,
                )
                return 1
            plat_root = await DepartmentDao.aget_by_id(int(tenant.root_dept_id))
            if plat_root is None:
                print("平台根部门未找到。", file=sys.stderr)
                return 1

            # --- departments ---
            print(f"开始创建 {args.departments} 个部门 ...", flush=True)
            depts, parent_ops = await _create_departments(
                source=args.source,
                tenant_id=args.tenant_id,
                count=args.departments,
                fanout=args.fanout,
                plat_root=plat_root,
            )
            dept_pks = [int(d.id) for d in depts]
            if not dept_pks:
                print("没有可分配的部门，退出。", file=sys.stderr)
                return 1

            if not args.no_fga:
                print("写部门父边到 OpenFGA ...", flush=True)
                await _flush_fga(parent_ops)

            # --- users ---
            print(f"开始创建 {args.users} 个用户 ...", flush=True)
            pwd_hash = md5_hash(DEFAULT_PLAIN_PASSWORD)
            secondary_every = 0
            if args.secondary_ratio > 0:
                secondary_every = max(1, int(round(1 / args.secondary_ratio)))

            member_ops: list = []
            created_total = 0
            seq = 0
            while seq < args.users:
                bsize = min(args.batch_size, args.users - seq)
                primary = [dept_pks[(seq + k) % len(dept_pks)] for k in range(bsize)]
                secondary: list[int | None] = []
                for k in range(bsize):
                    gi = seq + k
                    if secondary_every and gi % secondary_every == 0:
                        # pick a different department for the secondary membership
                        sec = dept_pks[(gi + 1) % len(dept_pks)]
                        secondary.append(sec if sec != primary[k] else None)
                    else:
                        secondary.append(None)

                rows = await _create_users_batch(
                    source=args.source,
                    tenant_id=args.tenant_id,
                    pwd_hash=pwd_hash,
                    start_seq=seq,
                    batch_size=bsize,
                    dept_ids_primary=primary,
                    dept_ids_secondary=secondary,
                )
                for uid, pdid, sdid in rows:
                    member_ops.extend(DepartmentChangeHandler.on_members_added(pdid, [uid]))
                    if sdid is not None:
                        member_ops.extend(DepartmentChangeHandler.on_members_added(sdid, [uid]))

                if args.with_role_fga:
                    from bisheng.database.constants import DefaultRole
                    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
                        LegacyRBACSyncService,
                    )

                    for uid, _pdid, _sdid in rows:
                        await LegacyRBACSyncService.sync_user_auth_created(uid, [DefaultRole])

                created_total += bsize
                seq += bsize
                print(f"  users {created_total}/{args.users} ...", flush=True)

            if not args.no_fga:
                print("写部门成员边到 OpenFGA ...", flush=True)
                await _flush_fga(member_ops)

            print(
                f"完成：部门 {len(dept_pks)} 个，用户 {created_total} 个。"
                f"统一密码={DEFAULT_PLAIN_PASSWORD}（仅本地用户登录可用）。"
            )
            return 0
    finally:
        if token is not None:
            current_tenant_id.reset(token)
        await close_app_context()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--departments", type=int, default=100, help="要生成的部门总数（默认 100）")
    p.add_argument("--users", type=int, default=1000, help="要生成的用户总数（默认 1000）")
    p.add_argument("--fanout", type=int, default=8, help="部门树每个节点的子节点数（默认 8）")
    p.add_argument(
        "--secondary-ratio",
        type=float,
        default=0.0,
        help="给多大比例的用户额外挂一个附属部门，0~1（默认 0，不挂附属）",
    )
    p.add_argument("--tenant-id", type=int, default=1, help="目标租户 id（默认 1）")
    p.add_argument("--source", default="loadtest", help="数据来源标签，用于幂等与清理（默认 loadtest）")
    p.add_argument("--batch-size", type=int, default=500, help="用户批量写入的每批大小（默认 500）")
    p.add_argument("--no-fga", action="store_true", help="只写库，不写 OpenFGA 边")
    p.add_argument(
        "--with-role-fga",
        action="store_true",
        help="逐用户把默认角色同步到 OpenFGA（慢；默认不写，仅写 user_role 库行）",
    )
    p.add_argument("--purge", action="store_true", help="删除本脚本生成的全部数据（按 --source 匹配）")
    p.add_argument("--apply", action="store_true", help="真正执行（默认 dry-run）")
    args = p.parse_args()

    if not args.purge:
        if args.departments < 1:
            p.error("--departments 必须 >= 1")
        if args.users < 0:
            p.error("--users 不能为负")
        if not (0.0 <= args.secondary_ratio <= 1.0):
            p.error("--secondary-ratio 必须在 0~1 之间")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
