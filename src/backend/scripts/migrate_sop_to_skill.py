#!/usr/bin/env python3
"""One-shot migration: linsight_sop -> tenant custom skills (F035 Track G, design §8).

What it does
------------
Walks every ``linsight_sop`` row (ORDER BY tenant_id, id — stable re-runs),
converts each SOP into a skill bundle on disk plus a ``linsight_skill``
metadata row:

- ``display_name`` = original (Chinese) SOP name, truncated to 255; per-tenant
  duplicates get a "（2）/（3）" suffix;
- ``name`` (skill ID) = pypinyin slug of the SOP name (e.g. 标书撰写流程 ->
  ``biao-shu-zhuan-xie-liu-cheng``); empty/symbol-only names fall back to
  ``sop-{id}``; per-tenant duplicates get a ``-2/-3`` suffix;
- ``description`` = SOP description truncated to 1024; when missing it is
  generated via ``SOPManageService.generate_sop_summary`` (pass ``--no-llm``
  to skip the LLM call and use a static fallback);
- frontmatter carries ``metadata.display-name`` and ``metadata.sop-id`` —
  the latter makes re-runs idempotent: a SOP already migrated overwrites its
  own bundle instead of allocating a new suffixed name.

Output: a migration summary (per design §8.3) on stdout and as a JSON file.
This is an **ops artifact only** — there is no in-product migration report
(PRD §4.6.2, decision 2026-06-12). Failed/skipped items are handled manually:
fix & recreate via the management page, or split oversize SOPs and re-upload.

The legacy ``linsight_sop`` table is kept untouched (archive, design §8.6).

How to run (from src/backend/)
------------------------------
Dry-run is the default; pass ``--apply`` to persist:

    cd src/backend/
    PYTHONPATH=./ .venv/bin/python scripts/migrate_sop_to_skill.py
    PYTHONPATH=./ .venv/bin/python scripts/migrate_sop_to_skill.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/migrate_sop_to_skill.py --apply --no-llm
    PYTHONPATH=./ .venv/bin/python scripts/migrate_sop_to_skill.py --tenant-id 2 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402
from sqlmodel import col, select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.linsight.domain.models.linsight_skill import (  # noqa: E402
    SKILL_SOURCE_SOP_MIGRATED,
    LinsightSkill,
    LinsightSkillDao,
)
from bisheng.linsight.domain.models.linsight_sop import LinsightSOP  # noqa: E402
from bisheng.linsight.domain.services.skill_store import (  # noqa: E402
    MAX_DESCRIPTION_LEN,
    MAX_DISPLAY_NAME_LEN,
    SKILL_MD,
    SOP_ID_META_KEY,
    SkillStore,
    compose_skill_md,
    parse_skill_md,
    slugify_pinyin,
    validate_skill_name,
)

# Aligned with SOPManageService import/export limit (SopContentOverLimitError).
SOP_CONTENT_LIMIT = 50000
DEFAULT_TENANT_ID = 1
_FALLBACK_DESCRIPTION = "由历史 SOP「{name}」迁移生成的技能。"


def _dedupe_name(base: str, used: set[str]) -> tuple[str, bool]:
    """Allocate a unique skill ID: base, base-2, base-3 ... (stable re-runs)."""
    if base not in used:
        return base, False
    idx = 2
    while True:
        # keep the suffixed result within the 64-char limit
        suffix = f"-{idx}"
        candidate = base[: 64 - len(suffix)].rstrip("-") + suffix
        if candidate not in used:
            return candidate, True
        idx += 1


def _dedupe_display_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    idx = 2
    while True:
        suffix = f"（{idx}）"
        candidate = base[: MAX_DISPLAY_NAME_LEN - len(suffix)] + suffix
        if candidate not in used:
            return candidate
        idx += 1


async def _load_tenant_state(store: SkillStore, tenant_id: int) -> tuple[dict[str, LinsightSkill], set[str], set[str]]:
    """Existing skills of the tenant: sop_id -> row map (idempotency) + used name sets."""
    rows, _ = await LinsightSkillDao.get_page(page=1, page_size=10000)
    sop_map: dict[str, LinsightSkill] = {}
    used_names = {r.name for r in rows}
    used_display = {r.display_name for r in rows if r.display_name}
    for row in rows:
        if row.source != SKILL_SOURCE_SOP_MIGRATED:
            continue
        try:
            meta, _body = parse_skill_md(store.read_text(tenant_id, row.name))
            sop_id = str((meta.get("metadata") or {}).get(SOP_ID_META_KEY) or "")
            if sop_id:
                sop_map[sop_id] = row
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("cannot read SKILL.md of migrated skill {}: {}", row.name, exc)
    return sop_map, used_names, used_display


async def _generate_description(sop: LinsightSOP, no_llm: bool) -> tuple[str, str]:
    """Return (description, mode) where mode in {existing, generated, fallback}."""
    if sop.description and sop.description.strip():
        return sop.description.strip()[:MAX_DESCRIPTION_LEN], "existing"
    if not no_llm:
        try:
            from bisheng.linsight.domain.services.sop_manage import SOPManageService

            summary = await SOPManageService.generate_sop_summary(invoke_user_id=sop.user_id, sop_content=sop.content)
            desc = str(summary.get("sop_description") or "").strip()
            if desc and desc != "SOP Description":
                return desc[:MAX_DESCRIPTION_LEN], "generated"
        except Exception as exc:
            logger.warning("generate_sop_summary failed for sop#{}: {}", sop.id, exc)
    return _FALLBACK_DESCRIPTION.format(name=(sop.name or "").strip()[:64])[:MAX_DESCRIPTION_LEN], "fallback"


async def _migrate_tenant(
    store: SkillStore, tenant_id: int, sops: list[LinsightSOP], apply: bool, no_llm: bool, report: dict
) -> None:
    set_current_tenant_id(tenant_id)
    sop_map, used_names, used_display = await _load_tenant_state(store, tenant_id)
    print(f"── tenant_id={tenant_id} · {len(sops)} 条 SOP ────────────────")

    for sop in sops:
        raw_name = (sop.name or "").strip()
        content = sop.content or ""
        try:
            if len(content) > SOP_CONTENT_LIMIT:
                report["skipped"].append(
                    {
                        "tenant_id": tenant_id,
                        "sop_id": sop.id,
                        "sop_name": raw_name,
                        "reason": "SKIPPED_OVERSIZE",
                        "content_len": len(content),
                    }
                )
                print(f"[SKIP]    sop#{sop.id} 「{raw_name}」 content={len(content)} > {SOP_CONTENT_LIMIT}")
                continue
            if not raw_name and not content.strip():
                raise ValueError("empty name and content")

            existing = sop_map.get(str(sop.id))
            renamed = False
            if existing:
                name = existing.name
                display_name = existing.display_name or raw_name[:MAX_DISPLAY_NAME_LEN] or name
            else:
                base = slugify_pinyin(raw_name) or f"sop-{sop.id}"
                name, renamed = _dedupe_name(base, used_names)
                display_name = _dedupe_display_name(raw_name[:MAX_DISPLAY_NAME_LEN] or name, used_display)
            if err := validate_skill_name(name):
                raise ValueError(f"illegal generated skill id {name!r}: {err}")

            description, desc_mode = await _generate_description(sop, no_llm)
            skill_md = compose_skill_md(
                name=name,
                description=description,
                body=content,
                display_name=display_name,
                extra_metadata={SOP_ID_META_KEY: str(sop.id)},
            )

            if apply:
                size = store.write_bundle(tenant_id, name, {SKILL_MD: skill_md.encode("utf-8")})
                if existing:
                    existing.description, existing.size = description, size
                    existing.object_path = store.object_path(tenant_id, name)
                    await LinsightSkillDao.update(existing)
                else:
                    await LinsightSkillDao.create(
                        LinsightSkill(
                            tenant_id=tenant_id,
                            name=name,
                            display_name=display_name,
                            description=description,
                            enabled=True,
                            source=SKILL_SOURCE_SOP_MIGRATED,
                            object_path=store.object_path(tenant_id, name),
                            size=size,
                            created_by=sop.user_id,
                        )
                    )
            used_names.add(name)
            used_display.add(display_name)

            entry = {"tenant_id": tenant_id, "sop_id": sop.id, "skill_name": name, "display_name": display_name}
            if renamed:
                entry["renamed"] = True
            if desc_mode != "existing":
                entry["description_mode"] = desc_mode
            report["success"].append(entry)
            tag = "[RENAMED]" if renamed else ("[REUSE]  " if existing else "[OK]     ")
            print(f"{tag} sop#{sop.id} 「{raw_name}」 → {name}")
        except Exception as exc:
            logger.exception("migrate sop#{} failed", sop.id)
            report["failed"].append(
                {
                    "tenant_id": tenant_id,
                    "sop_id": sop.id,
                    "sop_name": raw_name,
                    "reason": "PARSE_FAILED" if isinstance(exc, ValueError) else "WRITE_FAILED",
                    "error": str(exc),
                }
            )
            print(f"[FAIL]    sop#{sop.id} 「{raw_name}」 {exc}")


async def _run(apply: bool, no_llm: bool, only_tenant: int | None, report_file: str) -> int:
    await initialize_app_context(config=settings)
    try:
        store = SkillStore()
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(LinsightSOP).order_by(col(LinsightSOP.tenant_id), col(LinsightSOP.id))
                result = await session.exec(statement)
                all_sops = list(result.all())

        groups: dict[int, list[LinsightSOP]] = defaultdict(list)
        for sop in all_sops:
            tenant_id = sop.tenant_id or DEFAULT_TENANT_ID
            if only_tenant is not None and tenant_id != only_tenant:
                continue
            groups[tenant_id].append(sop)

        total = sum(len(v) for v in groups.values())
        mode = "APPLY" if apply else "DRY-RUN"
        print(f"[scan] 共 {total} 条 SOP · {len(groups)} 个租户 · mode={mode}")

        report: dict = {"summary": {}, "success": [], "skipped": [], "failed": []}
        for tenant_id in sorted(groups):
            await _migrate_tenant(store, tenant_id, groups[tenant_id], apply, no_llm, report)

        report["summary"] = {
            "mode": mode,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total": total,
            "success": len(report["success"]),
            "renamed": sum(1 for e in report["success"] if e.get("renamed")),
            "skipped": len(report["skipped"]),
            "failed": len(report["failed"]),
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        print("══ 迁移摘要（运维产物，无管理页报告界面）══")
        print(payload)
        with open(report_file, "w", encoding="utf-8") as fh:
            fh.write(payload)
        print(f"[report] 已写入 {report_file}")
        if not apply:
            print("[dry-run] 未写入任何数据 · 加 --apply 正式执行")
        return 0 if not report["failed"] else 1
    finally:
        await close_app_context()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate linsight_sop rows into tenant custom skills (F035)")
    parser.add_argument("--apply", action="store_true", help="persist changes (default: dry-run)")
    parser.add_argument(
        "--no-llm", action="store_true", help="skip LLM summary for missing descriptions, use static fallback"
    )
    parser.add_argument("--tenant-id", type=int, default=None, help="restrict to a single tenant")
    parser.add_argument(
        "--report-file",
        default="migrate_sop_to_skill_report.json",
        help="path of the JSON summary artifact (default: ./migrate_sop_to_skill_report.json)",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.apply, args.no_llm, args.tenant_id, args.report_file))


if __name__ == "__main__":
    raise SystemExit(main())
