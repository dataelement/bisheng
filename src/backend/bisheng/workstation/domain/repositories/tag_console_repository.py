"""Queries backing the F079 tag management console.

Library mode reads ``tag``; review mode reads ``review_tag``. The console
switches between them from the left panel, so each side pages independently.

The one exception is the reviewed ("已审核") listing: approving a tag deletes its
``review_tag`` row and writes the tag into ``tag``, so approved and rejected
history live in different tables and only that listing needs a UNION.
"""

from sqlalchemy import Integer, cast, exists, literal, or_, union, union_all
from sqlmodel import delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.review_tags import ApproveOrRejectEnum, ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.workstation.domain.repositories.review_tags_repository import (
    build_clinic_uploader_match_clause,
)
from bisheng.workstation.domain.schemas.review_tags_schema import ReviewTagScope
from bisheng.workstation.domain.schemas.tag_console_schema import (
    TagConsoleFilter,
    TagConsoleReviewSearchReq,
    TagConsoleReviewStatus,
    TagConsoleSearchReq,
)

PENDING_STATUS = 0
REJECTED_STATUS = ApproveOrRejectEnum.REJECT.value

# Which table a "已审核" row came from. Approved tags no longer exist in
# review_tag, so the reviewed listing reads two tables and has to say which one
# each row belongs to before it can be decorated.
SOURCE_TAG = 0
SOURCE_REVIEW = 1


class TagConsoleRepositoryImpl:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Library mode — approved tags
    # ------------------------------------------------------------------

    @staticmethod
    def _source_space_clause(link_model, tag_id_column, tenant_id: int, knowledge_id: int):
        """Rows whose source files live in the given knowledge space.

        Neither ``tag`` nor ``review_tag`` records the space a tag came from, so
        provenance is matched through the file link. Deleted links are not
        excluded: rejecting soft-deletes them and those rows must still be
        findable by their source.

        Same shape for both tables, hence the passed-in link model.
        """
        return exists(
            select(1)
            .select_from(link_model)
            .join(
                KnowledgeFile,
                # Compare as integers: resource_id is varchar, and CAST(id AS CHAR)
                # hits collation mismatches on MySQL.
                KnowledgeFile.id == cast(link_model.resource_id, Integer),
            )
            .where(
                link_model.tag_id == tag_id_column,
                link_model.tenant_id == tenant_id,
                KnowledgeFile.tenant_id == tenant_id,
                KnowledgeFile.knowledge_id == knowledge_id,
            )
        )

    @classmethod
    def _tag_field_filters(cls, req: TagConsoleFilter, tenant_id: int) -> list:
        """Where-clauses over ``tag`` shared by library mode and the approved half
        of the reviewed listing.

        Visibility is tenant-only by design (AD-12): tag libraries are tenant-level
        vocabulary, so narrowing these rows per department would make the left
        panel's tag_count disagree with what the table shows, and would hide a
        tag that nobody has applied to a file yet.
        """
        clauses = [
            Tag.tenant_id == tenant_id,
            # The table is shared with application/knowledge tags, which belong
            # to other features and must never surface here.
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
        ]
        if req.tag_name:
            clauses.append(Tag.name.like(f"%{req.tag_name.strip()}%"))
        if req.resource_type:
            clauses.append(Tag.resource_type == req.resource_type)
        if req.submitter_id is not None:
            clauses.append(Tag.user_id == req.submitter_id)
        if req.reviewer_id is not None:
            clauses.append(Tag.reviewer_id == req.reviewer_id)
        if req.create_time_start is not None:
            clauses.append(Tag.create_time >= req.create_time_start)
        if req.create_time_end is not None:
            clauses.append(Tag.create_time <= req.create_time_end)
        if req.review_time_start is not None:
            clauses.append(Tag.review_time >= req.review_time_start)
        if req.review_time_end is not None:
            clauses.append(Tag.review_time <= req.review_time_end)
        if req.source_knowledge_id is not None:
            clauses.append(cls._source_space_clause(TagLink, Tag.id, tenant_id, req.source_knowledge_id))
        return clauses

    @classmethod
    def _library_tag_filters(cls, req: TagConsoleSearchReq, tenant_id: int) -> list:
        clauses = cls._tag_field_filters(req, tenant_id)
        if req.library_ids:
            # Unknown ids simply match nothing — a library another admin deleted
            # must not turn the request into an error.
            clauses.append(Tag.business_id.in_([str(library_id) for library_id in req.library_ids]))
        return clauses

    async def search_library_tags(self, req: TagConsoleSearchReq, tenant_id: int) -> tuple[list[Tag], int]:
        """Return one page of approved tags plus the unpaged total.

        Ordered newest-first with ``id`` as tiebreak. Within a single table ``id``
        is unique, so the pair is a total order and paging can neither repeat nor
        drop a row.
        """
        clauses = self._library_tag_filters(req, tenant_id)

        total = await self.session.scalar(select(func.count(Tag.id)).where(*clauses))

        statement = (
            select(Tag)
            .where(*clauses)
            .order_by(Tag.create_time.desc(), Tag.id.desc())
            .offset((req.page - 1) * req.page_size)
            .limit(req.page_size)
        )
        rows = (await self.session.exec(statement)).all()
        return list(rows), int(total or 0)

    async def count_marked_knowledge(self, tag_ids: list[int], tenant_id: int) -> dict[int, int]:
        """How many knowledge files each tag is applied to.

        One grouped query for the whole page rather than a count per row.
        Tags with no links are absent from the result; callers default to zero.
        """
        normalized = [int(tag_id) for tag_id in tag_ids if tag_id]
        if not normalized:
            return {}
        statement = (
            select(TagLink.tag_id, func.count(func.distinct(TagLink.resource_id)))
            .where(TagLink.tag_id.in_(normalized), TagLink.tenant_id == tenant_id)
            .group_by(TagLink.tag_id)
        )
        rows = (await self.session.exec(statement)).all()
        return {int(tag_id): int(count) for tag_id, count in rows}

    async def list_source_files(self, tag_ids: list[int], tenant_id: int) -> dict[int, list[int]]:
        """Knowledge file ids per tag, again batched for the whole page."""
        normalized = [int(tag_id) for tag_id in tag_ids if tag_id]
        if not normalized:
            return {}
        statement = select(TagLink.tag_id, TagLink.resource_id).where(
            TagLink.tag_id.in_(normalized),
            TagLink.tenant_id == tenant_id,
        )
        rows = (await self.session.exec(statement)).all()
        grouped: dict[int, list[int]] = {}
        for tag_id, resource_id in rows:
            if not str(resource_id).isdigit():
                continue
            grouped.setdefault(int(tag_id), []).append(int(resource_id))
        return grouped

    # ------------------------------------------------------------------
    # Display-name lookups, all batched per page to avoid N+1
    # ------------------------------------------------------------------

    async def list_library_names(self, library_ids: list[int], tenant_id: int) -> dict[int, str]:
        normalized = [int(library_id) for library_id in library_ids if library_id]
        if not normalized:
            return {}
        statement = select(KnowledgeSpaceTagLibrary.id, KnowledgeSpaceTagLibrary.name).where(
            KnowledgeSpaceTagLibrary.id.in_(normalized),
            KnowledgeSpaceTagLibrary.tenant_id == tenant_id,
        )
        rows = (await self.session.exec(statement)).all()
        return {int(library_id): name for library_id, name in rows}

    async def list_file_briefs(self, file_ids: list[int], tenant_id: int) -> dict[int, dict]:
        """Minimal file info the console shows: name, owning space, parent folder."""
        normalized = [int(file_id) for file_id in file_ids if file_id]
        if not normalized:
            return {}
        statement = select(
            KnowledgeFile.id,
            KnowledgeFile.file_name,
            KnowledgeFile.knowledge_id,
            KnowledgeFile.file_level_path,
            KnowledgeFile.status,
            KnowledgeFile.remark,
        ).where(
            KnowledgeFile.id.in_(normalized),
            KnowledgeFile.tenant_id == tenant_id,
        )
        rows = (await self.session.exec(statement)).all()
        space_names = await self.list_knowledge_names(
            [row[2] for row in rows],
            tenant_id=tenant_id,
        )
        return {
            int(file_id): {
                "file_id": int(file_id),
                "file_name": file_name or "",
                "knowledge_id": int(knowledge_id) if knowledge_id is not None else 0,
                "knowledge_name": space_names.get(int(knowledge_id)) if knowledge_id is not None else None,
                "parent_id": self.parent_folder_id_from_level_path(file_level_path),
                "status": status,
                "remark": remark,
            }
            for file_id, file_name, knowledge_id, file_level_path, status, remark in rows
        }

    async def list_source_knowledges(
        self,
        tenant_id: int,
        keyword: str | None = None,
        limit: int = 200,
    ) -> list[tuple[int, str]]:
        """Knowledge bases that have actually produced tags.

        The 标签来源库 filter used to be fed the full knowledge-base list, which on
        a real install is mostly noise: every user owns a personal space and a
        『我的收藏』, so the dropdown showed dozens of identically named entries
        that could never match a tag. Offering only genuine sources removes them
        without having to guess from names, and repeated names collapse because
        the set is distinct by id.

        『我的收藏』 is excluded outright — it is a per-user pin board, not a
        source anyone filters by, even on the rare install where a file in it
        carried a tag.
        """
        tagged = (
            select(KnowledgeFile.knowledge_id)
            .select_from(TagLink)
            .join(KnowledgeFile, KnowledgeFile.id == cast(TagLink.resource_id, Integer))
            .where(TagLink.tenant_id == tenant_id, KnowledgeFile.tenant_id == tenant_id)
        )
        reviewed = (
            select(KnowledgeFile.knowledge_id)
            .select_from(ReviewTagLink)
            .join(KnowledgeFile, KnowledgeFile.id == cast(ReviewTagLink.resource_id, Integer))
            .where(ReviewTagLink.tenant_id == tenant_id, KnowledgeFile.tenant_id == tenant_id)
        )
        sources = union(tagged, reviewed).subquery()

        clauses = [
            Knowledge.tenant_id == tenant_id,
            Knowledge.id.in_(select(sources.c.knowledge_id)),
            Knowledge.is_favorite == False,  # noqa: E712
        ]
        if keyword and keyword.strip():
            clauses.append(Knowledge.name.like(f"%{keyword.strip()}%"))
        statement = select(Knowledge.id, Knowledge.name).where(*clauses).order_by(Knowledge.name.asc()).limit(limit)
        rows = (await self.session.exec(statement)).all()
        return [(int(knowledge_id), name or "") for knowledge_id, name in rows]

    async def list_knowledge_names(self, knowledge_ids: list[int], tenant_id: int) -> dict[int, str]:
        """Names of the knowledge bases a page's source files belong to.

        One query for the whole page — the 标签来源库 column would otherwise be a
        lookup per file.
        """
        normalized = {int(knowledge_id) for knowledge_id in knowledge_ids if knowledge_id}
        if not normalized:
            return {}
        statement = select(Knowledge.id, Knowledge.name).where(
            Knowledge.id.in_(sorted(normalized)),
            Knowledge.tenant_id == tenant_id,
        )
        rows = (await self.session.exec(statement)).all()
        return {int(knowledge_id): name for knowledge_id, name in rows}

    # ------------------------------------------------------------------
    # Library mode — writes
    # ------------------------------------------------------------------

    async def get_library_tags_by_ids(self, tag_ids: list[int], tenant_id: int) -> list[Tag]:
        normalized = [int(tag_id) for tag_id in tag_ids if tag_id]
        if not normalized:
            return []
        statement = select(Tag).where(
            Tag.id.in_(normalized),
            Tag.tenant_id == tenant_id,
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
        )
        return list((await self.session.exec(statement)).all())

    async def get_library_tags_by_names(self, names: list[str], tenant_id: int) -> list[Tag]:
        """Approved tags by name, for the reviewed listing.

        Safe as a lookup key here because tag names are unique per tenant across
        every library — the create path enforces that before inserting.
        """
        wanted = [name for name in names if name]
        if not wanted:
            return []
        statement = select(Tag).where(
            Tag.name.in_(wanted),
            Tag.tenant_id == tenant_id,
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
        )
        return list((await self.session.exec(statement)).all())

    async def find_library_tag_by_name(self, name: str, library_id: int, tenant_id: int) -> Tag | None:
        statement = select(Tag).where(
            Tag.name == name,
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.business_id == str(library_id),
            Tag.tenant_id == tenant_id,
        )
        return (await self.session.exec(statement)).first()

    async def insert_library_tag(self, tag: Tag) -> Tag:
        self.session.add(tag)
        await self.session.flush()
        return tag

    async def delete_library_tags(self, tag_ids: list[int], tenant_id: int) -> None:
        """Drop the tags and their file associations together."""
        normalized = [int(tag_id) for tag_id in tag_ids if tag_id]
        if not normalized:
            return
        await self.session.exec(delete(TagLink).where(TagLink.tag_id.in_(normalized), TagLink.tenant_id == tenant_id))
        await self.session.exec(
            delete(Tag).where(
                Tag.id.in_(normalized),
                Tag.tenant_id == tenant_id,
                Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            )
        )

    async def move_library_tag(self, tag_id: int, business_id: str, tenant_id: int) -> None:
        await self.session.exec(
            update(Tag)
            .where(
                Tag.id == tag_id,
                Tag.tenant_id == tenant_id,
                Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            )
            .values(business_id=business_id)
        )

    async def library_exists(self, library_id: int, tenant_id: int) -> bool:
        statement = select(KnowledgeSpaceTagLibrary.id).where(
            KnowledgeSpaceTagLibrary.id == library_id,
            KnowledgeSpaceTagLibrary.tenant_id == tenant_id,
        )
        return (await self.session.exec(statement)).first() is not None

    # ------------------------------------------------------------------
    # Review mode — pending / rejected tags
    # ------------------------------------------------------------------

    @staticmethod
    def _library_tag_names(tenant_id: int):
        """Names already promoted into a real tag library.

        The workbench listing hides these, and so must we: once a name exists as
        an approved tag, a leftover pending row for it is noise. Diverging here
        would make this page show more rows than the old one for the same data.
        """
        return select(Tag.name).where(
            Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
            Tag.tenant_id == tenant_id,
        )

    @staticmethod
    def _has_active_link(tenant_id: int):
        """Orphan pending tags — every file association gone — are hidden too."""
        return exists(
            select(1).where(
                ReviewTagLink.tag_id == ReviewTag.id,
                ReviewTagLink.tenant_id == tenant_id,
                ReviewTagLink.is_deleted == False,  # noqa: E712
            )
        )

    @classmethod
    def _space_scope_clause(cls, tenant_id: int, scope: ReviewTagScope | None):
        """按 ReviewTagScope 收窄审核列表；None 表示全租户不过滤。

        role 空间走 business_id / 文件 knowledge_id；科室路径并上上传人主部门
        且 org_level=office 的团队/个人库（与待审列表同一 SQL）。
        """
        if scope is None or scope.full_tenant:
            return None
        parts = []
        if scope.role_managed_space_ids:
            space_id_list = sorted(int(space_id) for space_id in scope.role_managed_space_ids)
            business_match = ReviewTag.business_type.in_(
                [TagBusinessTypeEnum.KNOWLEDGE_SPACE.value, TagBusinessTypeEnum.KNOWLEDGE.value]
            ) & ReviewTag.business_id.in_([str(space_id) for space_id in space_id_list])
            link_match = exists(
                select(1)
                .select_from(ReviewTagLink)
                .join(
                    KnowledgeFile,
                    # Compare as integers: resource_id is varchar, and CAST(id AS CHAR)
                    # hits collation mismatches on MySQL.
                    KnowledgeFile.id == cast(ReviewTagLink.resource_id, Integer),
                )
                .where(
                    ReviewTagLink.tag_id == ReviewTag.id,
                    ReviewTagLink.tenant_id == tenant_id,
                    KnowledgeFile.tenant_id == tenant_id,
                    KnowledgeFile.knowledge_id.in_(space_id_list),
                )
            )
            parts.append(or_(business_match, link_match))
        if scope.clinic_admin_department_ids:
            parts.append(build_clinic_uploader_match_clause(tenant_id, set(scope.clinic_admin_department_ids)))
        if not parts:
            return ReviewTag.id == -1
        return or_(*parts)

    @classmethod
    def _status_clause(cls, status: TagConsoleReviewStatus | None, tenant_id: int):
        """Pending and rejected rows need different conditions, not one filter.

        Approving deletes the row outright, so anything left is either pending or
        rejected. Rejecting *soft-deletes* both the tag and its links — which is
        why the orphan and library-name guards apply to the pending branch only:
        applied to rejected rows they would hide every one of them.
        """
        pending = (
            (ReviewTag.review_status == PENDING_STATUS)
            & (ReviewTag.is_deleted == False)  # noqa: E712
            & ReviewTag.name.not_in(cls._library_tag_names(tenant_id))
            & cls._has_active_link(tenant_id)
        )
        rejected = ReviewTag.review_status == REJECTED_STATUS
        if status == TagConsoleReviewStatus.PENDING:
            return pending
        if status == TagConsoleReviewStatus.REJECTED:
            return rejected
        if status == TagConsoleReviewStatus.APPROVED:
            # Approved tags were deleted from this table; they are read from
            # ``tag`` instead. Matching nothing here keeps a stray caller honest
            # rather than silently handing back pending rows.
            return ReviewTag.id == -1
        if status == TagConsoleReviewStatus.REVIEWED:
            return rejected  # only the rejected half of "已审核" lives here
        return or_(pending, rejected)

    @classmethod
    def _review_filters(cls, req: TagConsoleReviewSearchReq, tenant_id: int, scope: ReviewTagScope | None) -> list:
        clauses = [ReviewTag.tenant_id == tenant_id, cls._status_clause(req.status, tenant_id)]
        scope_clause = cls._space_scope_clause(tenant_id, scope)
        if scope_clause is not None:
            clauses.append(scope_clause)
        if req.tag_name:
            clauses.append(ReviewTag.name.like(f"%{req.tag_name.strip()}%"))
        if req.resource_type:
            clauses.append(ReviewTag.resource_type == req.resource_type)
        if req.submitter_id is not None:
            clauses.append(ReviewTag.user_id == req.submitter_id)
        if req.reviewer_id is not None:
            clauses.append(ReviewTag.reviewer_id == req.reviewer_id)
        if req.create_time_start is not None:
            clauses.append(ReviewTag.create_time >= req.create_time_start)
        if req.create_time_end is not None:
            clauses.append(ReviewTag.create_time <= req.create_time_end)
        if req.review_time_start is not None:
            clauses.append(ReviewTag.review_time >= req.review_time_start)
        if req.review_time_end is not None:
            clauses.append(ReviewTag.review_time <= req.review_time_end)
        if req.source_knowledge_id is not None:
            clauses.append(cls._source_space_clause(ReviewTagLink, ReviewTag.id, tenant_id, req.source_knowledge_id))
        return clauses

    async def search_review_tags(
        self,
        req: TagConsoleReviewSearchReq,
        tenant_id: int,
        scope: ReviewTagScope | None,
    ) -> tuple[list[tuple[str, str]], int]:
        """One page of ``(name, resource_type)`` pairs plus the unpaged total.

        Rows are grouped because one tag name produced in several knowledge
        spaces creates one ``review_tag`` row per space, and the whole review
        flow treats that pair as a single unit.

        ``id`` cannot break ties under a GROUP BY, so the order is
        ``MAX(create_time) DESC, name, resource_type`` — the pair itself is
        unique, which makes that a total order and keeps paging stable.
        """
        clauses = self._review_filters(req, tenant_id, scope)

        total_stmt = select(func.count()).select_from(
            select(ReviewTag.name, ReviewTag.resource_type)
            .where(*clauses)
            .group_by(ReviewTag.name, ReviewTag.resource_type)
            .subquery()
        )
        total = await self.session.scalar(total_stmt)

        page_stmt = (
            select(ReviewTag.name, ReviewTag.resource_type)
            .where(*clauses)
            .group_by(ReviewTag.name, ReviewTag.resource_type)
            .order_by(func.max(ReviewTag.create_time).desc(), ReviewTag.name.asc(), ReviewTag.resource_type.asc())
            .offset((req.page - 1) * req.page_size)
            .limit(req.page_size)
        )
        rows = (await self.session.exec(page_stmt)).all()
        return [(name, resource_type) for name, resource_type in rows], int(total or 0)

    # ------------------------------------------------------------------
    # Reviewed mode — approved (from ``tag``) and rejected (from ``review_tag``)
    # ------------------------------------------------------------------

    @classmethod
    def _approved_leg(cls, req: TagConsoleReviewSearchReq, tenant_id: int):
        """Tags that went through review and were approved.

        ``reviewer_id IS NOT NULL`` is the only marker that separates them from
        tags an admin typed straight into a library — both end up as plain rows
        in ``tag`` once approved. Tags approved before F079 added the column have
        no reviewer and therefore cannot appear here; there is nothing to backfill
        them from.

        Scope is tenant-wide rather than department-narrowed, matching library
        mode (AD-12): an approved tag is shared tenant vocabulary and no longer
        belongs to the space that proposed it.
        """
        return select(
            literal(SOURCE_TAG).label("source"),
            Tag.name.label("name"),
            Tag.resource_type.label("resource_type"),
            Tag.review_time.label("sort_time"),
        ).where(*cls._tag_field_filters(req, tenant_id), Tag.reviewer_id.is_not(None))

    @classmethod
    def _rejected_leg(cls, req: TagConsoleReviewSearchReq, tenant_id: int, scope: ReviewTagScope | None):
        scoped = req.model_copy(update={"status": TagConsoleReviewStatus.REJECTED})
        return (
            select(
                literal(SOURCE_REVIEW).label("source"),
                ReviewTag.name.label("name"),
                ReviewTag.resource_type.label("resource_type"),
                func.max(ReviewTag.review_time).label("sort_time"),
            )
            .where(*cls._review_filters(scoped, tenant_id, scope))
            .group_by(ReviewTag.name, ReviewTag.resource_type)
        )

    @classmethod
    def _reviewed_subquery(
        cls,
        req: TagConsoleReviewSearchReq,
        tenant_id: int,
        scope: ReviewTagScope | None,
    ):
        legs = []
        if req.status in (TagConsoleReviewStatus.APPROVED, TagConsoleReviewStatus.REVIEWED):
            legs.append(cls._approved_leg(req, tenant_id))
        if req.status in (TagConsoleReviewStatus.REJECTED, TagConsoleReviewStatus.REVIEWED):
            legs.append(cls._rejected_leg(req, tenant_id, scope))
        combined = legs[0] if len(legs) == 1 else union_all(*legs)
        return combined.subquery()

    async def search_reviewed_tags(
        self,
        req: TagConsoleReviewSearchReq,
        tenant_id: int,
        scope: ReviewTagScope | None,
    ) -> tuple[list[tuple[int, str, str]], int]:
        """One page of ``(source, name, resource_type)`` plus the unpaged total.

        Sorted newest-reviewed first. ``sort_time`` alone repeats and drops rows
        across pages whenever two tags share a review timestamp — a batch approval
        stamps them all with the same value — so the pair itself and finally the
        source table break the tie, which makes the ordering total.
        """
        subquery = self._reviewed_subquery(req, tenant_id, scope)

        total = await self.session.scalar(select(func.count()).select_from(subquery))

        page_stmt = (
            select(subquery.c.source, subquery.c.name, subquery.c.resource_type)
            .order_by(
                subquery.c.sort_time.desc(),
                subquery.c.name.asc(),
                subquery.c.resource_type.asc(),
                subquery.c.source.asc(),
            )
            .offset((req.page - 1) * req.page_size)
            .limit(req.page_size)
        )
        rows = (await self.session.exec(page_stmt)).all()
        return [(int(source), name, resource_type) for source, name, resource_type in rows], int(total or 0)

    async def count_review_by_status(
        self,
        req: TagConsoleReviewSearchReq,
        tenant_id: int,
        scope: ReviewTagScope | None,
    ) -> tuple[int, int, int]:
        """Pending / rejected / approved totals, deliberately ignoring the status
        filter.

        The tab bar shows every number at once, so narrowing them by the status
        the user is currently looking at would make the tabs useless.
        """
        counts = []
        for status in (TagConsoleReviewStatus.PENDING, TagConsoleReviewStatus.REJECTED):
            scoped = req.model_copy(update={"status": status})
            clauses = self._review_filters(scoped, tenant_id, scope)
            statement = select(func.count()).select_from(
                select(ReviewTag.name, ReviewTag.resource_type)
                .where(*clauses)
                .group_by(ReviewTag.name, ReviewTag.resource_type)
                .subquery()
            )
            counts.append(int(await self.session.scalar(statement) or 0))

        approved_req = req.model_copy(update={"status": TagConsoleReviewStatus.APPROVED})
        approved_total = await self.session.scalar(
            select(func.count()).select_from(self._reviewed_subquery(approved_req, tenant_id, scope))
        )
        counts.append(int(approved_total or 0))
        return counts[0], counts[1], counts[2]

    async def load_review_group(
        self,
        pairs: list[tuple[str, str]],
        tenant_id: int,
        scope: ReviewTagScope | None,
    ) -> dict[tuple[str, str], list[ReviewTag]]:
        """All ``review_tag`` rows behind the page's grouped pairs."""
        if not pairs:
            return {}
        names = sorted({name for name, _ in pairs})
        clauses = [
            ReviewTag.tenant_id == tenant_id,
            ReviewTag.name.in_(names),
            or_(
                ReviewTag.review_status == PENDING_STATUS,
                ReviewTag.review_status == REJECTED_STATUS,
            ),
        ]
        scope_clause = self._space_scope_clause(tenant_id, scope)
        if scope_clause is not None:
            clauses.append(scope_clause)
        rows = (await self.session.exec(select(ReviewTag).where(*clauses))).all()
        wanted = set(pairs)
        grouped: dict[tuple[str, str], list[ReviewTag]] = {}
        for row in rows:
            key = (row.name, row.resource_type)
            if key in wanted:
                grouped.setdefault(key, []).append(row)
        return grouped

    async def list_review_source_files(self, tag_ids: list[int], tenant_id: int) -> dict[int, list[int]]:
        """File ids per review_tag.

        ``is_deleted`` is not filtered: rejecting soft-deletes the links, and the
        review panel still has to show which files the tag came from.
        """
        normalized = [int(tag_id) for tag_id in tag_ids if tag_id]
        if not normalized:
            return {}
        statement = select(ReviewTagLink.tag_id, ReviewTagLink.resource_id).where(
            ReviewTagLink.tag_id.in_(normalized),
            ReviewTagLink.tenant_id == tenant_id,
        )
        rows = (await self.session.exec(statement)).all()
        grouped: dict[int, list[int]] = {}
        for tag_id, resource_id in rows:
            if not str(resource_id).isdigit():
                continue
            grouped.setdefault(int(tag_id), []).append(int(resource_id))
        return grouped

    @staticmethod
    def parent_folder_id_from_level_path(file_level_path: str | None) -> int | None:
        """Immediate parent folder id; empty path means the space root.

        Same rule the pending-review listing uses, so the portal deep link opens
        the containing folder before previewing the file.
        """
        folder_ids = [int(part) for part in (file_level_path or "").split("/") if part.isdigit()]
        return folder_ids[-1] if folder_ids else None
