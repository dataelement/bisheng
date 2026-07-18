#!/usr/bin/env python3
"""一次性脚本：回填 ``user_tenant`` 表里缺失/未激活的默认租户归属。

## 背景

历史上这段逻辑挂在服务启动流程 ``init_default_data()`` 的
``_init_default_tenant`` 里，每次进程启动都会全表扫描
``users`` / ``user_tenant`` 做回填——在大用户量部署下，每个 API/Worker
进程启动都要付出一次反连接 + 一次"把全部 is_active=1 行读进内存"的代价，
属于把数据维护任务塞进了热路径。

实际上运行期并不依赖这张回填表：``UserPayload`` 的租户解析在用户没有
``user_tenant`` 行时会回退到 ``DEFAULT_TENANT_ID``（见
``bisheng/common/dependencies/user_deps.py``），登录/查询都不会因缺行而失败。
多租户登录路径还会在首次登录时惰性补挂默认租户。所以这段回填是**纯数据
一致性维护**，适合作为一次性脚本按需运行，而不是每次开机跑。

本脚本做两件幂等的事（与原启动逻辑等价）：

1. **补挂**：对没有任何 ``user_tenant`` 行的用户，插入一条默认租户行
   ``(tenant_id=1, is_default=1, is_active=1, status='active')``。
2. **激活孤儿默认行**：对 ``tenant_id=1 / is_default=1 / status='active'
   / is_active IS NULL`` 且该用户当前没有任何 ``is_active=1`` 行的记录，
   把 ``is_active`` 置 1（每用户只激活一条，沿用原逻辑的去重）。

另外会防御性地确认默认租户（id=1）存在，不存在则创建——正常情况下启动
流程已建好，这一步只是让脚本在裸库上也能自洽运行。

## 用法

在 ``src/backend`` 目录下运行（``config`` 必须与线上服务一致）：

    export config=config.yaml
    export PYTHONPATH="./"

    # Dry-run（默认，只统计将要写入的行数，不改 DB）
    python scripts/backfill_user_tenant_associations.py

    # 真正应用
    python scripts/backfill_user_tenant_associations.py --apply

## 安全保证

- 幂等：重复运行不会重复插入或重复激活。
- 只新增/激活，不删除、不 demote 任何已存在的行。
- 单次事务，``--apply`` 失败则整体回滚。
- DB-only，无需 ``initialize_app_context``；用 ``bypass_tenant_filter()``
  做跨租户读写。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.database.models.tenant import Tenant, UserTenant  # noqa: E402
from bisheng.user.domain.models.user import User  # noqa: E402


@dataclass
class BackfillStats:
    tenant_created: bool
    backfilled: int  # users that had no user_tenant row at all
    activated: int  # orphan default rows promoted to is_active=1


def run_backfill(session, *, apply: bool) -> BackfillStats:
    """Idempotently backfill default-tenant associations.

    Mirrors the original ``_init_default_tenant`` backfill exactly. When
    ``apply`` is False the function only counts what *would* change and never
    writes, so it doubles as the dry-run path.
    """
    with bypass_tenant_filter():
        # Defensive: ensure the default tenant exists so the script is
        # self-sufficient on a bare DB. Startup normally creates it.
        tenant = session.exec(select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID)).first()
        tenant_created = False
        if tenant is None:
            tenant = Tenant(
                id=DEFAULT_TENANT_ID,
                tenant_code="default",
                tenant_name="Default Tenant",
                status="active",
            )
            tenant_created = True
            if apply:
                session.add(tenant)
                session.commit()

        # (1) Users with no user_tenant row at all.
        users_without_tenant = session.exec(
            select(User.user_id).where(User.user_id.notin_(select(UserTenant.user_id)))
        ).all()
        if apply:
            for uid in users_without_tenant:
                session.add(
                    UserTenant(
                        user_id=uid,
                        tenant_id=DEFAULT_TENANT_ID,
                        is_default=1,
                        is_active=1,
                        status="active",
                    )
                )

        # (2) Orphan default rows: is_default=1 / status=active / is_active IS NULL
        # for users that have no current is_active=1 leaf.
        active_user_ids = set(session.exec(select(UserTenant.user_id).where(UserTenant.is_active == 1)).all())
        inactive_default_rows = session.exec(
            select(UserTenant).where(
                UserTenant.tenant_id == DEFAULT_TENANT_ID,
                UserTenant.is_default == 1,
                UserTenant.status == "active",
                UserTenant.is_active.is_(None),
            )
        ).all()
        activated = 0
        for row in inactive_default_rows:
            if row.user_id in active_user_ids:
                continue
            if apply:
                row.is_active = 1
                session.add(row)
            active_user_ids.add(row.user_id)  # one activation per user, as before
            activated += 1

        if apply and (users_without_tenant or activated):
            session.commit()

    return BackfillStats(
        tenant_created=tenant_created,
        backfilled=len(users_without_tenant),
        activated=activated,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually write rows. Default is dry-run.")
    args = parser.parse_args()

    with get_sync_db_session() as session:
        stats = run_backfill(session, apply=args.apply)

    mode = "APPLIED" if args.apply else "DRY-RUN (no changes written)"
    print(f"[{mode}]")
    if stats.tenant_created:
        print(f"  default tenant (id={DEFAULT_TENANT_ID}) was missing -> created")
    print(f"  users without any user_tenant row -> backfilled: {stats.backfilled}")
    print(f"  orphan default rows -> activated (is_active=1):   {stats.activated}")
    if not args.apply and (stats.backfilled or stats.activated or stats.tenant_created):
        print()
        print("Dry-run only. Re-run with --apply to write the changes above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
