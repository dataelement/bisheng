"""Business logic for the F079 tag management console."""

from datetime import datetime

from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeSpaceTagLibraryInvalidError,
    KnowledgeSpaceTagLibraryNotExistError,
)
from bisheng.common.errcode.tag import ReviewTagNotFoundError
from bisheng.common.errcode.workstation import (
    TagConsoleActionNotApplicableError,
    TagConsoleBatchTooLargeError,
    TagConsolePageParamsError,
    TagConsoleRejectReasonRequiredError,
)
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
from bisheng.user.domain.models.user import UserDao
from bisheng.workstation.domain.repositories.tag_console_repository import (
    REJECTED_STATUS,
    TagConsoleRepositoryImpl,
)
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest
from bisheng.workstation.domain.schemas.tag_console_schema import (
    MAX_BATCH_SIZE,
    MAX_PAGE_SIZE,
    TagConsoleBatchFailure,
    TagConsoleBatchResult,
    TagConsoleCreateReq,
    TagConsoleFilter,
    TagConsoleItem,
    TagConsoleReviewItem,
    TagConsoleReviewRef,
    TagConsoleReviewSearchReq,
    TagConsoleReviewSearchResp,
    TagConsoleReviewStatus,
    TagConsoleSearchReq,
    TagConsoleSearchResp,
    TagConsoleSourceFile,
)
from bisheng.workstation.domain.services.workstation_tags_service import WorkStationTagsService


class TagConsoleService:
    """Reads for the console's library mode.

    Permission reuses ``WorkStationTagsService.resolve_reviewable_space_ids()``:
    it raises for anyone who may not review tags at all, which is exactly the gate
    this page needs. Its *return value* is only used by review mode — library mode
    is deliberately tenant-wide (AD-12).
    """

    def __init__(
        self,
        login_user: UserPayload,
        repository: TagConsoleRepositoryImpl,
        tags_service: WorkStationTagsService,
    ):
        self.login_user = login_user
        self.repository = repository
        self.tags_service = tags_service

    @staticmethod
    def _validate_page(req: TagConsoleFilter) -> None:
        if req.page < 1 or req.page_size < 1 or req.page_size > MAX_PAGE_SIZE:
            raise TagConsolePageParamsError()

    async def _ensure_can_manage_tags(self) -> None:
        """Raises when the caller may not manage tags; scope value unused here."""
        await self.tags_service.resolve_reviewable_space_ids()

    async def search(self, req: TagConsoleSearchReq, tenant_id: int) -> TagConsoleSearchResp:
        self._validate_page(req)
        await self._ensure_can_manage_tags()

        rows, total = await self.repository.search_library_tags(req, tenant_id=tenant_id)
        if not rows:
            return TagConsoleSearchResp(data=[], total=total)

        data = await self._decorate(rows, tenant_id=tenant_id)
        return TagConsoleSearchResp(data=data, total=total)

    async def _decorate(self, rows: list[Tag], tenant_id: int) -> list[TagConsoleItem]:
        """Fill in library names, user names, source files and usage counts.

        Every lookup is one batched query for the whole page — a per-row lookup
        here is what turns a 20-row page into 80 round trips.
        """
        tag_ids = [int(row.id) for row in rows if row.id is not None]

        marked_counts = await self.repository.count_marked_knowledge(tag_ids, tenant_id=tenant_id)
        files_by_tag = await self.repository.list_source_files(tag_ids, tenant_id=tenant_id)

        library_ids = {int(row.business_id) for row in rows if str(row.business_id or "").isdigit()}
        library_names = await self.repository.list_library_names(sorted(library_ids), tenant_id=tenant_id)

        file_ids = sorted({file_id for ids in files_by_tag.values() for file_id in ids})
        file_briefs = await self.repository.list_file_briefs(file_ids, tenant_id=tenant_id)

        user_ids = {int(row.user_id) for row in rows if row.user_id}
        user_ids |= {int(row.reviewer_id) for row in rows if row.reviewer_id}
        user_names = await self._list_user_names(sorted(user_ids))

        items: list[TagConsoleItem] = []
        for row in rows:
            library_id = int(row.business_id) if str(row.business_id or "").isdigit() else None
            source_files = [
                TagConsoleSourceFile(**file_briefs[file_id])
                for file_id in files_by_tag.get(int(row.id), [])
                if file_id in file_briefs
            ]
            items.append(
                TagConsoleItem(
                    id=int(row.id),
                    name=row.name or "",
                    resource_type=row.resource_type,
                    library_id=library_id,
                    library_name=library_names.get(library_id) if library_id else None,
                    marked_knowledge_count=marked_counts.get(int(row.id), 0),
                    submitter_id=row.user_id or None,
                    submitter_name=user_names.get(row.user_id) if row.user_id else None,
                    reviewer_id=row.reviewer_id,
                    reviewer_name=user_names.get(row.reviewer_id) if row.reviewer_id else None,
                    source_files=source_files,
                    create_time=row.create_time,
                    review_time=row.review_time,
                )
            )
        return items

    @staticmethod
    async def _list_user_names(user_ids: list[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        users = await UserDao.aget_user_by_ids(user_ids) or []
        return {int(user.user_id): user.user_name for user in users}

    # ------------------------------------------------------------------
    # Review mode reads
    # ------------------------------------------------------------------

    async def review_search(self, req: TagConsoleReviewSearchReq, tenant_id: int) -> TagConsoleReviewSearchResp:
        self._validate_page(req)
        space_ids = await self.tags_service.resolve_reviewable_space_ids()

        pairs, total = await self.repository.search_review_tags(req, tenant_id=tenant_id, space_ids=space_ids)
        pending_count, rejected_count = await self.repository.count_review_by_status(
            req, tenant_id=tenant_id, space_ids=space_ids
        )
        data = await self._decorate_review(pairs, tenant_id=tenant_id, space_ids=space_ids)
        return TagConsoleReviewSearchResp(
            data=data,
            total=total,
            pending_count=pending_count,
            rejected_count=rejected_count,
        )

    async def pending_count(self, tenant_id: int) -> int:
        """Badge on the left panel's fixed 'pending review' entry.

        Shares the query used by review mode so the two numbers cannot drift.
        """
        space_ids = await self.tags_service.resolve_reviewable_space_ids()
        pending, _ = await self.repository.count_review_by_status(
            TagConsoleReviewSearchReq(), tenant_id=tenant_id, space_ids=space_ids
        )
        return pending

    async def review_detail(self, ref: TagConsoleReviewRef, tenant_id: int) -> TagConsoleReviewItem:
        space_ids = await self.tags_service.resolve_reviewable_space_ids()
        items = await self._decorate_review([(ref.name, ref.resource_type)], tenant_id=tenant_id, space_ids=space_ids)
        if not items:
            raise ReviewTagNotFoundError()
        return items[0]

    async def _decorate_review(
        self,
        pairs: list[tuple[str, str]],
        tenant_id: int,
        space_ids: set[int] | None,
    ) -> list[TagConsoleReviewItem]:
        if not pairs:
            return []
        grouped = await self.repository.load_review_group(pairs, tenant_id=tenant_id, space_ids=space_ids)

        all_ids = [int(row.id) for rows in grouped.values() for row in rows if row.id is not None]
        files_by_tag = await self.repository.list_review_source_files(all_ids, tenant_id=tenant_id)
        file_ids = sorted({file_id for ids in files_by_tag.values() for file_id in ids})
        file_briefs = await self.repository.list_file_briefs(file_ids, tenant_id=tenant_id)

        library_ids = set()
        for rows in grouped.values():
            for row in rows:
                if row.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value and str(row.business_id or "").isdigit():
                    library_ids.add(int(row.business_id))
        library_names = await self.repository.list_library_names(sorted(library_ids), tenant_id=tenant_id)

        user_ids = set()
        for rows in grouped.values():
            for row in rows:
                if row.user_id:
                    user_ids.add(int(row.user_id))
                if row.reviewer_id:
                    user_ids.add(int(row.reviewer_id))
        user_names = await self._list_user_names(sorted(user_ids))

        items: list[TagConsoleReviewItem] = []
        for pair in pairs:
            rows = grouped.get(pair)
            if not rows:
                continue
            # Newest member represents the group, matching how the listing orders.
            newest = max(rows, key=lambda row: row.create_time or datetime.min)
            rejected = any(row.review_status == REJECTED_STATUS for row in rows)
            library_id = next(
                (
                    int(row.business_id)
                    for row in rows
                    if row.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value
                    and str(row.business_id or "").isdigit()
                ),
                None,
            )
            seen_files: list[TagConsoleSourceFile] = []
            seen_ids: set[int] = set()
            for row in rows:
                for file_id in files_by_tag.get(int(row.id), []):
                    if file_id in seen_ids or file_id not in file_briefs:
                        continue
                    seen_ids.add(file_id)
                    seen_files.append(TagConsoleSourceFile(**file_briefs[file_id]))
            items.append(
                TagConsoleReviewItem(
                    name=pair[0],
                    resource_type=pair[1],
                    status=TagConsoleReviewStatus.REJECTED if rejected else TagConsoleReviewStatus.PENDING,
                    review_tag_count=len(rows),
                    library_id=library_id,
                    library_name=library_names.get(library_id) if library_id else None,
                    submitter_id=newest.user_id or None,
                    submitter_name=user_names.get(newest.user_id) if newest.user_id else None,
                    reviewer_id=newest.reviewer_id,
                    reviewer_name=user_names.get(newest.reviewer_id) if newest.reviewer_id else None,
                    source_files=seen_files,
                    create_time=newest.create_time,
                    review_time=newest.review_time,
                    reject_reason=next((row.reject_reason for row in rows if row.reject_reason), None),
                )
            )
        return items

    # ------------------------------------------------------------------
    # Library mode writes
    # ------------------------------------------------------------------

    async def create_tag(self, req: TagConsoleCreateReq, tenant_id: int) -> TagConsoleItem:
        await self._ensure_can_manage_tags()
        name = (req.tag_name or "").strip()
        if not name:
            raise KnowledgeSpaceTagLibraryInvalidError(msg="标签名称不能为空")
        if not await self.repository.library_exists(req.library_id, tenant_id):
            raise KnowledgeSpaceTagLibraryNotExistError()
        # Tag names are unique across libraries; reuse the library service's own
        # check rather than growing a second rule that can drift from it.
        await KnowledgeSpaceTagLibraryService._ensure_global_tag_names_available(
            tenant_id=tenant_id,
            tag_names=[name],
        )

        tag = Tag(
            name=name,
            business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
            business_id=TagLibraryTagService._business_id(req.library_id),
            user_id=self.login_user.user_id,
            tenant_id=tenant_id,
            resource_type=TagResourceTypeEnum.SYSTEM_TAG.value,
            create_time=datetime.now(),
            update_time=datetime.now(),
        )
        await self.repository.insert_library_tag(tag)
        await self._commit_and_invalidate(tenant_id)
        return (await self._decorate([tag], tenant_id=tenant_id))[0]

    async def batch_delete(self, tag_ids: list[int], tenant_id: int) -> TagConsoleBatchResult:
        await self._ensure_can_manage_tags()
        self._validate_batch(tag_ids)
        found = await self.repository.get_library_tags_by_ids(tag_ids, tenant_id)
        result = self._start_result(tag_ids, found)
        if found:
            await self.repository.delete_library_tags([int(row.id) for row in found], tenant_id)
            result.succeeded = len(found)
            await self._commit_and_invalidate(tenant_id)
        return result

    async def batch_move(self, tag_ids: list[int], target_library_id: int, tenant_id: int) -> TagConsoleBatchResult:
        await self._ensure_can_manage_tags()
        self._validate_batch(tag_ids)
        if not await self.repository.library_exists(target_library_id, tenant_id):
            raise KnowledgeSpaceTagLibraryNotExistError()

        found = await self.repository.get_library_tags_by_ids(tag_ids, tenant_id)
        result = self._start_result(tag_ids, found)
        # business_id is an encoded value, not a bare library id.
        target_business_id = TagLibraryTagService._business_id(target_library_id)
        moved = 0
        for row in found:
            if row.business_id == target_business_id:
                result.skipped += 1
                continue
            clash = await self.repository.find_library_tag_by_name(row.name, target_library_id, tenant_id)
            if clash is not None:
                result.failed.append(TagConsoleBatchFailure(name=row.name or "", reason="目标标签库中已存在同名标签"))
                continue
            await self.repository.move_library_tag(int(row.id), target_business_id, tenant_id)
            moved += 1
        result.succeeded = moved
        if moved:
            await self._commit_and_invalidate(tenant_id)
        return result

    # ------------------------------------------------------------------
    # Review mode writes
    # ------------------------------------------------------------------

    async def batch_approve(
        self,
        items: list[TagConsoleReviewRef],
        target_library_id: int,
        tenant_id: int,
    ) -> TagConsoleBatchResult:
        return await self._batch_review(items, tenant_id, approve=True, target_library_id=target_library_id)

    async def batch_reject(
        self,
        items: list[TagConsoleReviewRef],
        reject_reason: str,
        tenant_id: int,
    ) -> TagConsoleBatchResult:
        if not (reject_reason or "").strip():
            raise TagConsoleRejectReasonRequiredError()
        return await self._batch_review(items, tenant_id, approve=False, reject_reason=reject_reason.strip())

    async def _batch_review(
        self,
        items: list[TagConsoleReviewRef],
        tenant_id: int,
        *,
        approve: bool,
        target_library_id: int | None = None,
        reject_reason: str | None = None,
    ) -> TagConsoleBatchResult:
        space_ids = await self.tags_service.resolve_reviewable_space_ids()
        self._validate_batch(items)
        if approve and not await self.repository.library_exists(target_library_id, tenant_id):
            raise KnowledgeSpaceTagLibraryNotExistError()

        pairs = [(item.name, item.resource_type) for item in items]
        grouped = await self.repository.load_review_group(pairs, tenant_id=tenant_id, space_ids=space_ids)

        result = TagConsoleBatchResult()
        for item in items:
            rows = grouped.get((item.name, item.resource_type))
            if not rows:
                result.failed.append(TagConsoleBatchFailure(name=item.name, reason="标签不存在或已被处理"))
                continue
            if any(row.review_status == REJECTED_STATUS for row in rows):
                # The underlying flow only looks at pending rows and would report
                # a bare "tag not found"; say what is actually wrong instead.
                raise TagConsoleActionNotApplicableError()
            knowledge_id = self._resolve_knowledge_id(rows, space_ids)
            if approve and knowledge_id is None:
                result.failed.append(TagConsoleBatchFailure(name=item.name, reason="缺少来源知识"))
                continue
            try:
                await self.tags_service.approve_or_reject_review_tag(
                    ApproveOrRejectRequest(
                        tag_name=item.name,
                        status=ApproveOrRejectEnum.APPROVE if approve else ApproveOrRejectEnum.REJECT,
                        resource_type=item.resource_type,
                        reject_reason=reject_reason,
                        tag_library_id=target_library_id,
                        knowledge_id=knowledge_id,
                    ),
                    tenant_id,
                )
            except Exception as exc:  # one bad item must not undo the whole batch
                logger.exception("tag console batch review failed for %s", item.name)
                result.failed.append(TagConsoleBatchFailure(name=item.name, reason=str(exc)))
                continue
            result.succeeded += 1

        if result.succeeded:
            await TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)
        return result

    @staticmethod
    def _resolve_knowledge_id(rows, space_ids: set[int] | None) -> int | None:
        """First in-scope knowledge space carrying the tag.

        A tag produced in several spaces still approves into one library; the
        review panel lists every source file so the reviewer sees the blast radius.
        """
        for row in rows:
            if row.business_type != TagBusinessTypeEnum.KNOWLEDGE_SPACE.value:
                continue
            if not str(row.business_id or "").isdigit():
                continue
            space_id = int(row.business_id)
            if space_ids is None or space_id in space_ids:
                return space_id
        return None

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_batch(items: list) -> None:
        if not items:
            raise TagConsolePageParamsError()
        if len(items) > MAX_BATCH_SIZE:
            raise TagConsoleBatchTooLargeError()

    @staticmethod
    def _start_result(requested_ids: list[int], found: list[Tag]) -> TagConsoleBatchResult:
        found_ids = {int(row.id) for row in found}
        missing = [tag_id for tag_id in requested_ids if int(tag_id) not in found_ids]
        return TagConsoleBatchResult(
            failed=[TagConsoleBatchFailure(name=str(tag_id), reason="标签不存在") for tag_id in missing]
        )

    async def _commit_and_invalidate(self, tenant_id: int) -> None:
        """Persist, then drop the Link B catalog cache once per operation.

        Without this the AI tagger keeps matching against tags that were just
        deleted or moved. One call per batch, not per item.
        """
        await self.repository.session.commit()
        await TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)
