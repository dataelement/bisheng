"""把重建失败留下的容器级 FAILED 状态收敛回 PUBLISHED。

重建 worker 过去在任何一个文件重建失败时，会把**整个**知识库/知识空间标成
``KnowledgeState.FAILED``。这个标记原本是给"下次自动重建"用的，但失败文件现在已经
不能自动重建、必须走重新解析，所以它不再有任何用途，只剩副作用：权限目标解析要求
容器处于 ``PUBLISHED``（``knowledge_permission_service.py``），于是一个坏文件就让整
个知识空间在权限层面"不存在"，接口报 19003「资源类型或 ID 无效」，用户根本进不去。

服务端已经不再写这个状态（``rebuild_knowledge_worker.py``）；本脚本收敛存量数据。

**只动容器状态，不碰文件状态**：哪些文件重建失败仍然记录在 ``knowledge_file`` 上，
那才是准确的信息，重新解析时要靠它。

Usage (from ``src/backend/``，默认 dry-run):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/converge_knowledge_rebuild_failed_state.py
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/converge_knowledge_rebuild_failed_state.py --apply
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/converge_knowledge_rebuild_failed_state.py --scope all --apply
```

``--scope space``（默认）只收敛知识空间；``all`` 还包括普通知识库和个人知识库 ——
它们由同一个 worker 标记，同样受影响。QA 知识库不在范围内：它的 FAILED 由
``worker/knowledge/qa.py`` 另行写入，语义未变。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    KnowledgeState,
    KnowledgeTypeEnum,
)

SCOPES: dict[str, tuple[KnowledgeTypeEnum, ...]] = {
    "space": (KnowledgeTypeEnum.SPACE,),
    "all": (
        KnowledgeTypeEnum.SPACE,
        KnowledgeTypeEnum.NORMAL,
        KnowledgeTypeEnum.PRIVATE,
    ),
}


async def run(scope: str, apply: bool) -> int:
    types = SCOPES[scope]
    type_values = [item.value for item in types]
    failed = KnowledgeState.FAILED.value
    published = KnowledgeState.PUBLISHED.value

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, name, type, tenant_id FROM knowledge "
                        "WHERE state = :failed AND type IN :types ORDER BY type, id"
                    ).bindparams(failed=failed, types=tuple(type_values))
                )
            ).all()

            print(f"scope={scope} 命中 {len(rows)} 条容器级 FAILED 记录")
            for row in rows:
                print(f"  id={row[0]:<8} type={KnowledgeTypeEnum(row[2]).name:<8} tenant={row[3]}  {row[1]}")

            if not rows:
                print("无需改动")
                return 0
            if not apply:
                print("\n[dry-run] 未写入任何数据；加 --apply 执行")
                return 0

            result = await session.execute(
                text("UPDATE knowledge SET state = :published WHERE state = :failed AND type IN :types").bindparams(
                    published=published, failed=failed, types=tuple(type_values)
                )
            )
            await session.commit()
            print(f"\n已更新 {result.rowcount} 条 -> PUBLISHED")

            remaining = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge WHERE state = :failed AND type IN :types").bindparams(
                        failed=failed, types=tuple(type_values)
                    )
                )
            ).scalar_one()
            print(f"剩余容器级 FAILED：{remaining}（应为 0）")
            return 0 if remaining == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        default="space",
        help="space=仅知识空间（默认）；all=再加普通知识库与个人知识库",
    )
    parser.add_argument("--apply", action="store_true", help="执行写入；默认只报告")
    args = parser.parse_args()
    return asyncio.run(run(args.scope, args.apply))


if __name__ == "__main__":
    sys.exit(main())
