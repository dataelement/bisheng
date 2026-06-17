#!/usr/bin/env python3
"""Dedupe redundant preset tools / tool-types that leaked into a single tenant.

WHY
---
During earlier development the "copy builtin tools to a child tenant" logic did
not set ``tenant_id`` explicitly. Running under a super-admin (root) context,
``before_flush`` + the column ``server_default=1`` stamped every copied row with
``tenant_id=1`` (root). Because ``t_gpts_tools.tool_key`` had no unique
constraint, this silently produced multiple rows sharing the same
``(tool_key, tenant_id)`` under root — e.g. ``web_search`` x3, ``arxiv`` x3.

Consequences:
- ``GptsToolsDao.get_tool_by_tool_key()`` does ``.first()`` with no ORDER BY, so
  the workflow runtime may resolve a *different* duplicate than the one edited in
  the tool-management UI -> "config not taking effect / reads stale provider".
- The new ``UniqueConstraint(tool_key, tenant_id)`` on ``GptsTools`` cannot be
  created while duplicates remain.

WHAT
----
For PRESET tools/types only (the confirmed root cause), within every tenant:
  1. Group tools by (tool_key, tenant_id); keep the smallest id as canonical.
  2. Re-point ``assistantlink.tool_id`` from each stray -> canonical.
  3. Group preset types by (name, tenant_id); keep the smallest id as canonical;
     re-point surviving ``t_gpts_tools.type`` from stray type -> canonical type.
  4. Hard-delete the stray tool rows and stray preset-type rows (hard delete is
     required so the unique constraint can be added afterwards).

NON-preset duplicates (custom API / MCP tools) are *reported only*, never
deleted — they should not normally exist and need human judgement.

References this script does NOT auto-fix (reported for manual follow-up):
- Workstation / workbench config JSON that embeds a stray tool_id / type_id.
- OpenFGA permission tuples keyed on a stray tool-type id (harmless dangling
  tuples after delete, but worth cleaning).

HOW
---
Dry-run (default, no writes):
    cd src/backend/
    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/dedupe_gpts_tools.py

Apply (writes + hard delete; BACK UP THE DB FIRST):
    python scripts/dedupe_gpts_tools.py --apply

After a clean apply, add the unique constraint manually, e.g.:
    ALTER TABLE t_gpts_tools
      ADD CONSTRAINT uk_gpts_tools_key_tenant UNIQUE (tool_key, tenant_id);
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from collections import defaultdict  # noqa: E402

from sqlmodel import col, delete, select, update  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.assistant import AssistantLink  # noqa: E402
from bisheng.tool.domain.const import ToolPresetType  # noqa: E402
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType  # noqa: E402


def _group_by(rows, key):
    grouped: dict = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    # deterministic: smallest id first => canonical is groups[k][0]
    for k in grouped:
        grouped[k].sort(key=lambda r: r.id)
    return grouped


async def dedupe(apply: bool) -> int:
    report = {
        "apply": apply,
        "preset_tool_groups_with_dupes": 0,
        "stray_tools_deleted": 0,
        "assistant_links_repointed": 0,
        "preset_type_groups_with_dupes": 0,
        "stray_types_deleted": 0,
        "tool_type_fk_repointed": 0,
        "non_preset_tool_dupes": [],  # reported only
    }

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            tools = (await session.exec(select(GptsTools))).all()
            types = (await session.exec(select(GptsToolsType))).all()
            links = (await session.exec(select(AssistantLink))).all()

        # assistant_id linkage: tool_id -> list of AssistantLink
        links_by_tool: dict[int, list] = defaultdict(list)
        for link in links:
            links_by_tool[link.tool_id].append(link)

        # ---- 1) tools: dedupe by (tool_key, tenant_id) ----
        tool_groups = _group_by(tools, lambda r: (r.tool_key, r.tenant_id))
        stray_tool_ids: list[int] = []
        for (tool_key, tenant_id), group in tool_groups.items():
            if len(group) < 2:
                continue
            non_preset = [r for r in group if r.is_preset != ToolPresetType.PRESET.value]
            if non_preset:
                # Do NOT auto-delete custom/MCP duplicates — surface them.
                report["non_preset_tool_dupes"].append(
                    {
                        "tool_key": tool_key,
                        "tenant_id": tenant_id,
                        "ids": [r.id for r in group],
                        "is_preset": [r.is_preset for r in group],
                    }
                )
                continue

            report["preset_tool_groups_with_dupes"] += 1
            canonical = group[0]
            strays = group[1:]
            for stray in strays:
                # re-point assistant links stray -> canonical
                for link in links_by_tool.get(stray.id, []):
                    report["assistant_links_repointed"] += 1
                    if apply:
                        await session.exec(
                            update(AssistantLink)
                            .where(
                                col(AssistantLink.assistant_id) == link.assistant_id,
                                col(AssistantLink.tool_id) == stray.id,
                            )
                            .values(tool_id=canonical.id)
                        )
                stray_tool_ids.append(stray.id)

        # ---- 2) preset types: dedupe by (name, tenant_id) ----
        preset_types = [t for t in types if t.is_preset == ToolPresetType.PRESET.value]
        type_groups = _group_by(preset_types, lambda r: (r.name, r.tenant_id))
        stray_type_ids: list[int] = []
        canonical_type_id_by_stray: dict[int, int] = {}
        for _key, group in type_groups.items():
            if len(group) < 2:
                continue
            report["preset_type_groups_with_dupes"] += 1
            canonical = group[0]
            for stray in group[1:]:
                canonical_type_id_by_stray[stray.id] = canonical.id
                stray_type_ids.append(stray.id)

        # re-point surviving tools' .type from stray type -> canonical type
        surviving_tool_ids = {t.id for t in tools} - set(stray_tool_ids)
        for tool in tools:
            if tool.id not in surviving_tool_ids:
                continue
            new_type = canonical_type_id_by_stray.get(tool.type)
            if new_type is not None and new_type != tool.type:
                report["tool_type_fk_repointed"] += 1
                if apply:
                    await session.exec(update(GptsTools).where(col(GptsTools.id) == tool.id).values(type=new_type))

        # ---- 3) hard-delete strays (tools first, then types) ----
        report["stray_tools_deleted"] = len(stray_tool_ids)
        report["stray_types_deleted"] = len(stray_type_ids)
        if apply:
            if stray_tool_ids:
                await session.exec(delete(GptsTools).where(col(GptsTools.id).in_(stray_tool_ids)))
            if stray_type_ids:
                await session.exec(delete(GptsToolsType).where(col(GptsToolsType.id).in_(stray_type_ids)))
            await session.commit()

        # ---- 4) post-check: remaining (tool_key, tenant_id) dupes (incl. non-preset) ----
        remaining = []
        if apply:
            with bypass_tenant_filter():
                tools2 = (await session.exec(select(GptsTools))).all()
            for (tk, tid), group in _group_by(tools2, lambda r: (r.tool_key, r.tenant_id)).items():
                if len(group) > 1:
                    remaining.append({"tool_key": tk, "tenant_id": tid, "ids": [r.id for r in group]})
        report["remaining_dupes_after_apply"] = remaining

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not apply:
        print(
            "\n[dry-run] no changes written. Re-run with --apply to perform the cleanup (BACK UP THE DB FIRST).",
            file=sys.stderr,
        )
    elif report.get("remaining_dupes_after_apply"):
        print(
            "\n[warn] duplicates remain (likely non-preset). Resolve them before adding the unique constraint.",
            file=sys.stderr,
        )
        return 2
    else:
        print(
            "\n[done] no (tool_key, tenant_id) duplicates remain. Safe to add UNIQUE(tool_key, tenant_id).",
            file=sys.stderr,
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the cleanup (re-point references + hard delete strays). Default is dry-run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    async def _main() -> int:
        try:
            return await dedupe(args.apply)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    raise SystemExit(asyncio.run(_main()))
