"""Profile GET /knowledge/space/{id}/tag latency breakdown. Run from src/backend:

uv run python scripts/profile_get_space_tags.py --space-id 137
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from unittest.mock import MagicMock

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.dependencies.user_deps import UserPayload  # noqa: E402
from bisheng.database.models.tag import TagBusinessTypeEnum, TagDao
from bisheng.knowledge.domain.models.knowledge_tag_library_link import KnowledgeTagLibraryLinkDao
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


async def _timed(label: str, coro):
    start = time.perf_counter()
    result = await coro
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"{label:48s} {elapsed_ms:8.1f} ms")
    return result


async def profile(space_id: int, user_id: int, tenant_id: int) -> None:
    login_user = UserPayload(
        user_id=user_id,
        user_name="profiler",
        tenant_id=tenant_id,
        is_global_super=True,
    )
    service = KnowledgeSpaceService(MagicMock(), login_user)

    print(f"\n=== profile get_space_tags(space_id={space_id}) ===\n")

    # Break down _get_effective_permission_ids (dominant cost).
    print("--- _get_effective_permission_ids breakdown ---")
    t0 = time.perf_counter()
    lineage = await service._build_resource_lineage("knowledge_space", space_id)
    print(f"{'  lineage':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  {lineage}")

    t0 = time.perf_counter()
    subjects = await service._get_current_user_subject_strings()
    print(f"{'  user_subject_strings':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  ({len(subjects)} subjects)")

    t0 = time.perf_counter()
    bindings = await service._get_relation_bindings()
    print(f"{'  relation_bindings':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  ({len(bindings)} bindings)")

    t0 = time.perf_counter()
    dept_paths = await service._get_binding_department_paths(bindings)
    print(f"{'  binding_department_paths':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms")

    t0 = time.perf_counter()
    models = await service._get_relation_models_map()
    print(f"{'  relation_models_map':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  ({len(models)} models)")

    from bisheng.permission.domain.services.fine_grained_permission_service import (
        FineGrainedPermissionService,
    )

    t0 = time.perf_counter()
    perms, _matched = await FineGrainedPermissionService.get_effective_permission_ids_async(
        login_user,
        "knowledge_space",
        space_id,
        models=models,
        bindings=bindings,
        binding_department_paths=dept_paths,
        user_subject_strings=subjects,
        lineage=lineage,
        nearest_binding_wins=False,
        return_match_metadata=True,
        use_permission_level_fallback=True,
    )
    print(
        f"{'  FGA get_effective_permission_ids_async':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  {sorted(perms)}"
    )

    t0 = time.perf_counter()
    membership = await service._membership_permission_ids(space_id)
    print(f"{'  membership_permission_ids':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  {sorted(membership)}")

    t0 = time.perf_counter()
    public_perms = await service._public_space_viewer_permission_ids(lineage)
    print(
        f"{'  public_space_viewer_permission_ids':48s} {(time.perf_counter() - t0) * 1000:8.1f} ms  {sorted(public_perms)}"
    )
    print()

    # Simulate HTTP: fresh service, both permission calls uncached.
    print("--- fresh HTTP-like request (duplicate permission) ---")
    http_user = UserPayload(
        user_id=user_id,
        user_name="profiler",
        tenant_id=tenant_id,
        is_global_super=False,
    )
    http_svc = KnowledgeSpaceService(MagicMock(), http_user)
    http_start = time.perf_counter()
    await http_svc._require_read_permission(space_id)
    read_ms = (time.perf_counter() - http_start) * 1000
    perm_start = time.perf_counter()
    await http_svc._require_permission_id("knowledge_space", space_id, "view_space")
    perm_ms = (time.perf_counter() - perm_start) * 1000
    print(f"{'  require_read (non-super, cold)':48s} {read_ms:8.1f} ms")
    print(f"{'  require_permission_id (same instance)':48s} {perm_ms:8.1f} ms")
    print()

    total_start = time.perf_counter()

    await _timed("1. _require_read_permission", service._require_read_permission(space_id))

    # Second permission call reuses per-request caches on the same service instance.
    perm2_start = time.perf_counter()
    await service._require_permission_id("knowledge_space", space_id, "view_space")
    perm2_ms = (time.perf_counter() - perm2_start) * 1000
    print(f"{'2. _require_permission_id(view_space) [cached]':48s} {perm2_ms:8.1f} ms")

    library_ids = await _timed(
        "3. alist_library_ids_by_knowledge",
        KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(space_id),
    )
    print(f"   bound libraries: {len(library_ids)} -> {library_ids}")

    merged = []
    seen_keys: set[str] = set()
    for index, library_id in enumerate(library_ids, start=1):
        tags = await _timed(
            f"4.{index} TagLibraryTagService.list_tags({library_id})",
            TagLibraryTagService.list_tags(int(library_id)),
        )
        repair_ms = 0.0
        # list_tags includes repair; also time raw query separately
        raw_start = time.perf_counter()
        raw_tags = await TagDao.get_tags_by_business(
            TagBusinessTypeEnum.TAG_LIBRARY,
            TagLibraryTagService._business_id(int(library_id)),
        )
        raw_ms = (time.perf_counter() - raw_start) * 1000
        print(f"   4.{index}a TagDao.get_tags_by_business only     {raw_ms:8.1f} ms  ({len(raw_tags)} tags)")

        for library_tag in tags:
            name = (library_tag.name or "").strip()
            if not name:
                continue
            resource_type = (library_tag.resource_type or "").strip().lower()
            dedupe_key = f"{resource_type}:{name.lower()}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            merged.append(library_tag)

    total_ms = (time.perf_counter() - total_start) * 1000
    print(f"\n{'TOTAL (instrumented path)':48s} {total_ms:8.1f} ms")
    print(f"merged tag count: {len(merged)}")

    # Full method for comparison (includes duplicate permission if not cached on same instance)
    service2 = KnowledgeSpaceService(MagicMock(), login_user)
    full_start = time.perf_counter()
    result = await service2.get_space_tags(space_id)
    full_ms = (time.perf_counter() - full_start) * 1000
    print(f"\n{'get_space_tags() end-to-end (fresh service)':48s} {full_ms:8.1f} ms")
    print(f"returned tag count: {len(result)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", type=int, default=137)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--tenant-id", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(profile(args.space_id, args.user_id, args.tenant_id))


if __name__ == "__main__":
    main()
