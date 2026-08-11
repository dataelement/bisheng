from datetime import datetime

from sqlalchemy import Integer, and_, cast, delete, exists, func, or_, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.tag import (
    NewTagExistedError,
    OriginalTagNotFoundError,
    TagLibraryNotFoundError,
    TargetTagInUsedError,
)
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.review_tags import ApproveOrRejectEnum, ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl
from bisheng.workstation.domain.schemas.review_tags_schema import (
    ORG_UPLOADER_REVIEW_LEVELS,
    ReviewTagScope,
    ReviewTagSubmitterTarget,
)


class ReviewTagsRepositoryImpl:
    """ReviewTag Base Repository Class"""

    def __init__(self, session: AsyncSession, tags_repository: TagRepositoryImpl):
        self.session = session
        self.tags_repository = tags_repository

    @staticmethod
    def _parent_folder_id_from_level_path(file_level_path: str | None) -> int | None:
        """Return immediate parent folder id from ``file_level_path`` (empty = space root)."""
        folder_ids = [int(part) for part in (file_level_path or "").split("/") if part.isdigit()]
        return folder_ids[-1] if folder_ids else None

    @staticmethod
    def _coerce_review_scope(
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ) -> ReviewTagScope | None:
        """归一化审核范围；返回 None 表示全租户不过滤。"""
        if scope is not None:
            return None if scope.full_tenant else scope
        if space_ids is None:
            return None
        return ReviewTagScope(role_managed_space_ids=frozenset(int(i) for i in space_ids))

    def _role_space_match_clause(self, tenant_id: int, space_ids: set[int]):
        """库角色范围：business_id 或文件 knowledge_id 落在 role 空间。"""
        space_id_list = sorted(int(space_id) for space_id in space_ids)
        space_id_strs = [str(space_id) for space_id in space_id_list]
        business_match = ReviewTag.business_type.in_(
            [
                TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
                TagBusinessTypeEnum.KNOWLEDGE.value,
            ]
        ) & ReviewTag.business_id.in_(space_id_strs)
        link_match = exists(
            select(1)
            .select_from(ReviewTagLink)
            .join(
                KnowledgeFile,
                KnowledgeFile.id == cast(ReviewTagLink.resource_id, Integer),
            )
            .where(
                ReviewTagLink.tag_id == ReviewTag.id,
                ReviewTagLink.tenant_id == tenant_id,
                ReviewTagLink.is_deleted == False,  # noqa: E712
                KnowledgeFile.tenant_id == tenant_id,
                KnowledgeFile.knowledge_id.in_(space_id_list),
            )
        )
        return or_(business_match, link_match)

    def _org_uploader_match_clause(self, tenant_id: int, uploader_ids: set[int]):
        """组织管理员范围：团队/个人库，且上传人在组织内。"""
        uploader_id_list = sorted(int(uid) for uid in uploader_ids)
        org_levels = sorted(ORG_UPLOADER_REVIEW_LEVELS)
        # link.user_id>0 用 link，否则回退 tag.user_id
        effective_uploader = func.coalesce(
            func.nullif(ReviewTagLink.user_id, 0),
            ReviewTag.user_id,
        )
        org_link_match = exists(
            select(1)
            .select_from(ReviewTagLink)
            .join(
                KnowledgeFile,
                KnowledgeFile.id == cast(ReviewTagLink.resource_id, Integer),
            )
            .join(
                KnowledgeSpaceScope,
                KnowledgeSpaceScope.space_id == KnowledgeFile.knowledge_id,
            )
            .where(
                ReviewTagLink.tag_id == ReviewTag.id,
                ReviewTagLink.tenant_id == tenant_id,
                ReviewTagLink.is_deleted == False,  # noqa: E712
                KnowledgeFile.tenant_id == tenant_id,
                KnowledgeSpaceScope.level.in_(org_levels),
                effective_uploader.in_(uploader_id_list),
            )
        )
        org_business_match = and_(
            ReviewTag.business_type.in_(
                [
                    TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
                    TagBusinessTypeEnum.KNOWLEDGE.value,
                ]
            ),
            ReviewTag.user_id.in_(uploader_id_list),
            exists(
                select(1)
                .select_from(KnowledgeSpaceScope)
                .where(
                    KnowledgeSpaceScope.space_id == cast(ReviewTag.business_id, Integer),
                    KnowledgeSpaceScope.level.in_(org_levels),
                )
            ),
        )
        return or_(org_business_match, org_link_match)

    def _pending_review_scope_clause(self, tenant_id: int, scope: ReviewTagScope | None):
        """按 ReviewTagScope 限制待审标签；None 表示全租户。"""
        if scope is None or scope.full_tenant:
            return None
        parts = []
        if scope.role_managed_space_ids:
            parts.append(self._role_space_match_clause(tenant_id, set(scope.role_managed_space_ids)))
        if scope.org_uploader_ids:
            parts.append(self._org_uploader_match_clause(tenant_id, set(scope.org_uploader_ids)))
        if not parts:
            return ReviewTag.id == -1
        return or_(*parts)

    def _pending_space_scope_clause(self, tenant_id: int, space_ids: set[int] | None):
        """兼容旧 space_ids 过滤（仅 role 空间维度）。"""
        return self._pending_review_scope_clause(tenant_id, self._coerce_review_scope(space_ids=space_ids))

    async def delete_review_tag_link(self, tag_id: int, tenant_id: int):
        await self.session.exec(
            update(ReviewTagLink)
            .where(ReviewTagLink.tag_id == tag_id, ReviewTagLink.tenant_id == tenant_id)
            .values(is_deleted=True, update_time=datetime.now())
        )

    async def delete_review_tag_id(
        self, tag_id: int, business_type: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        await self.session.exec(
            update(ReviewTag)
            .where(
                ReviewTag.id == tag_id,
                ReviewTag.business_type == business_type,
                ReviewTag.resource_type == resource_type,
                ReviewTag.tenant_id == tenant_id,
            )
            .values(is_deleted=True, update_time=datetime.now())
        )
        await self.delete_review_tag_link(tag_id, tenant_id)

    async def approve_review_tag(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ):
        """Hard-delete pending rows for ``tag_name``.

        When scoped, only in-scope file links are removed. The ``ReviewTag`` row
        is deleted only when no active links remain — so out-of-scope same-name
        associations stay pending.
        """
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        tags = await self.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id, scope=scope, space_ids=space_ids
        )
        if not tags:
            return
        for tag in tags:
            if tag.id is None:
                continue
            if effective is None:
                await self.session.exec(
                    delete(ReviewTagLink).where(
                        ReviewTagLink.tag_id == tag.id,
                        ReviewTagLink.tenant_id == tenant_id,
                    )
                )
                await self.session.exec(
                    delete(ReviewTag).where(
                        ReviewTag.id == tag.id,
                        ReviewTag.tenant_id == tenant_id,
                    )
                )
                continue

            in_scope_link_ids = await self._in_scope_link_ids_for_tag(int(tag.id), tenant_id, effective, tag=tag)
            if in_scope_link_ids:
                await self.session.exec(
                    delete(ReviewTagLink).where(
                        ReviewTagLink.id.in_(in_scope_link_ids),
                        ReviewTagLink.tenant_id == tenant_id,
                    )
                )
            remaining = await self.get_review_tag_link_list_by_tag_id([int(tag.id)], tenant_id)
            if not remaining:
                await self.session.exec(
                    delete(ReviewTag).where(
                        ReviewTag.id == tag.id,
                        ReviewTag.tenant_id == tenant_id,
                    )
                )

    async def reject_review_tag(
        self,
        tag_name: str,
        reject_reason: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
        reviewer_id: int | None = None,
    ):
        """Soft-delete pending rows for ``tag_name``, optionally scoped.

        Scoped reject only soft-deletes in-scope links. The parent ``ReviewTag``
        is rejected only when no active links remain outside the scope.

        Unlike approve — which hard-deletes the row — reject keeps it around, so
        this is where the reviewer is recorded for rejected tags.
        """
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        tags = await self.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id, scope=scope, space_ids=space_ids
        )
        if not tags:
            return
        now = datetime.now()
        for tag in tags:
            if tag.id is None:
                continue
            if effective is None:
                await self.session.exec(
                    update(ReviewTag)
                    .where(
                        ReviewTag.id == tag.id,
                        ReviewTag.tenant_id == tenant_id,
                    )
                    .values(
                        is_deleted=True,
                        reject_reason=reject_reason,
                        update_time=now,
                        review_status=ApproveOrRejectEnum.REJECT.value,
                        review_time=now,
                        reviewer_id=reviewer_id,
                    )
                )
                await self.session.exec(
                    update(ReviewTagLink)
                    .where(
                        ReviewTagLink.tag_id == tag.id,
                        ReviewTagLink.tenant_id == tenant_id,
                    )
                    .values(is_deleted=True, update_time=now)
                )
                continue

            in_scope_link_ids = await self._in_scope_link_ids_for_tag(int(tag.id), tenant_id, effective, tag=tag)
            if in_scope_link_ids:
                await self.session.exec(
                    update(ReviewTagLink)
                    .where(
                        ReviewTagLink.id.in_(in_scope_link_ids),
                        ReviewTagLink.tenant_id == tenant_id,
                    )
                    .values(is_deleted=True, update_time=now)
                )
            remaining = await self.get_review_tag_link_list_by_tag_id([int(tag.id)], tenant_id)
            if not remaining:
                await self.session.exec(
                    update(ReviewTag)
                    .where(
                        ReviewTag.id == tag.id,
                        ReviewTag.tenant_id == tenant_id,
                    )
                    .values(
                        is_deleted=True,
                        reject_reason=reject_reason,
                        update_time=now,
                        review_status=ApproveOrRejectEnum.REJECT.value,
                        review_time=now,
                        reviewer_id=reviewer_id,
                    )
                )

    async def _pending_tag_ids_for_name(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        *,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ) -> list[int]:
        tags = await self.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id, scope=scope, space_ids=space_ids
        )
        return [int(tag.id) for tag in tags or [] if tag.id is not None]

    async def delete_review_tag_link_jilian(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        await self.session.exec(
            update(ReviewTagLink)
            .where(
                ReviewTagLink.tag_id.in_(
                    select(ReviewTag.id).where(
                        ReviewTag.name == tag_name,
                        ReviewTag.tenant_id == tenant_id,
                        ReviewTag.resource_type == resource_type,
                    )
                ),
                ReviewTagLink.tenant_id == tenant_id,
            )
            .values(is_deleted=True, update_time=datetime.now())
        )

    async def get_review_tag_by_tag_id(self, tag_id: int, tenant_id: int):
        statement = select(ReviewTag).where(
            ReviewTag.id == tag_id, ReviewTag.tenant_id == tenant_id, ReviewTag.is_deleted == False
        )
        review_tag = await self.session.exec(statement)
        return review_tag.first()

    async def query_review_tag_link_list_by_tag_id(self, tag_id: int, tenant_id: int):
        statement = select(ReviewTagLink).where(
            ReviewTagLink.tag_id == tag_id, ReviewTagLink.tenant_id == tenant_id, ReviewTagLink.is_deleted == False
        )
        review_tag_link = await self.session.exec(statement)
        return review_tag_link.scalars().all()

    async def approve_tag_to_move(
        self,
        review_tag: ReviewTag,
        review_tag_link: list[ReviewTagLink],
        *,
        skip_library_add: bool = False,
        reviewer_id: int | None = None,
        review_time: datetime | None = None,
    ):
        if not skip_library_add:
            if (
                review_tag.resource_type == TagResourceTypeEnum.SYSTEM_TAG
                or review_tag.resource_type == TagResourceTypeEnum.AI_AUTO_TAG
            ):
                await self.create_tag_library_by_tag(review_tag.name, review_tag.tenant_id, review_tag.resource_type)
        await self.tags_repository.approve_tag_to_move(
            review_tag,
            review_tag_link,
            reviewer_id=reviewer_id,
            review_time=review_time,
        )

    async def create_tag_library_by_tag(self, tag_name: str, tenant_id: int, resource_type: TagResourceTypeEnum):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if tag_name not in tags_list:
                await self.tags_repository.add_tag_library_by_tag(tag_name, tag_library, resource_type)
        else:
            raise TagLibraryNotFoundError.http_exception()

    async def update_tag_library_by_tag(
        self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            if tag_name in ai_tags and tag_name in tags:
                raise NewTagExistedError.http_exception()
            if original_tag_name not in tags and original_tag_name not in ai_tags:
                raise OriginalTagNotFoundError.http_exception()
            if resource_type == TagResourceTypeEnum.SYSTEM_TAG:
                await self.tags_repository.update_tag_library_by_tag(original_tag_name, tag_name, tag_library)
            elif resource_type == TagResourceTypeEnum.AI_AUTO_TAG:
                await self.tags_repository.update_tag_library_by_ai_tag(original_tag_name, tag_name, tag_library)
            await self.tags_repository.update_tag_by_name(original_tag_name, resource_type, tag_name, tenant_id)
        else:
            raise TagLibraryNotFoundError.http_exception()

    async def update_tag_library_by_manual_tag(
        self, original_tag_name: str, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int
    ):
        await self.tags_repository.update_tag_by_name(original_tag_name, resource_type, tag_name, tenant_id)

    async def delete_tag_library_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            if tag_name in (tag_library.tags or []) or tag_name in (tag_library.ai_tags or []):
                # 检查是否有其他标签使用该标签库
                tag_count = await self.tags_repository.get_tag_count_by_tag_name(tag_name, tenant_id)
                if tag_count > 0:
                    raise TargetTagInUsedError.http_exception()
                await self.tags_repository.remove_tag_library_by_tag(tag_name, resource_type, tag_library)
            else:
                raise OriginalTagNotFoundError.http_exception()
        else:
            raise TagLibraryNotFoundError.http_exception()

    async def get_list_tag_library_by_name(self, keyword: str, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            result = dict.fromkeys(tags, TagResourceTypeEnum.SYSTEM_TAG) | dict.fromkeys(
                ai_tags, TagResourceTypeEnum.AI_AUTO_TAG
            )

            all_tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if keyword:
                tags_list = []
                for tag in all_tags_list:
                    if keyword in tag:
                        tags_list.append(tag)
                return tags_list, result
            else:
                return all_tags_list, result
        else:
            return [], {}

    async def get_list_tag_library_by_name(self, keyword: str, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            result = dict.fromkeys(tags, TagResourceTypeEnum.SYSTEM_TAG)

            all_tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if keyword:
                tags_list = []
                for tag in all_tags_list:
                    if keyword in tag:
                        tags_list.append(tag)
                return tags_list, result
            else:
                return all_tags_list, result
        else:
            return [], {}

    async def get_tag_info_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_list = await self.tags_repository.get_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        tags_count = 0
        if tag_list and len(tag_list) > 0:
            ids = [tag.id for tag in tag_list]
            tags_count = await self.tags_repository.get_tag_link_count_by_tag_id(ids, tenant_id)
        return {"tag_name": tag_name, "resource_type": resource_type, "resource_count": tags_count}

    async def get_not_exist_tag_info_by_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_list = await self.tags_repository.get_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        if not tag_list or len(tag_list) == 0:
            return {"tag_name": tag_name, "resource_type": resource_type, "resource_count": 0}
        return None

    @staticmethod
    def _library_tag_name_subquery(tenant_id: int):
        return select(Tag.name).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.tenant_id == tenant_id,
        )

    @staticmethod
    def _active_review_tag_link_exists(tenant_id: int):
        return exists(
            select(1).where(
                ReviewTagLink.tag_id == ReviewTag.id,
                ReviewTagLink.tenant_id == tenant_id,
                ReviewTagLink.is_deleted == False,  # noqa: E712
            )
        )

    async def get_review_tag_group_list_by_page(
        self,
        page: int,
        page_size: int,
        tenant_id: int,
        keyword: str = "",
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ):
        where_clause = [
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.is_deleted == False,
            ReviewTag.review_status == 0,
            ReviewTag.name.not_in(self._library_tag_name_subquery(tenant_id)),
            self._active_review_tag_link_exists(tenant_id),
        ]
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        scope_clause = self._pending_review_scope_clause(tenant_id, effective)
        if scope_clause is not None:
            where_clause.append(scope_clause)
        if keyword:
            where_clause.append(ReviewTag.name.like(f"%{keyword}%"))

        # 分页数据
        stmt = (
            select(ReviewTag.name, ReviewTag.resource_type)
            .where(*where_clause)
            .group_by(ReviewTag.name, ReviewTag.resource_type)
            .order_by(ReviewTag.name, ReviewTag.resource_type)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.exec(stmt)
        rows = result.all()
        return [{"name": row.name, "resource_type": row.resource_type} for row in rows]

    async def get_review_tag_group_count_by_page(
        self,
        tenant_id: int,
        keyword: str = "",
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ):
        where_clause = [
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.is_deleted == False,
            ReviewTag.review_status == 0,
            ReviewTag.name.not_in(self._library_tag_name_subquery(tenant_id)),
            self._active_review_tag_link_exists(tenant_id),
        ]
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        scope_clause = self._pending_review_scope_clause(tenant_id, effective)
        if scope_clause is not None:
            where_clause.append(scope_clause)
        if keyword:
            where_clause.append(ReviewTag.name.like(f"%{keyword}%"))
        subq = select(1).select_from(ReviewTag).where(*where_clause).group_by(ReviewTag.name, ReviewTag.resource_type)
        stmt = select(func.count()).select_from(subq.subquery())
        result = await self.session.exec(stmt)
        count = result.first()
        if count is None:
            return 0
        if isinstance(count, int):
            return count
        return int(count[0])

    @staticmethod
    def _resolve_review_tag_library_id(tag_list: list) -> int | None:
        from bisheng.database.models.tag import TagBusinessTypeEnum

        for tag in tag_list or []:
            if tag.business_type != TagBusinessTypeEnum.TAG_LIBRARY.value:
                continue
            business_id = str(getattr(tag, "business_id", "") or "").strip()
            if not business_id.isdigit():
                continue
            return int(business_id)
        return None

    async def get_review_tag_resource_info_by_tag(
        self,
        group_tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ):
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        tag_list = await self.get_review_tag_list_by_tag_name(
            group_tag_name, resource_type, tenant_id, scope=scope, space_ids=space_ids
        )
        tag_by_id = {int(tag.id): tag for tag in (tag_list or []) if tag.id is not None}
        tag_library_id = self._resolve_review_tag_library_id(tag_list)
        knowledge_ids: list[int] = []
        for tag in tag_list or []:
            if tag.business_type != TagBusinessTypeEnum.KNOWLEDGE_SPACE.value:
                continue
            if tag.business_id is None or not str(tag.business_id).isdigit():
                continue
            kid = int(tag.business_id)
            if effective is not None:
                level = await self._level_for_space(kid)
                if not effective.allows_space_for_uploader(
                    space_id=kid, level=level, uploader_id=int(tag.user_id or 0)
                ):
                    continue
            if kid not in knowledge_ids:
                knowledge_ids.append(kid)
        if tag_list and len(tag_list) > 0:
            minio_client = await get_minio_storage()
            resource_list = []
            ids = [tag.id for tag in tag_list]
            review_tag_link_list = await self.get_review_tag_link_list_by_tag_id(ids, tenant_id)
            if review_tag_link_list and len(review_tag_link_list) > 0:
                tag_create_time_by_id = {tag.id: tag.create_time for tag in tag_list}
                for tag_link in review_tag_link_list:
                    parent_tag = tag_by_id.get(int(tag_link.tag_id)) if tag_link.tag_id is not None else None
                    if effective is not None and parent_tag is not None:
                        if not await self.link_in_review_scope(tag_link, parent_tag, tenant_id, effective):
                            continue
                    elif effective is not None and parent_tag is None:
                        continue
                    file_info = {}
                    knowledgefile = await self.tags_repository.get_knowledgefile_by_resource_id(
                        tag_link.resource_id, tenant_id
                    )
                    if knowledgefile:
                        file_space_id = (
                            int(knowledgefile.knowledge_id) if knowledgefile.knowledge_id is not None else None
                        )
                        if file_space_id is not None and file_space_id not in knowledge_ids:
                            knowledge_ids.append(file_space_id)
                        if knowledgefile.object_name:
                            file_url = await minio_client.get_share_link(
                                knowledgefile.object_name,
                                minio_client.bucket,
                                clear_host=False,
                            )
                        else:
                            file_url = ""
                        file_info["file_url"] = file_url
                        file_info["file_name"] = knowledgefile.file_name
                        file_info["file_size"] = knowledgefile.file_size
                        file_info["file_type"] = knowledgefile.file_type
                        file_info["file_source"] = knowledgefile.file_source
                        file_info["thumbnails"] = knowledgefile.thumbnails
                        file_info["abstract"] = knowledgefile.abstract
                        file_info["level"] = knowledgefile.level
                        file_info["file_level_path"] = knowledgefile.file_level_path
                        file_info["id"] = knowledgefile.id
                        file_info["file_id"] = knowledgefile.id
                        file_info["knowledge_id"] = knowledgefile.knowledge_id
                        # Portal deep-link opens the parent folder before previewing the file.
                        file_info["parent_id"] = self._parent_folder_id_from_level_path(knowledgefile.file_level_path)
                        submit_time = tag_link.create_time or tag_create_time_by_id.get(tag_link.tag_id)
                        file_info["submit_time"] = submit_time.strftime("%Y-%m-%d %H:%M:%S") if submit_time else ""
                    if file_info:
                        resource_list.append(file_info)
                return {
                    "tag_name": group_tag_name,
                    "resource_type": resource_type,
                    "tags_count": len(tag_list),
                    "resource_files": resource_list or [],
                    "knowledge_ids": knowledge_ids,
                    "tag_library_id": tag_library_id,
                }

        return {
            "tag_name": group_tag_name,
            "resource_type": resource_type,
            "tags_count": len(tag_list or []),
            "resource_files": [],
            "knowledge_ids": knowledge_ids,
            "tag_library_id": tag_library_id,
        }

    async def get_review_tag_link_list_by_tag_id(self, tag_ids: list[int], tenant_id: int):
        statement = select(ReviewTagLink).where(
            ReviewTagLink.tag_id.in_(tag_ids), ReviewTagLink.tenant_id == tenant_id, ReviewTagLink.is_deleted == False
        )
        review_tag_link_list = await self.session.exec(statement)
        return review_tag_link_list.scalars().all()

    async def get_review_tag_list_by_tag_name(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ):
        statement = select(ReviewTag).where(
            ReviewTag.name == tag_name,
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.is_deleted == False,
            ReviewTag.review_status == 0,
            ReviewTag.resource_type == resource_type,
        )
        review_tag_list = await self.session.exec(statement)
        tags = list(review_tag_list.scalars().all())
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        if effective is None:
            return tags
        scoped: list[ReviewTag] = []
        for tag in tags:
            # 同名待审可能跨库；任一 link/business 命中 scope 即保留。
            if await self.tag_intersects_review_scope(tag, tenant_id, effective):
                scoped.append(tag)
        return scoped

    async def tag_intersects_space_scope(self, tag: ReviewTag, tenant_id: int, space_ids: set[int]) -> bool:
        """兼容旧 API：仅按 role 空间集合判断。"""
        return await self.tag_intersects_review_scope(
            tag, tenant_id, ReviewTagScope(role_managed_space_ids=frozenset(int(i) for i in space_ids))
        )

    async def tag_intersects_review_scope(self, tag: ReviewTag, tenant_id: int, scope: ReviewTagScope) -> bool:
        """待审标签是否触及给定 ReviewTagScope。"""
        if scope.full_tenant:
            return True
        space_id = self._space_id_from_review_tag(tag)
        if space_id is not None:
            level = await self._level_for_space(int(space_id))
            if scope.allows_space_for_uploader(space_id=int(space_id), level=level, uploader_id=int(tag.user_id or 0)):
                return True
        if tag.id is None:
            return False
        link_ids = await self._in_scope_link_ids_for_tag(int(tag.id), tenant_id, scope, tag=tag)
        return bool(link_ids)

    async def _level_for_space(self, space_id: int | None) -> str | None:
        if space_id is None:
            return None
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScopeDao

        row = await KnowledgeSpaceScopeDao.aget_by_space_id(int(space_id))
        if row is None:
            return None
        return str(getattr(row, "level", "") or "") or None

    async def link_in_review_scope(
        self,
        link: ReviewTagLink,
        tag: ReviewTag,
        tenant_id: int,
        scope: ReviewTagScope,
    ) -> bool:
        """单条 link 是否在审核范围内。"""
        if scope.full_tenant:
            return True
        space_id, _, _, _ = await self._resolve_file_target_from_link(link, tenant_id)
        uploader_id = int(link.user_id or 0) or int(tag.user_id or 0)
        level = await self._level_for_space(space_id)
        return scope.allows_space_for_uploader(space_id=space_id, level=level, uploader_id=uploader_id)

    async def _in_scope_link_ids_for_tag(
        self,
        tag_id: int,
        tenant_id: int,
        scope: ReviewTagScope | set[int],
        tag: ReviewTag | None = None,
    ) -> list[int]:
        """返回落在审核范围内的 active link id。"""
        if isinstance(scope, set):
            scope = ReviewTagScope(role_managed_space_ids=frozenset(int(i) for i in scope))
        if tag is None:
            tag = await self.get_review_tag_by_tag_id(tag_id, tenant_id)
        if tag is None:
            return []
        links = await self.get_review_tag_link_list_by_tag_id([tag_id], tenant_id)
        in_scope: list[int] = []
        for link in links or []:
            if link.id is None:
                continue
            if await self.link_in_review_scope(link, tag, tenant_id, scope):
                in_scope.append(int(link.id))
        return in_scope

    async def resolve_review_tag_space_id(self, tag: ReviewTag, tenant_id: int) -> int | None:
        """Resolve a representative knowledge space id for a pending review tag row."""
        space_id = self._space_id_from_review_tag(tag)
        if space_id is not None:
            return space_id
        if tag.id is not None:
            return await self._resolve_space_id_from_tag_links(int(tag.id), tenant_id)
        return None

    @staticmethod
    def _parse_knowledge_space_id(business_id: str | None) -> int | None:
        normalized = (business_id or "").strip()
        if normalized.isdigit():
            return int(normalized)
        return None

    @classmethod
    def _space_id_from_review_tag(cls, tag) -> int | None:
        business_type = str(getattr(tag, "business_type", "") or "")
        business_id = getattr(tag, "business_id", None)
        if business_type in (
            TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
            TagBusinessTypeEnum.KNOWLEDGE.value,
        ):
            return cls._parse_knowledge_space_id(business_id)
        return None

    async def _resolve_space_id_from_tag_links(self, tag_id: int, tenant_id: int) -> int | None:
        links = await self.get_review_tag_link_list_by_tag_id([tag_id], tenant_id)
        for link in links or []:
            knowledgefile = await self.tags_repository.get_knowledgefile_by_resource_id(
                link.resource_id,
                tenant_id,
            )
            if knowledgefile and knowledgefile.knowledge_id:
                return int(knowledgefile.knowledge_id)
        return None

    async def _resolve_file_target_from_link(
        self,
        link,
        tenant_id: int,
    ) -> tuple[int | None, int | None, str | None, str | None]:
        knowledgefile = await self.tags_repository.get_knowledgefile_by_resource_id(
            link.resource_id,
            tenant_id,
        )
        if not knowledgefile or knowledgefile.id is None:
            return None, None, None, None
        space_id = int(knowledgefile.knowledge_id) if knowledgefile.knowledge_id else None
        file_id = int(knowledgefile.id)
        file_name = knowledgefile.file_name
        file_type = knowledgefile.file_type
        return space_id, file_id, file_name, file_type

    async def _resolve_primary_file_for_tag(
        self,
        tag_id: int,
        user_id: int,
        tenant_id: int,
    ) -> tuple[int | None, int | None, str | None, str | None]:
        links = await self.get_review_tag_link_list_by_tag_id([tag_id], tenant_id)
        preferred = next((link for link in links or [] if int(link.user_id or 0) == user_id), None)
        chosen = preferred or ((links or [None])[0])
        if chosen is None:
            return None, None, None, None
        return await self._resolve_file_target_from_link(chosen, tenant_id)

    async def list_submitter_notification_targets(
        self,
        tag_name: str,
        resource_type: TagResourceTypeEnum,
        tenant_id: int,
        *,
        exclude_user_id: int | None = None,
        scope: ReviewTagScope | None = None,
        space_ids: set[int] | None = None,
    ) -> list[ReviewTagSubmitterTarget]:
        """Return unique submitters with their related knowledge space and file."""
        effective = self._coerce_review_scope(scope=scope, space_ids=space_ids)
        tags = await self.get_review_tag_list_by_tag_name(
            tag_name, resource_type, tenant_id, scope=scope, space_ids=space_ids
        )
        user_targets: dict[int, ReviewTagSubmitterTarget] = {}

        for tag in tags:
            user_id = int(tag.user_id or 0)
            if user_id <= 0:
                continue
            space_id = self._space_id_from_review_tag(tag)
            file_id: int | None = None
            file_name: str | None = None
            file_type: str | None = None
            if tag.id is not None:
                resolved_space, resolved_file, resolved_name, resolved_type = await self._resolve_primary_file_for_tag(
                    int(tag.id),
                    user_id,
                    tenant_id,
                )
                if space_id is None:
                    space_id = resolved_space
                file_id = resolved_file
                file_name = resolved_name
                file_type = resolved_type
            if effective is not None:
                level = await self._level_for_space(space_id)
                if not effective.allows_space_for_uploader(space_id=space_id, level=level, uploader_id=user_id):
                    continue
            existing = user_targets.get(user_id)
            if existing is None or (existing.knowledge_space_id is None and space_id is not None):
                user_targets[user_id] = ReviewTagSubmitterTarget(
                    user_id=user_id,
                    knowledge_space_id=space_id,
                    file_id=file_id,
                    file_name=file_name,
                    file_type=file_type,
                )

        tag_ids = [int(tag.id) for tag in tags if tag.id is not None]
        if tag_ids:
            tag_by_id = {int(tag.id): tag for tag in tags if tag.id is not None}
            links = await self.get_review_tag_link_list_by_tag_id(tag_ids, tenant_id)
            for link in links:
                user_id = int(link.user_id or 0)
                if user_id <= 0 or user_id in user_targets:
                    continue
                parent_tag = tag_by_id.get(int(link.tag_id)) if link.tag_id is not None else None
                if effective is not None and parent_tag is not None:
                    if not await self.link_in_review_scope(link, parent_tag, tenant_id, effective):
                        continue
                elif effective is not None and parent_tag is None:
                    continue
                space_id, file_id, file_name, file_type = await self._resolve_file_target_from_link(link, tenant_id)
                if space_id is None:
                    space_id = self._space_id_from_review_tag(parent_tag) if parent_tag else None
                    if space_id is None and parent_tag and parent_tag.id is not None:
                        space_id = await self._resolve_space_id_from_tag_links(int(parent_tag.id), tenant_id)
                user_targets[user_id] = ReviewTagSubmitterTarget(
                    user_id=user_id,
                    knowledge_space_id=space_id,
                    file_id=file_id,
                    file_name=file_name,
                    file_type=file_type,
                )

        if exclude_user_id is not None:
            user_targets.pop(int(exclude_user_id), None)
        return list(user_targets.values())

    async def list_all_tags_by_page(self, page: int, page_size: int, keyword: str, tenant_id: int):
        return await self.tags_repository.list_all_tags_by_page(page, page_size, keyword, tenant_id)

    async def query_all_tag_library_count_by_page(self, keyword: str, tenant_id: int):
        return await self.tags_repository.get_all_tag_library_count_by_page(keyword, tenant_id)

    async def delete_tag_library_by_manual_tag(self, tag_name: str, resource_type: TagResourceTypeEnum, tenant_id: int):
        tag_list = await self.tags_repository.get_tag_list_by_tag_name(tag_name, resource_type, tenant_id)
        if tag_list and len(tag_list) > 0:
            tag_ids = [tag.id for tag in tag_list]
            tag_link_count = await self.tags_repository.get_tag_link_count_by_tag_id(tag_ids, tenant_id)
            if tag_link_count > 0:
                raise TargetTagInUsedError.http_exception()
            else:
                await self.tags_repository.delete_tag_library_by_name(tag_name, resource_type, tenant_id)

    async def query_existed_tag_by_review_tag(self, review_tag: ReviewTag):
        return await self.tags_repository.query_existed_tag_by_review_tag(review_tag)

    async def get_not_exist_system_tag_by_name(self, keyword: str, tenant_id: int):
        tag_library = await self.tags_repository.get_tag_library(tenant_id)
        if tag_library:
            tags = tag_library.tags or []
            ai_tags = tag_library.ai_tags or []
            result = dict.fromkeys(tags, TagResourceTypeEnum.SYSTEM_TAG)

            all_tags_list = await self.tags_repository.get_all_library_list(tag_library)
            if keyword:
                tags_list = []
                for tag in all_tags_list:
                    if keyword in tag:
                        tags_list.append(tag)
                return tags_list, result
            else:
                return all_tags_list, result
        else:
            return [], {}
