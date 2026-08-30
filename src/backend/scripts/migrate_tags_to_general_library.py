#!/usr/bin/env python3
"""Move public-library tags into 「通用标签库」 and bind every knowledge space to it.

Keeps ``tag.id`` unchanged: only ``tag.business_id`` is rewritten. Does not touch
``taglink``, ``review_tag``, or ``review_tag_link``. Does not delete source
libraries (empty shells remain so pending review rows can still point at them).

Default is dry-run. ``--apply`` writes one transaction per run.

Usage (from ``src/backend``):

    python scripts/migrate_tags_to_general_library.py
    python scripts/migrate_tags_to_general_library.py --tenant 1
    python scripts/migrate_tags_to_general_library.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

_SCRIPTS_DIR = os.path.abspath(os.path.dirname(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from loguru import logger  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlmodel import select  # noqa: E402
from tag_library_migrate_support import (  # noqa: E402
    GENERAL_LIBRARY_NAME,
    MAX_LIBRARY_TAGS,
    SPACE_TYPE,
    fetch_libraries,
    fetch_links,
    fetch_tag_library_tags,
    public_libraries,
    rebuild_library_name_lists,
)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.database.models.tag import Tag  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (  # noqa: E402
    KnowledgeSpaceTagLibrary,
)
from bisheng.knowledge.domain.models.knowledge_tag_library_link import (  # noqa: E402
    KnowledgeTagLibraryLink,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import (  # noqa: E402
    TagLibraryTagService,
)


class Plan:
    def __init__(self) -> None:
        self.tag_moves: list[tuple[Tag, KnowledgeSpaceTagLibrary, KnowledgeSpaceTagLibrary]] = []
        self.link_inserts: list[KnowledgeTagLibraryLink] = []
        self.link_deletes: list[KnowledgeTagLibraryLink] = []
        self.libraries_to_resync: list[KnowledgeSpaceTagLibrary] = []
        self.duplicate_names: list[tuple[int, str, list[int]]] = []
        self.errors: list[str] = []
        self.tenant_ids: set[int] = set()


def _libraries_by_tenant(libraries: list[KnowledgeSpaceTagLibrary]) -> dict[int, list[KnowledgeSpaceTagLibrary]]:
    grouped: dict[int, list[KnowledgeSpaceTagLibrary]] = defaultdict(list)
    for library in public_libraries(libraries):
        grouped[int(library.tenant_id or 1)].append(library)
    return grouped


def _pick_general(public: list[KnowledgeSpaceTagLibrary], tenant_id: int) -> KnowledgeSpaceTagLibrary | None:
    matches = [row for row in public if (row.name or "").strip() == GENERAL_LIBRARY_NAME]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None
    raise ValueError(f"tenant {tenant_id} 有 {len(matches)} 座「{GENERAL_LIBRARY_NAME}」, 请人工确认后再跑")


def build_plan(session, tenant_id: int | None) -> Plan:
    plan = Plan()
    libraries = fetch_libraries(session, tenant_id)
    tags = fetch_tag_library_tags(session, tenant_id)
    links = fetch_links(session, tenant_id)
    space_statement = select(Knowledge).where(Knowledge.type == SPACE_TYPE)
    if tenant_id is not None:
        space_statement = space_statement.where(Knowledge.tenant_id == tenant_id)
    spaces = list(session.exec(space_statement).all())

    tags_by_library: dict[str, list[Tag]] = defaultdict(list)
    for tag in tags:
        tags_by_library[str(tag.business_id or "")].append(tag)

    existing_pairs = {(int(link.knowledge_id), int(link.tag_library_id)) for link in links}

    for current_tenant, public in _libraries_by_tenant(libraries).items():
        plan.tenant_ids.add(current_tenant)
        try:
            general = _pick_general(public, current_tenant)
        except ValueError as exc:
            plan.errors.append(str(exc))
            continue
        if general is None or general.id is None:
            plan.errors.append(f"tenant {current_tenant} 没有公共库「{GENERAL_LIBRARY_NAME}」")
            continue

        sources = [row for row in public if int(row.id) != int(general.id)]
        source_ids = {int(row.id) for row in sources if row.id is not None}
        general_id = int(general.id)
        general_key = str(general_id)

        moving: list[Tag] = []
        for source in sources:
            for tag in tags_by_library.get(str(source.id), []):
                moving.append(tag)
                plan.tag_moves.append((tag, source, general))

        after_count = len(tags_by_library.get(general_key, [])) + len(moving)
        if after_count > MAX_LIBRARY_TAGS:
            plan.errors.append(f"tenant {current_tenant} 并入后标签行={after_count}, 超过单库上限 {MAX_LIBRARY_TAGS}")

        names: dict[str, list[int]] = defaultdict(list)
        for tag in tags_by_library.get(general_key, []) + moving:
            names[(tag.name or "").strip()].append(int(tag.id))
        for name, ids in sorted(names.items()):
            if name and len(ids) > 1:
                plan.duplicate_names.append((current_tenant, name, ids))

        tenant_spaces = [space for space in spaces if int(space.tenant_id or 1) == current_tenant]
        for space in tenant_spaces:
            if space.id is None:
                continue
            pair = (int(space.id), general_id)
            if pair in existing_pairs:
                continue
            plan.link_inserts.append(
                KnowledgeTagLibraryLink(
                    tenant_id=current_tenant,
                    knowledge_id=int(space.id),
                    tag_library_id=general_id,
                    sort_order=0,
                )
            )

        for link in links:
            if int(link.tenant_id or 1) != current_tenant:
                continue
            if int(link.tag_library_id) in source_ids:
                plan.link_deletes.append(link)

        resync_ids = {general_id, *source_ids}
        plan.libraries_to_resync.extend([row for row in public if row.id in resync_ids])

    return plan


def apply_plan(session, plan: Plan) -> None:
    general_id_by_source_tag: dict[int, str] = {}
    for tag, _source, general in plan.tag_moves:
        if tag.id is None or general.id is None:
            continue
        general_id_by_source_tag[int(tag.id)] = str(general.id)

    if general_id_by_source_tag:
        current = list(session.exec(select(Tag).where(Tag.id.in_(list(general_id_by_source_tag)))).all())
        for tag in current:
            tag.business_id = general_id_by_source_tag[int(tag.id)]
            session.add(tag)

    for link in plan.link_inserts:
        session.add(link)
    session.flush()

    delete_ids = [int(link.id) for link in plan.link_deletes if link.id is not None]
    if delete_ids:
        session.exec(delete(KnowledgeTagLibraryLink).where(KnowledgeTagLibraryLink.id.in_(delete_ids)))

    seen_library_ids: set[int] = set()
    for library in plan.libraries_to_resync:
        if library.id in seen_library_ids:
            continue
        seen_library_ids.add(int(library.id))
        live = session.exec(select(KnowledgeSpaceTagLibrary).where(KnowledgeSpaceTagLibrary.id == library.id)).first()
        if live:
            rebuild_library_name_lists(session, live)


def _print_plan(plan: Plan) -> None:
    print(f"将改写的 tag.business_id:           {len(plan.tag_moves)}")
    print(f"将新增的知识空间→通用库绑定:       {len(plan.link_inserts)}")
    print(f"将删除的其它公共库绑定:             {len(plan.link_deletes)}")
    print(f"将重写清单的标签库:                 {len({int(row.id) for row in plan.libraries_to_resync})}")
    print()

    if plan.tag_moves:
        print("标签归属 (id 不变):")
        for tag, source, general in plan.tag_moves[:50]:
            print(f"  tag.id={tag.id} 「{tag.name}」  {source.name}({source.id}) -> {general.name}({general.id})")
        if len(plan.tag_moves) > 50:
            print(f"  ... 另有 {len(plan.tag_moves) - 50} 条")
        print()

    if plan.duplicate_names:
        print("警告: 并入后同一座通用库会出现同名多行 (按要求不改 tag.id, 不会合并):")
        for tenant_id, name, ids in plan.duplicate_names:
            print(f"  tenant={tenant_id} 「{name}」 tag.id={ids}")
        print()

    if plan.errors:
        print("错误 (有错误时不会 --apply):")
        for message in plan.errors:
            print(f"  {message}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="将其它公共标签库的标签归属到通用标签库, 并绑定全部知识空间")
    parser.add_argument("--tenant", type=int, default=None, help="只处理该租户, 默认全部租户")
    parser.add_argument("--apply", action="store_true", help="真正写库, 默认 dry-run")
    args = parser.parse_args()

    with bypass_tenant_filter(), get_sync_db_session() as session:
        plan = build_plan(session, args.tenant)
        _print_plan(plan)
        if plan.errors:
            return 1
        if not args.apply:
            print("Dry-run, 未写库。确认已跑 backup_tag_library_migration.py 后加 --apply 执行。")
            return 0
        apply_plan(session, plan)
        session.commit()

    for tenant_id in sorted(plan.tenant_ids):
        try:
            TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_sync(tenant_id)
        except Exception:
            logger.exception("failed to invalidate tag resolver catalog cache for tenant_id={}", tenant_id)

    print("已提交。未删除源标签库, 未改 review_tag / taglink / tag.id。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
