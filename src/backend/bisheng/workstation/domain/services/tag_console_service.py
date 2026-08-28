"""Business logic for the F079 tag management console."""

from collections.abc import Iterable
from datetime import datetime

from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import (
    KnowledgeSpaceTagLibraryInvalidError,
    KnowledgeSpaceTagLibraryNotExistError,
)
from bisheng.common.errcode.tag import ReviewTagNotFoundError
from bisheng.common.errcode.workstation import (
    TagConsoleBatchTooLargeError,
    TagConsolePageParamsError,
    TagConsoleRejectReasonRequiredError,
)
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_tag_library_service import (
    KnowledgeSpaceTagLibraryService,
)
from bisheng.knowledge.domain.services.tag_blacklist_service import TAG_BLACKLIST_MAX, TagBlacklistService
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService
from bisheng.user.domain.models.user import UserDao
from bisheng.workstation.domain.repositories.tag_console_repository import (
    PENDING_STATUS,
    REJECTED_STATUS,
    SOURCE_REVIEW,
    SOURCE_TAG,
    TagConsoleRepositoryImpl,
)
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest, ReviewTagScope
from bisheng.workstation.domain.schemas.tag_console_schema import (
    MAX_BATCH_SIZE,
    MAX_PAGE_SIZE,
    TagConsoleBatchFailure,
    TagConsoleBatchResult,
    TagConsoleBlacklistCreateReq,
    TagConsoleBlacklistItem,
    TagConsoleBlacklistSearchReq,
    TagConsoleBlacklistSearchResp,
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
    TagConsoleSourceKnowledge,
    TagConsoleSourceKnowledgeResp,
)
from bisheng.workstation.domain.services.workstation_tags_service import WorkStationTagsService


class TagConsoleService:
    """Reads for the console's library mode.

    Tag Console 库管理门禁独立于门户标签审核 scope：仅超管 / 租户管理员 /
    部门管理员可进入。库 admin/creator 即使能审标签，也不能获得全租户库管理权。
    控制台内审核子能力仍委托 ``WorkStationTagsService``（走 ReviewTagScope）。
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
    def _validate_page(req: TagConsoleFilter | TagConsoleBlacklistSearchReq) -> None:
        if req.page < 1 or req.page_size < 1 or req.page_size > MAX_PAGE_SIZE:
            raise TagConsolePageParamsError()

    async def _ensure_can_manage_tags(self) -> None:
        """仅放行超管 / RBAC admin / 子租户管理员 / 部门管理员。"""
        from bisheng.common.errcode.tag import ReviewTagPermissionDeniedError

        login_user = self.login_user
        if bool(getattr(login_user, "is_global_super", False)):
            return
        is_admin_fn = getattr(login_user, "is_admin", None)
        if callable(is_admin_fn) and is_admin_fn():
            return

        has_tenant_admin = getattr(login_user, "has_tenant_admin", None)
        if callable(has_tenant_admin):
            from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id

            tid = get_current_tenant_id()
            if tid is None:
                tid = getattr(login_user, "tenant_id", None)
            if tid is not None and int(tid) != DEFAULT_TENANT_ID and await has_tenant_admin(int(tid)):
                return

        from bisheng.database.models.department import DepartmentDao

        admin_depts = await DepartmentDao.aget_user_admin_departments(int(login_user.user_id))
        if admin_depts:
            return
        raise ReviewTagPermissionDeniedError()

    async def _review_scope_or_full(self) -> ReviewTagScope | None:
        """解析审核范围：全租户返回 None（仓库不过滤），否则返回受限 scope。"""
        scope = await self.tags_service.resolve_review_tag_scope()
        if scope.full_tenant:
            return None
        return scope

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
        scope = await self._review_scope_or_full()

        if req.status in (TagConsoleReviewStatus.APPROVED, TagConsoleReviewStatus.REVIEWED):
            # The "已审核" tab spans two tables, so rows arrive tagged with the
            # one they came from.
            refs, total = await self.repository.search_reviewed_tags(req, tenant_id=tenant_id, scope=scope)
        else:
            pairs, total = await self.repository.search_review_tags(req, tenant_id=tenant_id, scope=scope)
            refs = [(SOURCE_REVIEW, name, resource_type) for name, resource_type in pairs]

        pending_count, rejected_count, approved_count = await self.repository.count_review_by_status(
            req, tenant_id=tenant_id, scope=scope
        )
        data = await self._assemble_review_page(refs, tenant_id=tenant_id, scope=scope)
        return TagConsoleReviewSearchResp(
            data=data,
            total=total,
            pending_count=pending_count,
            rejected_count=rejected_count,
            approved_count=approved_count,
        )

    async def _assemble_review_page(
        self,
        refs: list[tuple[int, str, str]],
        tenant_id: int,
        scope: ReviewTagScope | None,
    ) -> list[TagConsoleReviewItem]:
        """Decorate each half with its own query, then restore the page order.

        Rebuilding from ``refs`` rather than concatenating the two halves is what
        keeps approved and rejected rows interleaved by review time instead of
        clumping into two blocks.
        """
        if not refs:
            return []
        review_pairs = [(name, resource_type) for source, name, resource_type in refs if source == SOURCE_REVIEW]
        approved_pairs = [(name, resource_type) for source, name, resource_type in refs if source == SOURCE_TAG]

        review_items = {
            (item.name, item.resource_type): item
            for item in await self._decorate_review(review_pairs, tenant_id=tenant_id, scope=scope)
        }
        approved_items = await self._decorate_approved(approved_pairs, tenant_id=tenant_id)

        ordered: list[TagConsoleReviewItem] = []
        for source, name, resource_type in refs:
            bucket = approved_items if source == SOURCE_TAG else review_items
            item = bucket.get((name, resource_type))
            if item is not None:
                ordered.append(item)
        return ordered

    async def _decorate_approved(
        self,
        pairs: list[tuple[str, str]],
        tenant_id: int,
    ) -> dict[tuple[str, str], TagConsoleReviewItem]:
        """Approved rows reuse library mode's decoration, then get reshaped.

        Same underlying tag, just presented with a review status so the reviewed
        listing can hold both kinds of row in one table.
        """
        if not pairs:
            return {}
        tags = await self.repository.get_library_tags_by_names([name for name, _ in pairs], tenant_id=tenant_id)
        wanted = set(pairs)
        tags = [tag for tag in tags if (tag.name, tag.resource_type) in wanted]
        items = await self._decorate(tags, tenant_id=tenant_id)
        return {
            (item.name, item.resource_type): TagConsoleReviewItem(
                name=item.name,
                resource_type=item.resource_type,
                status=TagConsoleReviewStatus.APPROVED,
                review_tag_count=1,
                library_id=item.library_id,
                library_name=item.library_name,
                submitter_id=item.submitter_id,
                submitter_name=item.submitter_name,
                reviewer_id=item.reviewer_id,
                reviewer_name=item.reviewer_name,
                source_files=item.source_files,
                create_time=item.create_time,
                review_time=item.review_time,
            )
            for item in items
        }

    async def pending_count(self, tenant_id: int) -> int:
        """Badge on the left panel's fixed 'pending review' entry.

        Shares the query used by review mode so the two numbers cannot drift.
        """
        scope = await self._review_scope_or_full()
        pending, _, _ = await self.repository.count_review_by_status(
            TagConsoleReviewSearchReq(), tenant_id=tenant_id, scope=scope
        )
        return pending

    async def list_source_knowledges(
        self,
        tenant_id: int,
        keyword: str | None = None,
    ) -> TagConsoleSourceKnowledgeResp:
        """Options for the 标签来源库 filter.

        Only knowledge bases that actually produced a tag, so the dropdown does
        not fill up with every user's personal space and 『我的收藏』.
        """
        await self._ensure_can_manage_tags()
        rows = await self.repository.list_source_knowledges(tenant_id=tenant_id, keyword=keyword)
        return TagConsoleSourceKnowledgeResp(
            data=[TagConsoleSourceKnowledge(id=knowledge_id, name=name) for knowledge_id, name in rows]
        )

    async def review_detail(self, ref: TagConsoleReviewRef, tenant_id: int) -> TagConsoleReviewItem:
        scope = await self._review_scope_or_full()
        items = await self._decorate_review([(ref.name, ref.resource_type)], tenant_id=tenant_id, scope=scope)
        if not items:
            raise ReviewTagNotFoundError()
        return items[0]

    async def _decorate_review(
        self,
        pairs: list[tuple[str, str]],
        tenant_id: int,
        scope: ReviewTagScope | None,
    ) -> list[TagConsoleReviewItem]:
        if not pairs:
            return []
        grouped = await self.repository.load_review_group(pairs, tenant_id=tenant_id, scope=scope)

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
        await self._commit_and_invalidate(tenant_id, library_ids=[req.library_id])
        return (await self._decorate([tag], tenant_id=tenant_id))[0]

    async def batch_delete(self, tag_ids: list[int], tenant_id: int) -> TagConsoleBatchResult:
        await self._ensure_can_manage_tags()
        self._validate_batch(tag_ids)
        found = await self.repository.get_library_tags_by_ids(tag_ids, tenant_id)
        result = self._start_result(tag_ids, found)
        if found:
            touched = self._library_ids_of(found)
            await self.repository.delete_library_tags([int(row.id) for row in found], tenant_id)
            result.succeeded = len(found)
            await self._commit_and_invalidate(tenant_id, library_ids=touched)
        return result

    async def batch_move(self, tag_ids: list[int], target_library_id: int, tenant_id: int) -> TagConsoleBatchResult:
        await self._ensure_can_manage_tags()
        self._validate_batch(tag_ids)
        if not await self.repository.library_exists(target_library_id, tenant_id):
            raise KnowledgeSpaceTagLibraryNotExistError()

        found = await self.repository.get_library_tags_by_ids(tag_ids, tenant_id)
        result = self._start_result(tag_ids, found)
        # Both ends of a move change: the tag leaves one library's name list and
        # joins another's.
        touched = self._library_ids_of(found) | {int(target_library_id)}
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
            await self._commit_and_invalidate(tenant_id, library_ids=touched)
        return result

    # ------------------------------------------------------------------
    # Review mode writes
    # ------------------------------------------------------------------

    async def batch_approve(
        self,
        items: list[TagConsoleReviewRef],
        target_library_id: int,
        tenant_id: int,
        *,
        ack_similar: bool = False,
    ) -> TagConsoleBatchResult:
        return await self._batch_review(
            items,
            tenant_id,
            approve=True,
            target_library_id=target_library_id,
            ack_similar=ack_similar,
        )

    async def batch_reject(
        self,
        items: list[TagConsoleReviewRef],
        reject_reason: str,
        tenant_id: int,
        *,
        skip_blacklist: bool = False,
    ) -> TagConsoleBatchResult:
        if not (reject_reason or "").strip():
            raise TagConsoleRejectReasonRequiredError()
        if not skip_blacklist:
            await TagBlacklistService.ensure_can_insert_async([item.name for item in items])
        return await self._batch_review(
            items,
            tenant_id,
            approve=False,
            reject_reason=reject_reason.strip(),
            skip_blacklist=skip_blacklist,
        )

    async def _batch_review(
        self,
        items: list[TagConsoleReviewRef],
        tenant_id: int,
        *,
        approve: bool,
        target_library_id: int | None = None,
        reject_reason: str | None = None,
        ack_similar: bool = False,
        skip_blacklist: bool = False,
    ) -> TagConsoleBatchResult:
        scope = await self._review_scope_or_full()
        self._validate_batch(items)
        if approve and not await self.repository.library_exists(target_library_id, tenant_id):
            raise KnowledgeSpaceTagLibraryNotExistError()
        if approve:
            await self.tags_service.ensure_review_tags_similar_acknowledged(
                tag_names=[item.name for item in items],
                tag_library_id=int(target_library_id),
                tenant_id=tenant_id,
                ack_similar=ack_similar,
            )

        pairs = [(item.name, item.resource_type) for item in items]
        grouped = await self.repository.load_review_group(pairs, tenant_id=tenant_id, scope=scope)
        # One batched lookup for the whole request rather than per item.
        spaces_by_review_tag = await self._map_review_tags_to_spaces(grouped, tenant_id=tenant_id) if approve else {}

        result = TagConsoleBatchResult()
        for item in items:
            rows = grouped.get((item.name, item.resource_type))
            if not rows:
                result.failed.append(TagConsoleBatchFailure(name=item.name, reason="标签不存在或已被处理"))
                continue
            pending_rows = [
                row
                for row in rows
                if int(getattr(row, "review_status", PENDING_STATUS) or PENDING_STATUS) == PENDING_STATUS
            ]
            # Same name may have an older rejected row (soft-delete). Acting on
            # the new pending proposal must not fail the whole batch.
            if not pending_rows:
                result.failed.append(
                    TagConsoleBatchFailure(name=item.name, reason="该标签的当前状态不支持此操作")
                )
                continue
            knowledge_id = self._resolve_knowledge_id(pending_rows, scope, spaces_by_review_tag)
            if approve and knowledge_id is None:
                # Logged, not silent: this rejects the whole item while still
                # returning HTTP 200, which is invisible in the access log.
                logger.warning(
                    "tag console approve skipped, no in-scope source space for %s (review_tag ids=%s, scope=%s)",
                    item.name,
                    [row.id for row in rows],
                    "all"
                    if scope is None
                    else (
                        f"role={sorted(scope.role_managed_space_ids)} "
                        f"clinic={sorted(scope.clinic_admin_department_ids)}"
                    ),
                )
                result.failed.append(TagConsoleBatchFailure(name=item.name, reason="缺少来源知识"))
                continue
            # reject_reason is declared `str = None`: pydantic skips the default
            # but validates anything passed in, so handing it an explicit None on
            # the approve path fails the request outright. Omit it instead.
            payload = {
                "tag_name": item.name,
                "status": ApproveOrRejectEnum.APPROVE if approve else ApproveOrRejectEnum.REJECT,
                "resource_type": item.resource_type,
                "tag_library_id": target_library_id,
                "knowledge_id": knowledge_id,
                "ack_similar": ack_similar if approve else False,
                "skip_blacklist": skip_blacklist if not approve else False,
            }
            if reject_reason is not None:
                payload["reject_reason"] = reject_reason
            try:
                await self.tags_service.approve_or_reject_review_tag(
                    ApproveOrRejectRequest(**payload),
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

    async def _map_review_tags_to_spaces(
        self,
        grouped: dict[tuple[str, str], list],
        tenant_id: int,
    ) -> dict[int, list[int]]:
        """Knowledge space ids per ``review_tag`` row, via its source files.

        ``review_tag.business_id`` cannot be used for this: in practice these
        rows carry ``business_type='tag_library'`` and the id is the *tag
        library*, not a space. Reading it as a space id would approve the tag
        into the wrong knowledge space. The provenance that does hold is the
        file link — the same route the workbench page takes.
        """
        review_tag_ids = [int(row.id) for rows in grouped.values() for row in rows if row.id is not None]
        if not review_tag_ids:
            return {}
        files_by_tag = await self.repository.list_review_source_files(review_tag_ids, tenant_id=tenant_id)
        file_ids = sorted({file_id for ids in files_by_tag.values() for file_id in ids})
        file_briefs = await self.repository.list_file_briefs(file_ids, tenant_id=tenant_id)

        spaces: dict[int, list[int]] = {}
        for review_tag_id, ids in files_by_tag.items():
            seen: list[int] = []
            for file_id in ids:
                space_id = (file_briefs.get(file_id) or {}).get("knowledge_id")
                if space_id and space_id not in seen:
                    seen.append(int(space_id))
            if seen:
                spaces[review_tag_id] = seen
        return spaces

    @staticmethod
    def _resolve_knowledge_id(
        rows,
        scope: ReviewTagScope | None,
        spaces_by_review_tag: dict[int, list[int]],
    ) -> int | None:
        """解析通过时写入的目标知识空间。

        优先来源文件所在、且落在 role 管理空间内的库；科室路径下再用文件来源
        团队/个人库（2A）。``business_id`` 仅在行明确声明 knowledge_space 时兜底。
        """
        full = scope is None or scope.full_tenant
        role_ids = frozenset() if full else scope.role_managed_space_ids
        clinic = False if full else bool(scope.clinic_admin_department_ids)

        for row in rows:
            for space_id in spaces_by_review_tag.get(int(row.id), []):
                if full or space_id in role_ids:
                    return space_id
        if clinic:
            for row in rows:
                for space_id in spaces_by_review_tag.get(int(row.id), []):
                    return space_id
        for row in rows:
            if row.business_type != TagBusinessTypeEnum.KNOWLEDGE_SPACE.value:
                continue
            if not str(row.business_id or "").isdigit():
                continue
            space_id = int(row.business_id)
            if full or space_id in role_ids or clinic:
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

    @staticmethod
    def _library_ids_of(tags: list[Tag]) -> set[int]:
        return {int(tag.business_id) for tag in tags if str(tag.business_id or "").isdigit()}

    async def _commit_and_invalidate(self, tenant_id: int, library_ids: Iterable[int] = ()) -> None:
        """Persist, resync the touched libraries, then drop the Link B cache.

        The resync has to run *after* the commit: it reads the tag rows back
        through its own session and would otherwise still see the pre-write
        state. Skipping it lets a library keep listing names it no longer has,
        which is what made deleted tags reappear — see
        ``TagLibraryTagService.sync_library_name_lists``.

        The cache eviction is last, and once per operation rather than per item:
        without it the AI tagger keeps matching against tags just deleted.
        """
        await self.repository.session.commit()
        for library_id in sorted(set(library_ids)):
            await TagLibraryTagService.sync_library_name_lists(library_id)
        await TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)

    async def preview_blacklist(self, names: list[str]) -> dict:
        await self._ensure_can_manage_tags()
        preview = await TagBlacklistService.preview_insert_async(names)
        return {
            "count": preview.count,
            "limit": preview.limit,
            "new_count": preview.new_count,
            "would_exceed": preview.would_exceed,
        }

    async def list_blacklist(self, req: TagConsoleBlacklistSearchReq) -> TagConsoleBlacklistSearchResp:
        self._validate_page(req)
        await self._ensure_can_manage_tags()
        rows, total, count = await TagBlacklistService.search_async(
            keyword=req.keyword,
            page=req.page,
            page_size=req.page_size,
        )
        return TagConsoleBlacklistSearchResp(
            data=[
                TagConsoleBlacklistItem(
                    id=int(row.id),
                    name=row.name,
                    user_id=int(row.user_id or 0),
                    create_time=row.create_time,
                )
                for row in rows
                if row.id is not None
            ],
            total=total,
            count=count,
            limit=TAG_BLACKLIST_MAX,
        )

    async def delete_blacklist(self, blacklist_id: int) -> bool:
        await self._ensure_can_manage_tags()
        await TagBlacklistService.delete_async(int(blacklist_id))
        return True

    async def add_blacklist(self, req: TagConsoleBlacklistCreateReq) -> TagConsoleBlacklistItem:
        await self._ensure_can_manage_tags()
        row = await TagBlacklistService.add_name_async(
            req.name,
            user_id=int(getattr(self.login_user, "user_id", 0) or 0),
        )
        return TagConsoleBlacklistItem(
            id=int(row.id),
            name=row.name,
            user_id=int(row.user_id or 0),
            create_time=row.create_time,
        )
