#!/usr/bin/env python3
"""Dev/QA fixture: seed ONE tenant skill with maxed-out field lengths so the
skill-detail drawer overflow handling can be eyeballed (F035 Track I,
2026-06-16 UI hardening of ``SkillDetailSheet.tsx``).

This is NOT a migration. It inserts a single "overflow QA" skill into a tenant
(default: tenant 1) whose fields are pushed to their limits, plus a SKILL.md
body carrying an unbroken (space-less) token:

- ``display_name`` -> 255 chars (title truncation + tooltip)
- ``name`` (skill ID) -> 64 chars, ``[a-z0-9-]`` legal (ID chip truncation)
- ``description`` -> 1024 chars, no spaces (description ``line-clamp-2`` + tooltip)
- SKILL.md body -> a 400-char unbroken token (preview ``break-words``)
- one bundle asset with a long file name (file-tree truncation)

Idempotent: re-running replaces the same skill (delete bundle + row, recreate).
Dry-run is the default; pass ``--apply`` to persist, ``--remove`` to delete it.

How to run (from src/backend/)
------------------------------
    cd src/backend/
    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py            # dry-run
    PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py --apply    # create
    PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py --remove   # clean up
    PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py --tenant-id 1 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, set_current_tenant_id  # noqa: E402
from bisheng.linsight.domain.models.linsight_skill import (  # noqa: E402
    SKILL_SOURCE_MANUAL,
    LinsightSkill,
    LinsightSkillDao,
)
from bisheng.linsight.domain.services.skill_store import (  # noqa: E402
    MAX_DESCRIPTION_LEN,
    MAX_DISPLAY_NAME_LEN,
    MAX_NAME_LEN,
    SKILL_MD,
    SkillStore,
    compose_skill_md,
    validate_skill_name,
)

# Identifiable, idempotent skill ID suffix so re-runs hit the same row and the
# fixture is easy to spot/delete in the management list.
_NAME_SUFFIX = "-overflow-qa"


def _ramp(n: int) -> str:
    """An n-char string of repeating digits 0123456789... (no spaces — the
    worst case for word wrapping)."""
    return ("0123456789" * (n // 10 + 1))[:n]


def _build_fields() -> tuple[str, str, str, dict[str, bytes]]:
    name = _ramp(MAX_NAME_LEN - len(_NAME_SUFFIX)) + _NAME_SUFFIX  # exactly 64 chars
    if err := validate_skill_name(name):
        raise SystemExit(f"generated skill id is illegal: {err} ({name!r})")

    display_name = ("【溢出测试 overflow】" + _ramp(MAX_DISPLAY_NAME_LEN))[:MAX_DISPLAY_NAME_LEN]
    description = (
        "【描述溢出测试·无空格超长串，用于验证 line-clamp-2 截断与 break-words 折行，悬停应显示完整文本】"
        + _ramp(MAX_DESCRIPTION_LEN)
    )[:MAX_DESCRIPTION_LEN]

    body = (
        "# 溢出测试技能 " + _ramp(60) + "\n\n"
        "本技能用于验证**技能详情抽屉**在超长内容下的排版是否正确。下面是一段没有空格的"
        "超长 token，用来检验预览区 Markdown 段落的 `break-words` 是否在面板内折行（而非横向溢出）：\n\n"
        + _ramp(400)
        + "\n\n"
        "## 普通小标题\n\n"
        "- 列表项一：正常中文内容，应当随面板宽度正常换行。\n"
        "- 列表项二（超长无空格 token）：" + _ramp(120) + "\n\n"
        "## 代码块（应保留自身横向滚动，不被 break-words 影响）\n\n"
        "```text\n" + _ramp(200) + "\n```\n\n"
        "正文结束。\n"
    )
    skill_md = compose_skill_md(name=name, description=description, body=body, display_name=display_name)

    asset_path = "reference/long-unbroken-asset-" + _ramp(40) + ".md"
    files = {
        SKILL_MD: skill_md.encode("utf-8"),
        asset_path: b"# asset\n\nA bundle asset with a deliberately long file name "
        b"to exercise the file-tree truncation + tooltip.\n",
    }
    return name, display_name, description, files


async def _run(apply: bool, remove: bool, tenant_id: int) -> int:
    name, display_name, description, files = _build_fields()
    store = SkillStore()

    await initialize_app_context(config=settings)
    try:
        set_current_tenant_id(tenant_id)
        existing = await LinsightSkillDao.get_by_name(name)

        if remove:
            if existing:
                await LinsightSkillDao.delete_by_name(name)
            removed = store.delete(tenant_id, name)
            print(f"[remove] tenant={tenant_id} name={name} db_row={'yes' if existing else 'no'} bundle={removed}")
            return 0

        print(f"── overflow QA skill (tenant={tenant_id}) ──────────────")
        print(f"  name        ({len(name)}/{MAX_NAME_LEN})  {name}")
        print(f"  display_name({len(display_name)}/{MAX_DISPLAY_NAME_LEN})  {display_name[:48]}…")
        print(f"  description ({len(description)}/{MAX_DESCRIPTION_LEN})  {description[:48]}…")
        print(f"  files: {', '.join(files)}")
        if not apply:
            print("[dry-run] 未写入 · 加 --apply 正式创建")
            return 0

        size = store.write_bundle(tenant_id, name, files)
        object_path = store.object_path(tenant_id, name)
        if existing:
            existing.display_name = display_name
            existing.description = description
            existing.enabled = True
            existing.object_path = object_path
            existing.size = size
            await LinsightSkillDao.update(existing)
            print(f"[apply] updated existing skill row id={existing.id}")
        else:
            created = await LinsightSkillDao.create(
                LinsightSkill(
                    tenant_id=tenant_id,
                    name=name,
                    display_name=display_name,
                    description=description,
                    enabled=True,
                    source=SKILL_SOURCE_MANUAL,
                    object_path=object_path,
                    size=size,
                    created_by=1,
                )
            )
            print(f"[apply] created skill row id={created.id} object_path={object_path} size={size}")
        print("[done] 打开 构建-首页-技能管理，点开该技能即可体验详情抽屉超长内容排版")
        return 0
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist the fixture (default: dry-run)")
    parser.add_argument("--remove", action="store_true", help="delete the fixture (db row + bundle) and exit")
    parser.add_argument("--tenant-id", type=int, default=DEFAULT_TENANT_ID, help="target tenant (default: 1)")
    args = parser.parse_args()
    return asyncio.run(_run(args.apply, args.remove, args.tenant_id))


if __name__ == "__main__":
    raise SystemExit(main())
