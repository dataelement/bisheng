#!/usr/bin/env python3
"""首钢个人知识库清理脚本

清理「个人知识库」分类下的历史遗留空间，只保留系统按需自动创建的两类：

  1. 我的收藏            (is_favorite = True)
  2. {用户名}的知识库    (个人默认库，名称精确等于 "{user_name}的知识库")

其余归属于「个人」(personal) 作用域的知识空间一律视为删除候选。

删除复用应用层 ``KnowledgeSpaceService.delete_space(space_id, force=True)``，
``force`` 是系统维护旁路：跳过 我的收藏/个人库 的删除保护与调用方权限校验，并
抑制「空间已删除」的逐用户通知（避免批量清理骚扰用户）。级联会一并清理：
向量数据(milvus/ES)、minio 文件、数据库记录、成员、OpenFGA 权限 tuple、
私有标签库、channel 同步绑定 —— 避免留下孤儿数据。

使用方法（在容器内 src/backend 目录执行）：

    # 仅统计，不删除（默认 dry-run）：列出将删除 / 保留 / 跳过的空间
    python scripts/shougang_clean_personal_spaces.py --all-users

    # 确认删除（默认仅删空库；非空库会被列出并跳过）
    python scripts/shougang_clean_personal_spaces.py --all-users --apply

    # 连非空库一并删除（含其文件 / 向量 / minio）
    python scripts/shougang_clean_personal_spaces.py --all-users --apply --include-non-empty

    # 仅清理指定用户（先小范围验证效果）
    python scripts/shougang_clean_personal_spaces.py --user-id 5 --apply

安全设计：
  - 必须显式指定 --all-users 或 --user-id，避免一条命令误删全系统。
  - 默认 dry-run；--apply 才真正删除，且执行前先交互确认（输入 y）。
  - 默认跳过非空库；--include-non-empty 才连同其内容一起删除。
  - 全过程先打印计划（保留/删除/跳过清单），执行时逐条打印结果。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from types import SimpleNamespace

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def _personal_default_name(user_name: str) -> str:
    return f"{user_name}的知识库"


class _CleanupRequest:
    """Minimal stand-in for FastAPI ``Request`` used only by audit logging.

    ``get_request_ip`` reads ``headers.get(...)`` then falls back to
    ``client.host`` — an empty dict + a fixed host keeps the audit IP clean
    instead of leaking a MagicMock repr.
    """

    headers: dict = {}
    client = SimpleNamespace(host="127.0.0.1")


async def _collect_personal_spaces(session, user_id_filter):
    """Return (spaces, file_counts, user_name_by_id) for all personal-scope spaces.

    Runs under ``bypass_tenant_filter`` so it spans every tenant.
    """
    from sqlmodel import func, select

    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_scope import (
        KnowledgeSpaceLevelEnum,
        KnowledgeSpaceScope,
    )
    from bisheng.user.domain.models.user import User

    scope_rows = (
        await session.exec(
            select(KnowledgeSpaceScope.space_id).where(
                KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PERSONAL.value
            )
        )
    ).all()
    personal_ids = [int(sid) for sid in scope_rows]
    if not personal_ids:
        return [], {}, {}

    kstmt = select(Knowledge).where(
        Knowledge.id.in_(personal_ids),
        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
    )
    if user_id_filter is not None:
        kstmt = kstmt.where(Knowledge.user_id == user_id_filter)
    spaces = (await session.exec(kstmt)).all()
    if not spaces:
        return [], {}, {}

    space_ids = [int(s.id) for s in spaces]
    fc_rows = (
        await session.exec(
            select(KnowledgeFile.knowledge_id, func.count())
            .where(KnowledgeFile.knowledge_id.in_(space_ids))
            .group_by(KnowledgeFile.knowledge_id)
        )
    ).all()
    file_counts = {int(kid): int(cnt) for kid, cnt in fc_rows}

    user_ids = sorted({int(s.user_id) for s in spaces if s.user_id is not None})
    u_rows = (
        await session.exec(
            select(User.user_id, User.user_name).where(User.user_id.in_(user_ids))
        )
    ).all()
    user_name_by_id = {int(uid): name for uid, name in u_rows}

    return spaces, file_counts, user_name_by_id


def _classify(spaces, file_counts, user_name_by_id, include_non_empty):
    """Split personal spaces into keep / delete / skipped-non-empty buckets."""
    keep, to_delete, skipped_non_empty, unknown_owner = [], [], [], []
    for s in spaces:
        sid = int(s.id)
        owner_id = int(s.user_id) if s.user_id is not None else None
        user_name = user_name_by_id.get(owner_id) if owner_id is not None else None
        files = file_counts.get(sid, 0)
        is_fav = bool(getattr(s, "is_favorite", False))
        is_default = bool(user_name) and s.name == _personal_default_name(user_name)

        row = SimpleNamespace(
            id=sid, name=s.name, owner_id=owner_id, user_name=user_name,
            files=files, is_favorite=is_fav,
        )
        if is_fav or is_default:
            keep.append(row)
            continue
        if user_name is None:
            # Owner not found → cannot confirm the default library; do NOT delete.
            unknown_owner.append(row)
            continue
        if files > 0 and not include_non_empty:
            skipped_non_empty.append(row)
            continue
        to_delete.append(row)
    return keep, to_delete, skipped_non_empty, unknown_owner


def _print_rows(title, rows):
    print(f"\n{title} ({len(rows)}):")
    if not rows:
        print("    (无)")
        return
    for r in rows:
        fav = " [我的收藏]" if r.is_favorite else ""
        owner = f"{r.user_name}(uid={r.owner_id})" if r.user_name else f"uid={r.owner_id}"
        print(f"    space_id={r.id:<8} 文件={r.files:<5} owner={owner:<24} name={r.name}{fav}")


async def run(args: argparse.Namespace) -> int:
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.constants import AdminRole
    from bisheng.database.models.tenant import ROOT_TENANT_ID
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )

    print("=" * 68)
    print("首钢个人知识库清理脚本")
    print("=" * 68)
    scope_desc = "全部用户" if args.all_users else f"仅用户 uid={args.user_id}"
    print(f"  作用范围   : {scope_desc}")
    print(f"  非空库处理 : {'一并删除' if args.include_non_empty else '跳过（仅删空库）'}")
    print(f"  执行模式   : {'【实际删除】' if args.apply else '【dry-run，仅统计】'}")

    await initialize_app_context(config=settings)
    try:
        user_id_filter = None if args.all_users else args.user_id
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                spaces, file_counts, user_name_by_id = await _collect_personal_spaces(
                    session, user_id_filter
                )

        keep, to_delete, skipped, unknown = _classify(
            spaces, file_counts, user_name_by_id, args.include_non_empty
        )

        print(f"\n个人分类空间总数: {len(spaces)}")
        _print_rows("保留（我的收藏 / 个人默认库）", keep)
        _print_rows("待删除", to_delete)
        if not args.include_non_empty:
            _print_rows("跳过（非空库，需 --include-non-empty 才删除）", skipped)
        _print_rows("跳过（owner 缺失，无法确认默认库，保守不删）", unknown)

        if not to_delete:
            print("\n没有需要删除的空间，退出。")
            return 0

        if not args.apply:
            print(
                f"\n[dry-run] 以上 {len(to_delete)} 个空间将被删除。追加 --apply 参数执行实际删除。"
            )
            return 0

        answer = input(
            f"\n确认删除以上 {len(to_delete)} 个个人知识库？此操作不可逆，输入 y 继续，其他键退出: "
        ).strip().lower()
        if answer != "y":
            print("已取消。")
            return 0

        login_user = UserPayload(
            user_id=1,
            user_name="system-cleanup",
            tenant_id=ROOT_TENANT_ID,
            user_role=[AdminRole],
            is_global_super=True,
        )
        service = KnowledgeSpaceService(_CleanupRequest(), login_user)

        print("\n开始删除...")
        ok, failed = 0, 0
        for r in to_delete:
            try:
                with bypass_tenant_filter():
                    await service.delete_space(r.id, force=True)
                ok += 1
                print(f"  ✓ 已删除 space_id={r.id} name={r.name}")
            except Exception as e:  # noqa: BLE001 - keep cleaning remaining spaces
                failed += 1
                print(f"  ✗ 删除失败 space_id={r.id} name={r.name}: {e}")

        print(f"\n清理完成：成功 {ok} 个，失败 {failed} 个。")
        return 0 if failed == 0 else 1
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--all-users",
        action="store_true",
        default=False,
        help="清理全部用户的个人分类空间（除 我的收藏 + {用户名}的知识库）",
    )
    target.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="仅清理指定用户的个人分类空间",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="实际执行删除（默认为 dry-run，只统计不删除）",
    )
    parser.add_argument(
        "--include-non-empty",
        action="store_true",
        default=False,
        help="连含文件的非空库一并删除（默认跳过非空库）",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
