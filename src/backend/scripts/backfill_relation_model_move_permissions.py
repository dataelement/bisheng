#!/usr/bin/env python3
"""一次性脚本：把 F034 新增的「移动文件 / 移动文件夹」权限补进已被冻结的系统权限档位。

## 背景

知识空间后台「权限配置」里「所有者 / 可管理 / 可编辑 / 可查看」四个系统档位，
存在全局配置行 ``permission_relation_models_v1``（``config`` 表，key 唯一、无 tenant_id）。

每个档位有个 ``permissions_explicit`` 开关：

- ``permissions_explicit=False``（默认 seed）：勾选状态**读取时按代码模板动态计算**，
  ``default_permission_ids_for_relation(relation)`` 现算——新增权限（本次的
  ``move_file`` / ``move_folder``）会自动出现，**无需本脚本**。
- ``permissions_explicit=True``：勾选状态用**保存那一刻冻结的快照**
  （``update_relation_model`` 保存 permissions 时会把开关翻成 True）。模板后来
  新增的权限不会再补进去——这正是「所有 / 管理 缺了移动权限」的根因。

代码升级不会修改这些已冻结的库内快照，所以需要本脚本一次性补齐。

## 这个脚本做什么

对配置里的**系统档位**（``is_system=True``）且**已冻结**（``permissions_explicit=True``）：

- 计算该档位按规则**应当默认拥有**的目标权限：
  ``{move_file, move_folder} ∩ default_permission_ids_for_relation(该档 relation)``
  - 所有者 / 可管理 / 可编辑（can_edit 及以上）→ 两个都补；
  - 可查看（viewer）→ 交集为空，**不补**。
- 仅把缺失的这两个 id **并入** ``permissions[]``，不动其它任何已勾选项
  （保住管理员真正自定义过的内容）。

幂等：已补齐的档位重跑无变化。不动自定义（非系统）档位、不动 explicit=False 档位
（它们本来就动态、已正确）。

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只打印将要改动，不写 DB）
    python scripts/backfill_relation_model_move_permissions.py

    # 真正应用
    python scripts/backfill_relation_model_move_permissions.py --apply

## 安全保证

- 只新增 ``move_file`` / ``move_folder``，绝不删除或重置任何已有勾选。
- 只动 system + explicit=True 的档位；自定义档位、动态档位一律跳过。
- 单次写整行配置，失败回滚。
- 该 config key 不走 Redis 缓存（``aget_config_by_key`` 直连 DB），运行中的进程
  下次读取即生效，无需重启。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.models.config import Config  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.permission.domain.relation_model_backfill import (  # noqa: E402
    RELATION_MODELS_KEY as _RELATION_MODELS_KEY,
)
from bisheng.permission.domain.relation_model_backfill import (
    apply_move_permission_backfill,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正写入 DB（默认仅 dry-run）")
    args = parser.parse_args()

    with get_sync_db_session() as session:
        row = session.exec(select(Config).where(Config.key == _RELATION_MODELS_KEY)).first()
        if not row or not (row.value or "").strip():
            print(f"[skip] 未找到配置行 {_RELATION_MODELS_KEY}（全新/未初始化环境，系统档动态计算，无需补齐）")
            return 0
        try:
            models = json.loads(row.value)
        except Exception as exc:
            print(f"[error] 配置 JSON 解析失败：{exc}")
            return 1

        updated, changes = apply_move_permission_backfill(models)

        if not changes:
            print("[ok] 没有需要补齐的档位（已全部正确或本就是动态档位）")
            return 0

        print(f"将补齐 {len(changes)} 个档位：")
        for c in changes:
            print(f"  - {c['name']}({c['id']}, relation={c['relation']}) += {c['added']}")

        if not args.apply:
            print("\n[dry-run] 未写入。确认无误后加 --apply 真正应用。")
            return 0

        row.value = json.dumps(updated, ensure_ascii=False)
        session.add(row)
        session.commit()
        print(f"\n[applied] 已写回 {_RELATION_MODELS_KEY}。运行中的进程下次读取即生效，无需重启。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
