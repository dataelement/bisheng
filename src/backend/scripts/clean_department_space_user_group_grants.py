#!/usr/bin/env python3
"""一次性脚本（F033）：清理部门知识空间上的"用户组"历史授权。

## 背景

F033 起，**部门知识空间**只能按"绑定部门及其子部门 / 子树成员"授权，
不再支持"用户组"维度（前端隐藏 tab，后端 `authorize` 拒绝新增 user_group）。
运行期代码**不为历史 user_group 授权保留兼容路径**，存量异常授权由本脚本一次性清理：

- 撤销 OpenFGA tuple（真正的访问来源）；
- 删除 UI 的 relation-model binding（`initdb_config` 里的展示绑定）。

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只扫描并打印受影响的 (空间, 用户组, relation, 波及用户数)，不写库）
    python scripts/clean_department_space_user_group_grants.py

    # 真正应用
    python scripts/clean_department_space_user_group_grants.py --apply

## 安全保证

- 仅作用于 ``DepartmentKnowledgeSpaceDao.aget_all()`` 列出的**部门知识空间**，
  且只删除其上 ``subject_type='user_group'`` 的授权——不碰普通知识空间、不碰
  user / department 维度授权。
- Dry-run 是默认行为，不写任何库；``--apply`` 才执行。
- **不可逆**：删除即收回该用户组成员的访问。务必先看 dry-run 输出再 ``--apply``。
- 跨租户维护脚本，运行在 ``bypass_tenant_filter()`` 下扫描所有租户的部门空间。
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402

RESOURCE_TYPE = "knowledge_space"


async def _collect_user_group_grants() -> tuple[list[int], list[tuple[int, int, str, bool]]]:
    """Return (scanned department space ids, user_group grants).

    Each grant is ``(space_id, group_id, relation, include_children)``.
    """
    from bisheng.knowledge.domain.models.department_knowledge_space import (
        DepartmentKnowledgeSpaceDao,
    )
    from bisheng.permission.domain.services.permission_service import PermissionService

    bindings = await DepartmentKnowledgeSpaceDao.aget_all()
    space_ids = sorted({int(b.space_id) for b in bindings})

    grants: list[tuple[int, int, str, bool]] = []
    for space_id in space_ids:
        permissions = await PermissionService.get_resource_permissions(
            object_type=RESOURCE_TYPE, object_id=str(space_id)
        )
        for perm in permissions:
            if getattr(perm, "subject_type", None) == "user_group":
                grants.append(
                    (
                        space_id,
                        int(perm.subject_id),
                        perm.relation,
                        bool(getattr(perm, "include_children", False)),
                    )
                )
    return space_ids, grants


async def _count_group_users(group_id: int) -> int:
    from bisheng.database.models.user_group import UserGroupDao

    try:
        users = await UserGroupDao.aget_group_users([group_id])
        return len(users or [])
    except Exception as exc:  # best-effort reporting only; never blocks cleanup
        logger.warning(f"F033 cleanup: could not count users for group {group_id}: {exc}")
        return -1


async def _revoke_grant(space_id: int, group_id: int, relation: str, include_children: bool) -> None:
    from bisheng.permission.domain.schemas.permission_schema import AuthorizeRevokeItem
    from bisheng.permission.domain.services.permission_service import PermissionService

    await PermissionService.authorize(
        object_type=RESOURCE_TYPE,
        object_id=str(space_id),
        revokes=[
            AuthorizeRevokeItem(
                subject_type="user_group",
                subject_id=group_id,
                relation=relation,
                include_children=include_children,
            )
        ],
        enforce_fga_success=True,
    )


async def _drop_binding(space_id: int, group_id: int, relation: str, include_children: bool) -> None:
    from bisheng.permission.api.endpoints.resource_permission import (
        _binding_lookup_keys,
        _get_bindings,
        _save_bindings,
    )

    bindings = await _get_bindings()
    binding_map = {b.get("key"): b for b in bindings if b.get("key")}
    for include in {include_children, True, False}:
        for key in _binding_lookup_keys(RESOURCE_TYPE, str(space_id), "user_group", group_id, relation, include):
            binding_map.pop(key, None)
    await _save_bindings(list(binding_map.values()))


async def run(apply: bool) -> None:
    # Cross-tenant maintenance script with no request scope: disable the tenant
    # filter so DAO reads/writes span every tenant's department spaces.
    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter():
        await _run_inner(apply)


async def _run_inner(apply: bool) -> None:
    space_ids, grants = await _collect_user_group_grants()
    logger.info(
        f"F033 cleanup: scanned {len(space_ids)} department knowledge space(s), found {len(grants)} user_group grant(s)"
    )
    for space_id, group_id, relation, include_children in grants:
        affected = await _count_group_users(group_id)
        logger.info(
            f"  space={space_id} group={group_id} relation={relation} "
            f"include_children={include_children} affected_users={affected}"
        )

    if not grants:
        logger.info("F033 cleanup: nothing to clean.")
        return

    if not apply:
        logger.info("[dry-run] no changes written. Re-run with --apply to execute.")
        return

    for space_id, group_id, relation, include_children in grants:
        await _revoke_grant(space_id, group_id, relation, include_children)
        await _drop_binding(space_id, group_id, relation, include_children)
        logger.info(f"F033 cleanup: revoked user_group grant space={space_id} group={group_id} relation={relation}")
    logger.info(f"F033 cleanup applied: removed {len(grants)} user_group grant(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the cleanup. Without this flag the script runs in dry-run mode.",
    )
    args = parser.parse_args()

    async def _amain() -> None:
        # Initialize the full app context (database + OpenFGA) so the revoke
        # path's FGA writes work. Without this only the lazily-registered
        # database context exists and PermissionService.authorize fails with
        # "FGAClient not available".
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.manager import close_app_context, initialize_app_context

        await initialize_app_context(config=settings)
        try:
            await run(apply=args.apply)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    asyncio.run(_amain())


if __name__ == "__main__":
    main()
