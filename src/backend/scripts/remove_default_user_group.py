#!/usr/bin/env python3
"""删除历史「默认用户组」并解除全部用户与该组的 MySQL + OpenFGA 关系。

处理名称匹配 `Default user group` / `默认用户组` 的 `group` 行：
1. 读取该组下所有 `user_group` 行（含创建者 admin 行），按行删除 OpenFGA 上
   `user:{id} —member/admin→ user_group:{gid}` 元组；
2. 删除 `user_group`、`group_resource` 中该组记录；
3. 删除 `group` 行。

用法（在 src/backend 目录，需能连上 config.yaml 中的 MySQL，且 OpenFGA 可访问时才会清 FGA）::

    python scripts/remove_default_user_group.py
"""

from __future__ import annotations

import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.database import get_sync_db_session
from bisheng.database.models.group import Group
from bisheng.database.models.group_resource import GroupResource
from bisheng.database.models.user_group import UserGroup

DEFAULT_NAMES = ('Default user group', '默认用户组')


async def _purge_openfga_tuples(group_id: int, user_ids: list[int]) -> None:
    """对该组在 FGA 中出现的 member/admin 元组做 best-effort 删除（忽略「不存在」）。"""
    from bisheng.common.services.config_service import settings

    cfg = settings.openfga
    if not cfg.enabled:
        print('  OpenFGA 未启用（settings.openfga.enabled=false），跳过 FGA 元组删除。')
        return

    from bisheng.core.openfga.exceptions import FGAClientError, FGAWriteError
    from bisheng.core.openfga.manager import FGAManager

    mgr = FGAManager(openfga_config=cfg)
    client = await mgr._async_initialize()  # noqa: SLF001
    obj = f'user_group:{int(group_id)}'
    ok = 0
    try:
        for uid in sorted(set(user_ids)):
            for rel in ('admin', 'member'):
                try:
                    await client.write_tuples(
                        deletes=[{'user': f'user:{int(uid)}', 'relation': rel, 'object': obj}],
                    )
                    ok += 1
                except (FGAWriteError, FGAClientError) as e:
                    msg = str(e).lower()
                    if 'did not exist' in msg or 'does not exist' in msg:
                        continue
                    raise
        print(f'  OpenFGA：已对 user_group:{group_id} 尝试删除元组（成功写入的 delete 调用约 {ok} 次，含已不存在则跳过）。')
    finally:
        await client.close()


def main() -> None:
    with get_sync_db_session() as session:
        stmt = select(Group).where(Group.group_name.in_(DEFAULT_NAMES))
        groups = list(session.exec(stmt).all())
        if not groups:
            print('未找到名称匹配的默认用户组，无需处理。')
            return
        for g in groups:
            gid = g.id
            if gid is None:
                continue
            print(f'处理 group id={gid} name={g.group_name!r} …')
            ug_stmt = select(UserGroup.user_id, UserGroup.is_group_admin).where(
                UserGroup.group_id == gid,
            )
            raw = list(session.exec(ug_stmt).all())
            user_ids = [int(row[0]) for row in raw]

            if user_ids:
                asyncio.run(_purge_openfga_tuples(gid, user_ids))

            session.exec(delete(UserGroup).where(UserGroup.group_id == gid))
            session.exec(delete(GroupResource).where(GroupResource.group_id == str(gid)))
            session.exec(delete(Group).where(Group.id == gid))
            session.commit()
            print(f'  已删除 group id={gid} 的 user_group / group_resource / group 行。')
    print('完成。组织与成员列表中不应再出现上述名称的用户组（接口已过滤隐藏名）。')


if __name__ == '__main__':
    main()
