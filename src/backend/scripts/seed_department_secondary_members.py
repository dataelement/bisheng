#!/usr/bin/env python3
"""一次性脚本：在除根节点外的每个部门下各创建 2 名本地用户。

- 用户名格式：「人名（第三方）_部门内部id_主|附」，例如 陆思哲（第三方）_12_主、林雨桐（第三方）_12_附。
- 两人相对该部门的关系类型：一名主部门（is_primary=1）、一名附属部门（is_primary=0）。
- 不加入任何用户组；角色=默认角色（DefaultRole）。密码统一为 Test@1234ab。

用法（在 src/backend 目录，需能连上 config.yaml 中的 MySQL；建议设置与后端一致的 BS_* 环境变量）:
    .venv/Scripts/python.exe scripts/seed_department_secondary_members.py

若 OpenFGA 当时未写入，可在部署好 FGA 后补写**全部**部门成员关系（主/附均写 member 元组）:
    .venv/Scripts/python.exe scripts/seed_department_secondary_members.py --repair-fga
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys

# 保证以脚本路径运行时能 import bisheng
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select

from bisheng.common.services.config_service import settings
from bisheng.database.constants import DefaultRole
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import UserTenantDao
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.user.domain.models.user import User, UserDao
from bisheng.utils import md5_hash

# 固定密码（8+ 位，含大小写数字符号）
DEFAULT_PLAIN_PASSWORD = "Test@1234ab"

# 每部门两人：主部门用第一个名字，附属用第二个；部门 id 轮换不同中文名对
NAME_PAIRS = [
    ("陆思哲", "林雨桐"),
    ("方景行", "苏晚晴"),
    ("周予安", "许知夏"),
    ("韩沐阳", "沈若溪"),
    ("邓文博", "蒋心语"),
    ("罗嘉树", "谢清和"),
    ("冯景明", "陈书瑶"),
    ("吴承宇", "赵思齐"),
]


def _username_for(dept_pk: int, is_primary: bool) -> str:
    pair = NAME_PAIRS[dept_pk % len(NAME_PAIRS)]
    base = pair[0] if is_primary else pair[1]
    tag = "主" if is_primary else "附"
    return f"{base}（第三方）_{dept_pk}_{tag}"


def _external_id() -> str:
    return f"seed_{secrets.token_hex(6)}"


async def _flush_fga(ops: list) -> None:
    """使用 crash_safe=False，避免依赖 failed_tuple 预写表（部分环境未跑迁移）。"""
    if not ops:
        return
    await PermissionService.batch_write_tuples(ops, crash_safe=False)


def repair_fga_all_department_members() -> None:
    """将库中所有部门成员关系补写到 OpenFGA（主/附均写 member，幂等）。"""
    from bisheng.core.database import get_sync_db_session

    ops: list = []
    with get_sync_db_session() as session:
        stmt = select(UserDepartment.department_id, UserDepartment.user_id)
        rows = list(session.exec(stmt).all())

    for dept_pk, uid in rows:
        ops.extend(DepartmentChangeHandler.on_members_added(dept_pk, [uid]))

    async def _run():
        await _flush_fga(ops)

    print(f"repair-fga: {len(rows)} 条 user_department → {len(ops)} 个 tuple 操作")
    asyncio.run(_run())
    print("repair-fga: OpenFGA 写入已尝试。")


def main() -> None:
    from bisheng.core.database import get_sync_db_session

    pwd_hash = md5_hash(DEFAULT_PLAIN_PASSWORD)
    multi_on = bool(
        getattr(settings, "multi_tenant", None)
        and getattr(settings.multi_tenant, "enabled", False)
    )

    all_ops: list = []
    created_users = 0
    linked_rows = 0

    with get_sync_db_session() as session:
        stmt = (
            select(Department)
            .where(Department.parent_id.isnot(None))
            .where(Department.status == "active")
            .order_by(Department.id)
        )
        depts = list(session.exec(stmt).all())

    if not depts:
        print("未找到非根部门（parent_id 非空且 active），退出。")
        return

    print(f"将处理 {len(depts)} 个部门，每部门 2 人（1 主部门 + 1 附属部门）。")

    for dept in depts:
        assert dept.id is not None
        tenant_id = getattr(dept, "tenant_id", None) or 1

        for is_primary in (True, False):
            uname = _username_for(dept.id, is_primary)
            primary_flag = 1 if is_primary else 0
            existing = UserDao.get_unique_user_by_name(uname)
            if existing:
                user = existing
                print(f"  已存在用户 {uname} (id={user.user_id})，跳过创建")
            else:
                user = User(
                    user_name=uname,
                    password=pwd_hash,
                    source="local",
                    external_id=_external_id(),
                )
                user = UserDao.add_user_with_groups_and_roles(
                    user,
                    [],
                    [DefaultRole],
                )
                if multi_on:
                    try:
                        UserTenantDao.add_user_to_tenant(
                            user.user_id,
                            tenant_id,
                            is_default=1,
                        )
                    except Exception as ex:  # noqa: BLE001
                        print(f"  警告: user_tenant 写入失败 user={user.user_id}: {ex}")
                created_users += 1
                print(f"  新建用户 {uname} (id={user.user_id})")

            with get_sync_db_session() as session:
                exists_ud = session.exec(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user.user_id,
                        UserDepartment.department_id == dept.id,
                    )
                ).first()
                if exists_ud:
                    print(
                        f"  已存在部门成员 dept_id={dept.dept_id} user={user.user_id}，跳过关联",
                    )
                    continue

                ud = UserDepartment(
                    user_id=user.user_id,
                    department_id=dept.id,
                    is_primary=primary_flag,
                    source="local",
                )
                session.add(ud)
                session.commit()
                linked_rows += 1

            ops = DepartmentChangeHandler.on_members_added(dept.id, [user.user_id])
            all_ops.extend(ops)

    print(f"完成：新建用户约 {created_users} 个，新建部门关联 {linked_rows} 条。")

    async def _run():
        await _flush_fga(all_ops)

    asyncio.run(_run())
    print("OpenFGA 写入已尝试（若未配置 FGA 则仅写库）。")


if __name__ == "__main__":
    if "--repair-fga" in sys.argv:
        repair_fga_all_department_members()
    else:
        main()
