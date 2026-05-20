from typing import List, Optional

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeSpaceTagLibraryInvalidError,
    KnowledgeSpaceTagLibraryNotExistError,
)
from bisheng.common.schemas.api import PageData
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
    KnowledgeSpaceTagLibrary,
    KnowledgeSpaceTagLibraryDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_tag_library_schema import (
    KnowledgeSpaceTagLibraryDetail,
    KnowledgeSpaceTagLibraryListItem,
)


MAX_LIBRARY_TAGS = 200


class KnowledgeSpaceTagLibraryService:
    def __init__(self, login_user: UserPayload):
        self.login_user = login_user

    @staticmethod
    def normalize_tags(tags: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        for tag in tags or []:
            if tag is None:
                continue
            value = str(tag).strip()
            if value:
                normalized.append(value)
        if len(normalized) > MAX_LIBRARY_TAGS:
            raise KnowledgeSpaceTagLibraryInvalidError(
                message=f"单个标签库最多只能包含 {MAX_LIBRARY_TAGS} 个标签"
            )
        return normalized

    @classmethod
    def parse_text_tags(cls, content: str) -> List[str]:
        return cls.normalize_tags(content.splitlines())

    @staticmethod
    def normalize_name(name: str) -> str:
        normalized = (name or "").strip()
        if not normalized:
            raise KnowledgeSpaceTagLibraryInvalidError(message="标签库名称不能为空")
        return normalized

    @staticmethod
    def to_list_item(
        library: KnowledgeSpaceTagLibrary,
    ) -> KnowledgeSpaceTagLibraryListItem:
        return KnowledgeSpaceTagLibraryListItem(
            id=library.id,
            name=library.name,
            description=library.description,
            tag_count=library.tag_count,
            is_builtin=library.is_builtin,
        )

    @staticmethod
    def to_detail(library: KnowledgeSpaceTagLibrary) -> KnowledgeSpaceTagLibraryDetail:
        return KnowledgeSpaceTagLibraryDetail(
            id=library.id,
            name=library.name,
            description=library.description,
            tag_count=library.tag_count,
            is_builtin=library.is_builtin,
            tags=library.tags or [],
        )

    async def list_libraries(
        self, page: int = 1, page_size: int = 20, keyword: Optional[str] = None
    ) -> PageData[KnowledgeSpaceTagLibraryListItem]:
        rows = await KnowledgeSpaceTagLibraryDao.alist(
            page=page, page_size=page_size, keyword=keyword
        )
        total = await KnowledgeSpaceTagLibraryDao.acount(keyword=keyword)
        return PageData(data=[self.to_list_item(row) for row in rows], total=total)

    async def get_library(self, library_id: int) -> KnowledgeSpaceTagLibraryDetail:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()
        return self.to_detail(library)

    async def create_library(
        self, name: str, description: Optional[str], tags: List[str]
    ) -> KnowledgeSpaceTagLibraryDetail:
        normalized = self.normalize_tags(tags)
        library = await KnowledgeSpaceTagLibraryDao.ainsert(
            KnowledgeSpaceTagLibrary(
                tenant_id=self.login_user.tenant_id,
                name=self.normalize_name(name),
                description=description,
                tags=normalized,
                tag_count=len(normalized),
                user_id=self.login_user.user_id,
            )
        )
        return self.to_detail(library)

    async def import_text_library(
        self, name: str, description: Optional[str], content: str
    ) -> KnowledgeSpaceTagLibraryDetail:
        return await self.create_library(
            name=name, description=description, tags=self.parse_text_tags(content)
        )

    async def update_library(
        self,
        library_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> KnowledgeSpaceTagLibraryDetail:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()

        updates = {}
        if name is not None:
            updates["name"] = self.normalize_name(name)
        if description is not None:
            updates["description"] = description
        if tags is not None:
            normalized = self.normalize_tags(tags)
            updates["tags"] = normalized
            updates["tag_count"] = len(normalized)

        if updates:
            library = await KnowledgeSpaceTagLibraryDao.aupdate(library_id, **updates)
        return self.to_detail(library)

    async def delete_library(self, library_id: int) -> None:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()
        if library.is_builtin:
            raise KnowledgeSpaceTagLibraryInvalidError(message="内置标签库不能删除")
        await KnowledgeSpaceTagLibraryDao.aclear_space_bindings(library_id)
        await KnowledgeSpaceTagLibraryDao.adelete(library_id)

    @staticmethod
    async def validate_bindable_library(library_id: Optional[int]) -> None:
        if not library_id:
            raise KnowledgeSpaceTagLibraryInvalidError(
                message="开启自动标签时必须绑定非空标签库"
            )
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()
        if library.tag_count <= 0 or not library.tags:
            raise KnowledgeSpaceTagLibraryInvalidError(
                message="开启自动标签时必须绑定非空标签库"
            )
