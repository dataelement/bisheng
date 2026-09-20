"""门户问答收藏引用解析; 始终保留源入口作为授权身份。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalPlan
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
    from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
    from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
        KnowledgeDocumentDurableReferenceResolver,
    )

from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
    KnowledgeDocumentEntryResolutionError,
)


@dataclass(frozen=True)
class FavoriteBinding:
    favorite_space_id: int
    favorite_file_id: int
    source_space_id: int
    source_file_id: int


class PortalQaFavorites:
    def __init__(
        self,
        *,
        user: Any,
        files: KnowledgeFileRepository,
        spaces: KnowledgeRepository,
        durable: KnowledgeDocumentDurableReferenceResolver,
    ) -> None:
        self.user = user
        self.files = files
        self.spaces = spaces
        self.durable = durable
        self._space_cache = {}

    async def preload_spaces(self, ids: list[int]) -> None:
        missing = sorted(set(ids) - self._space_cache.keys())
        for start in range(0, len(missing), 500):
            batch = missing[start : start + 500]
            self._space_cache.update(dict.fromkeys(batch))
            for space in await self.spaces.find_by_ids(batch):
                self._space_cache[int(space.id)] = space

    async def space(self, sid: int) -> Knowledge | None:
        if sid not in self._space_cache:
            self._space_cache[sid] = await self.spaces.find_by_id(sid)
        return self._space_cache[sid]

    def valid_space(self, space: Knowledge | None) -> bool:
        return bool(
            space
            and int(space.tenant_id or 0) == int(self.user.tenant_id)
            and int(space.type) == KnowledgeTypeEnum.SPACE.value
            and int(space.state) != KnowledgeState.DELETING.value
        )

    async def owns(self, sid: int) -> bool:
        space = await self.space(sid)
        return bool(self.valid_space(space) and space.is_favorite and int(space.user_id or 0) == int(self.user.user_id))

    def valid_file(self, file: KnowledgeFile | None, sid: int) -> bool:
        return bool(
            file
            and int(file.tenant_id or 0) == int(self.user.tenant_id)
            and int(file.knowledge_id) == sid
            and file.deleted_at is None
            and int(file.file_type) == FileType.FILE.value
            and int(file.status) == KnowledgeFileStatus.SUCCESS.value
        )

    async def resolve(self, space_id: int, file_id: int) -> FavoriteBinding | None:
        if not await self.owns(space_id):
            return None
        ref = await self.files.find_by_id(file_id)
        if (
            not self.valid_file(ref, space_id)
            or ref.file_source != "favorite_reference"
            or int(ref.user_id or 0) != int(self.user.user_id)
        ):
            return None
        metadata = ref.user_metadata
        target = metadata.get("favorite_reference") if isinstance(metadata, dict) else None
        if not isinstance(target, dict):
            return None
        try:
            sid, fid = int(target.get("source_space_id") or 0), int(target.get("source_file_id") or 0)
        except (ValueError, TypeError):
            return None
        if sid <= 0 or fid <= 0 or not self.valid_space(await self.space(sid)):
            return None
        source = await self.files.find_by_id(fid)
        # 收藏不串接收藏; 失效源文件不得借助文档映射重新获得访问资格。
        if not self.valid_file(source, sid) or source.file_source == "favorite_reference":
            return None
        try:
            resolved = await self.durable.resolve(
                tenant_id=int(self.user.tenant_id),
                requested_space_id=sid,
                durable_file_id=fid,
                require_view_permission=False,
            )
        except KnowledgeDocumentEntryResolutionError:
            return None
        current = await self.files.find_by_id(int(resolved.entry_file_id))
        if not self.valid_file(current, sid) or current.file_source == "favorite_reference":
            return None
        return FavoriteBinding(space_id, file_id, sid, int(current.id))

    async def expand_spaces(self, ids: list[int]) -> tuple[tuple[int, ...], tuple[FavoriteBinding, ...]]:
        whole, bindings = [], []
        for sid in sorted(set(ids)):
            space = await self.space(sid)
            if not space or not getattr(space, "is_favorite", False):
                whole.append(sid)
                continue
            if not await self.owns(sid):
                continue
            after = 0
            while True:
                rows = await self.files.list_qa_favorite_page(space_id=sid, after_id=after, limit=200)
                if not rows:
                    break
                for row in rows:
                    binding = await self.resolve(sid, int(row.id))
                    if binding is not None:
                        bindings.append(binding)
                next_id = int(rows[-1].id)
                if next_id <= after:
                    raise RuntimeError("favorite pagination made no progress")
                after = next_id
        return tuple(whole), tuple(bindings)


def create_qa_favorites(session: AsyncSession, user: Any) -> PortalQaFavorites:
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
    from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
        KnowledgeDocumentDurableReferenceResolver,
        KnowledgeDocumentEntryResolver,
    )

    files = KnowledgeFileRepositoryImpl(session)
    versions = KnowledgeDocumentVersionRepositoryImpl(session)

    async def permissions(fid: int, sid: int) -> set[str]:
        # 身份解析与授权分开; 目录和检索各自沿用源入口的既有权限检查。
        return set()

    entry = KnowledgeDocumentEntryResolver(
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=versions,
        file_repository=files,
        permission_loader=permissions,
    )
    return PortalQaFavorites(
        user=user,
        files=files,
        spaces=KnowledgeRepositoryImpl(session),
        durable=KnowledgeDocumentDurableReferenceResolver(
            entry_resolver=entry, version_repository=versions, file_repository=files
        ),
    )


class FavoriteScopeAuthorizer:
    """候选和最终检查均重新读取收藏; 直接选择或整库权限仍按原路径处理。"""

    def __init__(self, inner: Any, favorites: PortalQaFavorites, plan: QaRetrievalPlan) -> None:
        self.inner, self.favorites, self.plan = inner, favorites, plan
        self.context = inner.context
        self.allowed = {(sid, fid) for sid, ids in plan.direct_file_ids_by_space.items() for fid in ids}
        self.checked = set()
        self.bindings = {}
        for binding in plan.favorite_bindings:
            self.bindings.setdefault((binding.source_space_id, binding.source_file_id), []).append(binding)

    async def __call__(self, entries: list[KnowledgeFile]) -> dict[int, bool]:
        # 只复核本批候选依赖的收藏, 避免最终少量命中重复扫描整个收藏库。
        for entry in entries:
            key = (int(entry.knowledge_id), int(entry.id))
            if key in self.checked or key in self.allowed or key[0] in self.plan.whole_space_ids:
                continue
            for binding in self.bindings.get(key, []):
                current = await self.favorites.resolve(binding.favorite_space_id, binding.favorite_file_id)
                if current == binding:
                    self.allowed.add(key)
                    break
            self.checked.add(key)
        valid = [
            entry
            for entry in entries
            if int(entry.knowledge_id) in self.plan.whole_space_ids
            or (int(entry.knowledge_id), int(entry.id)) in self.allowed
        ]
        permissions = await self.inner(valid) if valid else {}
        return {int(entry.id): bool(permissions.get(int(entry.id), False)) for entry in entries}
