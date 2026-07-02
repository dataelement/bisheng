"""Knowledge-space tag library service backed by ``tag`` rows and M:N links."""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeSpaceTagLibraryInvalidError,
    KnowledgeSpaceTagLibraryNotExistError,
)
from bisheng.common.schemas.api import PageData
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_tag_library import (
    KnowledgeSpaceTagLibrary,
    KnowledgeSpaceTagLibraryDao,
)
from bisheng.knowledge.domain.models.knowledge_tag_library_link import (
    KnowledgeTagLibraryLinkDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_tag_library_schema import (
    KnowledgeSpaceTagLibraryDetail,
    KnowledgeSpaceTagLibraryListItem,
    KnowledgeSpaceTagLibraryTagItem,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import (
    TagLibraryTagService,
)
from bisheng.user.domain.models.user import UserDao

MAX_LIBRARY_TAGS = 200
MAX_LIBRARY_NAME_LENGTH = 20


class KnowledgeSpaceTagLibraryService:
    def __init__(self, login_user: UserPayload):
        self.login_user = login_user

    @staticmethod
    def normalize_tags(tags: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for tag in tags or []:
            if tag is None:
                continue
            value = str(tag).strip()
            if value:
                normalized.append(value)
        if len(normalized) > MAX_LIBRARY_TAGS:
            raise KnowledgeSpaceTagLibraryInvalidError(message=f"单个标签库最多只能包含 {MAX_LIBRARY_TAGS} 个标签")
        return normalized

    @classmethod
    def parse_text_tags(cls, content: str) -> list[str]:
        return cls.normalize_tags(content.splitlines())

    @classmethod
    def normalize_name(cls, name: str) -> str:
        normalized = (name or "").strip()
        if not normalized:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签库名称不能为空")
        if len(normalized) > MAX_LIBRARY_NAME_LENGTH:
            raise KnowledgeSpaceTagLibraryInvalidError(msg=f"标签库名称不能超过{MAX_LIBRARY_NAME_LENGTH}个字符")
        return normalized

    @staticmethod
    async def _ensure_public_name_available(name: str, *, exclude_library_id: int | None = None) -> None:
        existing = await KnowledgeSpaceTagLibraryDao.aget_public_by_name(
            name,
            exclude_library_id=exclude_library_id,
        )
        if existing:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签库名称已存在")

    @staticmethod
    async def _ensure_global_tag_names_available(
        *,
        tenant_id: int | None,
        tag_names: list[str],
        exclude_library_id: int | None = None,
    ) -> None:
        duplicates = await TagLibraryTagService.find_names_used_in_other_libraries(
            tenant_id=tenant_id,
            names=tag_names,
            exclude_library_id=exclude_library_id,
        )
        if not duplicates:
            return
        if len(duplicates) == 1:
            raise KnowledgeSpaceTagLibraryInvalidError(msg=f"标签「{duplicates[0]}」已存在于其他标签库")
        preview = "、".join(duplicates[:3])
        raise KnowledgeSpaceTagLibraryInvalidError(msg=f"标签「{preview}」等已存在于其他标签库")

    @staticmethod
    async def resolve_bound_library_ids(knowledge_id: int) -> list[int]:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        library_ids = await KnowledgeTagLibraryLinkDao.alist_library_ids_by_knowledge(knowledge_id)
        rows = await KnowledgeDao.aget_list_by_ids([knowledge_id])
        if rows and rows[0].auto_tag_library_id:
            legacy_id = int(rows[0].auto_tag_library_id)
            if legacy_id not in library_ids:
                library_ids.append(legacy_id)
        return library_ids

    @classmethod
    async def validate_library_bound_to_knowledge(cls, library_id: int, knowledge_id: int) -> None:
        bound_ids = await cls.resolve_bound_library_ids(knowledge_id)
        if int(library_id) not in bound_ids:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="该标签库未关联此知识空间")

    async def list_bound_libraries_for_knowledge(
        self,
        knowledge_id: int,
    ) -> list[KnowledgeSpaceTagLibraryListItem]:
        library_ids = await self.resolve_bound_library_ids(knowledge_id)
        items: list[KnowledgeSpaceTagLibraryListItem] = []
        seen: set[int] = set()
        for library_id in library_ids:
            normalized_id = int(library_id)
            if normalized_id in seen:
                continue
            library = await KnowledgeSpaceTagLibraryDao.aget(normalized_id)
            if not library:
                continue
            # Only tenant/public libraries are selectable in the UI dropdown.
            if library.owner_knowledge_id is not None:
                continue
            seen.add(normalized_id)
            items.append(await self.to_list_item(library))
        return items

    async def append_review_tag(
        self,
        *,
        library_id: int,
        knowledge_id: int,
        tag_name: str,
        review_resource_type: str,
    ) -> None:
        await self.validate_library_bound_to_knowledge(library_id, knowledge_id)
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()

        normalized_name = (tag_name or "").strip()
        if not normalized_name:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签名称不能为空")

        system, manual, ai = await TagLibraryTagService.list_tag_names(library_id)
        if not system and not manual and not ai:
            system = list(library.tags or [])
            ai = list(library.ai_tags or [])

        if review_resource_type == TagResourceTypeEnum.AI_AUTO_TAG.value:
            if normalized_name not in ai:
                await self._ensure_global_tag_names_available(
                    tenant_id=library.tenant_id,
                    tag_names=[normalized_name],
                    exclude_library_id=library_id,
                )
                ai.append(normalized_name)
        elif review_resource_type == TagResourceTypeEnum.MANUAL_TAG.value:
            if normalized_name not in manual:
                await self._ensure_global_tag_names_available(
                    tenant_id=library.tenant_id,
                    tag_names=[normalized_name],
                    exclude_library_id=library_id,
                )
                manual.append(normalized_name)
        elif normalized_name not in system:
            await self._ensure_global_tag_names_available(
                tenant_id=library.tenant_id,
                tag_names=[normalized_name],
                exclude_library_id=library_id,
            )
            system.append(normalized_name)

        non_ai = TagLibraryTagService.non_ai_tag_names(system, manual)
        if len(non_ai) + len(ai) > MAX_LIBRARY_TAGS:
            raise KnowledgeSpaceTagLibraryInvalidError(message=f"单个标签库最多只能包含 {MAX_LIBRARY_TAGS} 个标签")

        await TagLibraryTagService.replace_tags(
            library_id=library_id,
            tenant_id=library.tenant_id,
            user_id=self.login_user.user_id,
            system_tags=system,
            manual_tags=manual,
            ai_tags=ai,
        )
        await KnowledgeSpaceTagLibraryDao.aupdate(
            library_id,
            tags=non_ai,
            ai_tags=ai,
            tag_count=len(non_ai) + len(ai),
        )

    @staticmethod
    async def _resolve_library_tags(
        library: KnowledgeSpaceTagLibrary,
    ) -> tuple[list[str], int]:
        system, manual, ai = await TagLibraryTagService.list_tag_names(int(library.id))
        if not system and not manual and not ai:
            system = list(library.tags or [])
            ai = list(library.ai_tags or [])
        non_ai = TagLibraryTagService.non_ai_tag_names(system, manual)
        return non_ai + ai, len(non_ai) + len(ai)

    async def to_list_item(
        self,
        library: KnowledgeSpaceTagLibrary,
    ) -> KnowledgeSpaceTagLibraryListItem:
        system, manual, ai = await TagLibraryTagService.list_tag_names(int(library.id))
        if not system and not manual and not ai:
            system = list(library.tags or [])
            ai = list(library.ai_tags or [])
        non_ai = TagLibraryTagService.non_ai_tag_names(system, manual)
        tag_count = len(non_ai) + len(ai)
        bound_space_names: list[str] = []
        if library.owner_knowledge_id is None:
            bound_space_names = await KnowledgeTagLibraryLinkDao.alist_bound_space_names(int(library.id))
        bound_space_count = len(bound_space_names)
        used_knowledge_count = await TagLibraryTagService.count_total_usage(
            library_id=int(library.id),
            tenant_id=library.tenant_id,
            system_tags=system,
            manual_tags=manual,
            ai_tags=ai,
        )
        return KnowledgeSpaceTagLibraryListItem(
            id=library.id,
            name=library.name,
            description=library.description,
            tag_count=tag_count,
            bound_space_count=bound_space_count,
            bound_space_names=bound_space_names,
            used_knowledge_count=used_knowledge_count,
            is_builtin=library.is_builtin,
        )

    async def _ensure_tags_materialized(self, library: KnowledgeSpaceTagLibrary) -> None:
        """Sync legacy JSON tags into the tag table when migration or writes missed them."""
        tags = await TagLibraryTagService.list_tags(int(library.id))
        if tags:
            return
        system = list(library.tags or [])
        ai = list(library.ai_tags or [])
        if not system and not ai:
            return
        owner_id = library.user_id or self.login_user.user_id
        await TagLibraryTagService.replace_tags(
            library_id=int(library.id),
            tenant_id=library.tenant_id,
            user_id=owner_id,
            system_tags=system,
            ai_tags=ai,
        )

    async def _resolve_creator_name(self, library: KnowledgeSpaceTagLibrary) -> str | None:
        user_id = library.user_id or self.login_user.user_id
        if not user_id:
            return None
        users = await UserDao.aget_user_by_ids([int(user_id)])
        if not users:
            return None
        return users[0].user_name or None

    async def _build_tag_items_fallback(
        self,
        library: KnowledgeSpaceTagLibrary,
    ) -> list[KnowledgeSpaceTagLibraryTagItem]:
        manual = list(library.tags or [])
        ai = list(library.ai_tags or [])
        creator_name = await self._resolve_creator_name(library)
        items: list[KnowledgeSpaceTagLibraryTagItem] = []
        for name in manual:
            items.append(
                KnowledgeSpaceTagLibraryTagItem(
                    name=name,
                    resource_type=TagResourceTypeEnum.SYSTEM_TAG.value,
                    create_time=library.create_time,
                    creator_name=creator_name,
                )
            )
        for name in ai:
            items.append(
                KnowledgeSpaceTagLibraryTagItem(
                    name=name,
                    resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value,
                    create_time=library.create_time,
                    creator_name=creator_name,
                )
            )
        return items

    async def _build_tag_items_detail(
        self,
        library: KnowledgeSpaceTagLibrary,
    ) -> list[KnowledgeSpaceTagLibraryTagItem]:
        await self._ensure_tags_materialized(library)
        tags = await TagLibraryTagService.list_tags(int(library.id))
        if not tags:
            return await self._build_tag_items_fallback(library)

        usage_keys = [(tag.name or "", tag.resource_type) for tag in tags if tag.name]
        usage_map = await TagLibraryTagService.count_usage_batch(
            items=usage_keys,
            tenant_id=library.tenant_id,
        )

        user_ids = {int(tag.user_id) for tag in tags if tag.user_id}
        if library.user_id:
            user_ids.add(int(library.user_id))
        users = await UserDao.aget_user_by_ids(list(user_ids)) if user_ids else []
        user_name_by_id = {int(user.user_id): (user.user_name or "") for user in users or [] if user.user_id}

        items: list[KnowledgeSpaceTagLibraryTagItem] = []
        for tag in tags:
            name = (tag.name or "").strip()
            if not name:
                continue
            creator_user_id = tag.user_id or library.user_id or 0
            items.append(
                KnowledgeSpaceTagLibraryTagItem(
                    name=name,
                    resource_type=tag.resource_type,
                    resource_count=usage_map.get((name, tag.resource_type), 0),
                    create_time=tag.create_time or library.create_time,
                    creator_name=user_name_by_id.get(int(creator_user_id)) or None,
                )
            )
        return items

    async def to_detail(
        self,
        library: KnowledgeSpaceTagLibrary,
    ) -> KnowledgeSpaceTagLibraryDetail:
        tag_items = await self._build_tag_items_detail(library)
        system = [item.name for item in tag_items if item.resource_type == TagResourceTypeEnum.SYSTEM_TAG.value]
        manual = [item.name for item in tag_items if item.resource_type == TagResourceTypeEnum.MANUAL_TAG.value]
        return KnowledgeSpaceTagLibraryDetail(
            id=library.id,
            name=library.name,
            description=library.description,
            tag_count=len(tag_items),
            is_builtin=library.is_builtin,
            tags=[*system, *manual],
            tag_items=tag_items,
        )

    async def list_libraries_by_one(self, keyword: str | None = None) -> PageData[KnowledgeSpaceTagLibraryListItem]:
        rows = await KnowledgeSpaceTagLibraryDao.alist_by_one(keyword=keyword)
        data = [await self.to_list_item(row) for row in rows]
        return PageData(data=data, total=1)

    async def list_libraries(
        self, page: int = 1, page_size: int = 20, keyword: str | None = None
    ) -> PageData[KnowledgeSpaceTagLibraryListItem]:
        rows = await KnowledgeSpaceTagLibraryDao.alist(page=page, page_size=page_size, keyword=keyword)
        total = await KnowledgeSpaceTagLibraryDao.acount(keyword=keyword)
        data = [await self.to_list_item(row) for row in rows]
        return PageData(data=data, total=total)

    async def get_library(self, library_id: int) -> KnowledgeSpaceTagLibraryDetail:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()
        return await self.to_detail(library)

    async def create_library(
        self,
        name: str,
        description: str | None,
        tags: list[str],
        is_builtin: bool = False,
    ) -> KnowledgeSpaceTagLibraryDetail:
        normalized = self.normalize_tags(tags)
        normalized_name = self.normalize_name(name)
        await self._ensure_public_name_available(normalized_name)
        if normalized:
            await self._ensure_global_tag_names_available(
                tenant_id=self.login_user.tenant_id,
                tag_names=normalized,
            )
        library = await KnowledgeSpaceTagLibraryDao.ainsert(
            KnowledgeSpaceTagLibrary(
                tenant_id=self.login_user.tenant_id,
                name=normalized_name,
                description=description,
                tags=normalized,
                tag_count=len(normalized),
                is_builtin=is_builtin,
                user_id=self.login_user.user_id,
            )
        )
        await TagLibraryTagService.replace_tags(
            library_id=int(library.id),
            tenant_id=self.login_user.tenant_id,
            user_id=self.login_user.user_id,
            system_tags=normalized,
            ai_tags=library.ai_tags or [],
        )
        return await self.to_detail(library)

    async def update_library(
        self,
        library_id: int,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        manual_tags: list[str] | None = None,
        ai_tags: list[str] | None = None,
    ) -> KnowledgeSpaceTagLibraryDetail:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()

        updates = {}
        if name is not None:
            normalized_name = self.normalize_name(name)
            if library.owner_knowledge_id is None and normalized_name != library.name:
                await self._ensure_public_name_available(normalized_name, exclude_library_id=library_id)
            updates["name"] = normalized_name
        if description is not None:
            updates["description"] = description

        current_system, current_manual, current_ai = await TagLibraryTagService.list_tag_names(library_id)
        if not current_system and not current_manual:
            current_system = list(library.tags or [])
        if not current_ai:
            current_ai = list(library.ai_tags or [])

        next_system = self.normalize_tags(tags) if tags is not None else current_system
        next_manual = self.normalize_tags(manual_tags) if manual_tags is not None else current_manual
        next_ai = self.normalize_tags(ai_tags) if ai_tags is not None else current_ai
        non_ai = TagLibraryTagService.non_ai_tag_names(next_system, next_manual)
        if len(non_ai) + len(next_ai) > MAX_LIBRARY_TAGS:
            raise KnowledgeSpaceTagLibraryInvalidError(message=f"单个标签库最多只能包含 {MAX_LIBRARY_TAGS} 个标签")

        if tags is not None or manual_tags is not None or ai_tags is not None:
            await self._ensure_global_tag_names_available(
                tenant_id=library.tenant_id,
                tag_names=[*non_ai, *next_ai],
                exclude_library_id=library_id,
            )
            updates["tags"] = non_ai
            updates["ai_tags"] = next_ai
            updates["tag_count"] = len(non_ai) + len(next_ai)
            await TagLibraryTagService.replace_tags(
                library_id=library_id,
                tenant_id=library.tenant_id,
                user_id=self.login_user.user_id,
                system_tags=next_system,
                manual_tags=next_manual,
                ai_tags=next_ai,
            )

        if updates:
            library = await KnowledgeSpaceTagLibraryDao.aupdate(library_id, **updates)
        return await self.to_detail(library)

    async def get_library_usage(self, library_id: int) -> int:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()
        if library.owner_knowledge_id is not None:
            return 0
        return await KnowledgeTagLibraryLinkDao.acount_bound_knowledge_spaces(library_id)

    async def delete_library(self, library_id: int) -> None:
        library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
        if not library:
            raise KnowledgeSpaceTagLibraryNotExistError()
        if library.is_builtin:
            raise KnowledgeSpaceTagLibraryInvalidError(message="内置标签库不能删除")
        if library.owner_knowledge_id is not None:
            raise KnowledgeSpaceTagLibraryInvalidError(message="私有标签库不能从此入口删除")

        _, tag_count = await self._resolve_library_tags(library)
        if tag_count > 0:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签库中存在标签，无法删除")

        bound_count = await KnowledgeTagLibraryLinkDao.acount_bound_knowledge_spaces(library_id)
        if bound_count > 0:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签库已关联知识空间，无法删除")

        await TagLibraryTagService.delete_for_library(library_id)
        await KnowledgeSpaceTagLibraryDao.adelete(library_id)

    @staticmethod
    async def validate_bindable_library(library_id: int | None) -> None:
        if not library_id:
            raise KnowledgeSpaceTagLibraryInvalidError(message="开启自动标签时必须绑定非空标签库")
        await KnowledgeSpaceTagLibraryService.validate_bindable_libraries([library_id])

    @staticmethod
    async def validate_bindable_libraries(library_ids: list[int] | None) -> None:
        normalized = list(dict.fromkeys(int(library_id) for library_id in (library_ids or []) if library_id))
        if not normalized:
            raise KnowledgeSpaceTagLibraryInvalidError(message="开启自动标签时必须绑定非空标签库")
        for library_id in normalized:
            library = await KnowledgeSpaceTagLibraryDao.aget(library_id)
            if not library:
                raise KnowledgeSpaceTagLibraryNotExistError()
            if library.owner_knowledge_id is not None:
                raise KnowledgeSpaceTagLibraryInvalidError(message="无效的标签库")
            system, manual, ai = await TagLibraryTagService.list_tag_names(library_id)
            if not system and not manual and not ai and not (library.tags or library.ai_tags):
                raise KnowledgeSpaceTagLibraryInvalidError(message="开启自动标签时必须绑定非空标签库")
