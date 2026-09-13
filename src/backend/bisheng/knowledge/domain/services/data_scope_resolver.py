"""Knowledge-domain ownership facts for the F066 data-scope narrowing.

Implements ``DataScopeOwnershipResolver`` (permission.application.data_scope)
with the exact "created by me" reading the UI uses (design decision 3):

* document / QA libraries — ``knowledge.user_id = holder`` (types 0/1);
* knowledge spaces — an ACTIVE CREATOR membership row **and** no
  ``department_knowledge_space`` binding (a space bound to a department is an
  organisational asset and leaves the personal set, mirroring the sidebar);
* files / folders — resolved in one batch to their parent library or space
  and judged by the parent.  Never by the file's own creator: content added
  by others inside a holder-created container stays retrievable (accepted
  residual risk, D21).

Results are memoised per request task via ``ContextVar`` so repeated checks
(per-file prefilters, page batches) hit the database once per container.
"""

from __future__ import annotations

from contextvars import ContextVar

from bisheng.common.models.space_channel_member import SpaceChannelMemberDao
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.permission.application.data_scope import register_data_scope_resolver

_GOVERNED = frozenset({"knowledge_library", "knowledge_space", "knowledge_file", "knowledge_folder"})
_FILE_TYPES = frozenset({"knowledge_file", "knowledge_folder"})

# Per-request memo: {(holder, "libraries"): frozenset[int], (holder, "spaces"):
# frozenset[int], (holder, "parent", parent_id): bool}.  A fresh dict is set
# lazily inside the current task context, so requests never share entries.
_memo: ContextVar[dict | None] = ContextVar("knowledge_data_scope_memo", default=None)


def _cache() -> dict:
    cache = _memo.get()
    if cache is None:
        cache = {}
        _memo.set(cache)
    return cache


class KnowledgeDataScopeResolver:
    def governed_resource_types(self) -> frozenset[str]:
        return _GOVERNED

    async def filter_owned(
        self,
        *,
        holder_user_id: int,
        tenant_id: int,
        resource_type: str,
        resource_ids: tuple[str, ...],
    ) -> frozenset[str]:
        if not resource_ids:
            return frozenset()
        if resource_type == "knowledge_library":
            owned = await self._owned_libraries(holder_user_id)
            return frozenset(rid for rid in resource_ids if _as_int(rid) in owned)
        if resource_type == "knowledge_space":
            owned = await self._owned_spaces(holder_user_id)
            return frozenset(rid for rid in resource_ids if _as_int(rid) in owned)
        if resource_type in _FILE_TYPES:
            return await self._filter_owned_files(holder_user_id, resource_ids)
        return frozenset()

    async def owned_ids(
        self,
        *,
        holder_user_id: int,
        tenant_id: int,
        resource_type: str,
    ) -> frozenset[str]:
        if resource_type == "knowledge_library":
            return frozenset(str(item) for item in await self._owned_libraries(holder_user_id))
        if resource_type == "knowledge_space":
            return frozenset(str(item) for item in await self._owned_spaces(holder_user_id))
        # File-level enumeration is never used for lists; fail closed.
        return frozenset()

    async def _owned_libraries(self, holder_user_id: int) -> frozenset[int]:
        cache = _cache()
        key = (holder_user_id, "libraries")
        if key not in cache:
            normal = await KnowledgeDao.aget_knowledge_ids_created_by(holder_user_id, KnowledgeTypeEnum.NORMAL)
            qa = await KnowledgeDao.aget_knowledge_ids_created_by(holder_user_id, KnowledgeTypeEnum.QA)
            cache[key] = frozenset(normal) | frozenset(qa)
        return cache[key]

    async def _owned_spaces(self, holder_user_id: int) -> frozenset[int]:
        cache = _cache()
        key = (holder_user_id, "spaces")
        if key not in cache:
            members = await SpaceChannelMemberDao.async_get_user_created_members(holder_user_id)
            created = {int(member.business_id) for member in members}
            if created:
                bound = await DepartmentKnowledgeSpaceDao.aget_by_space_ids(list(created))
                created -= {int(binding.space_id) for binding in bound}
            cache[key] = frozenset(created)
        return cache[key]

    async def _filter_owned_files(
        self,
        holder_user_id: int,
        resource_ids: tuple[str, ...],
    ) -> frozenset[str]:
        cache = _cache()
        wanted = {rid: _as_int(rid) for rid in resource_ids}
        missing = [fid for fid in wanted.values() if fid is not None and (holder_user_id, "file", fid) not in cache]
        if missing:
            rows = await KnowledgeFileDao.aget_file_by_ids(missing)
            parent_by_file = {int(row.id): int(row.knowledge_id) for row in rows}
            parent_ids = sorted(set(parent_by_file.values()))
            owned_parents = await self._owned_parents(holder_user_id, parent_ids)
            for fid in missing:
                parent = parent_by_file.get(fid)
                cache[(holder_user_id, "file", fid)] = parent is not None and parent in owned_parents
        return frozenset(
            rid for rid, fid in wanted.items() if fid is not None and cache.get((holder_user_id, "file", fid), False)
        )

    async def _owned_parents(self, holder_user_id: int, parent_ids: list[int]) -> frozenset[int]:
        if not parent_ids:
            return frozenset()
        rows = await KnowledgeDao.aget_list_by_ids(parent_ids)
        owned_libraries = await self._owned_libraries(holder_user_id)
        owned_spaces = await self._owned_spaces(holder_user_id)
        owned: set[int] = set()
        for row in rows:
            if row.type == KnowledgeTypeEnum.SPACE.value:
                if int(row.id) in owned_spaces:
                    owned.add(int(row.id))
            elif int(row.id) in owned_libraries:
                owned.add(int(row.id))
        return frozenset(owned)


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Assembly-time registration: this module is imported by the knowledge domain
# services package, which is loaded before any knowledge permission check can
# run.  Until then a narrowed actor is denied everything (fail closed).
register_data_scope_resolver(KnowledgeDataScopeResolver())
