"""Queries backing the F079 tag management console.

Library mode reads ``tag``; review mode (added later) reads ``review_tag``. The
two never get merged into one result set — the console switches between them
from the left panel, so each side pages independently and neither needs a
cross-table UNION.
"""

from sqlalchemy import Integer, cast, exists, or_
from sqlmodel import delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.review_tags import ApproveOrRejectEnum, ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_tag_library import KnowledgeSpaceTagLibrary
from bisheng.workstation.domain.schemas.tag_console_schema import (
    TagConsoleReviewSearchReq,
    TagConsoleReviewStatus,
    TagConsoleSearchReq,
)

PENDING_STATUS = 0
REJECTED_STATUS = ApproveOrRejectEnum.REJECT.value


class TagConsoleRepositoryImpl:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Library mode — approved tags
    # ------------------------------------------------------------------

    @staticmethod
    def _library_tag_filters(req: TagConsoleSearchReq, tenant_id: int) -> list:
        """Where-clauses shared by the page query and its COUNT.

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
        if req.library_ids:
            # Unknown ids simply match nothing — a library another admin deleted
            # must not turn the request into an error.
            clauses.append(Tag.business_id.in_([str(library_id) for library_id in req.library_ids]))
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
        ).where(
            KnowledgeFile.id.in_(normalized),
            KnowledgeFile.tenant_id == tenant_id,
        )
        rows = (await self.session.exec(statement)).all()
        return {
            int(file_id): {
                "file_id": int(file_id),
                "file_name": file_name or "",
                "knowledge_id": int(knowledge_id) if knowledge_id is not None else 0,
                "parent_id": self.parent_folder_id_from_level_path(file_level_path),
            }
            for file_id, file_name, knowledge_id, file_level_path in rows
        }

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
    def _space_scope_clause(cls, tenant_id: int, space_ids: set[int] | None):
        """Department-admin scope, mirroring the pending-review listing.

        Unlike library mode, review-mode rows *do* have per-space provenance, so
        this narrowing is meaningful here (AC-38).
        """
        if space_ids is None:
            return None
        if not space_ids:
            return ReviewTag.id == -1  # empty managed set matches nothing
        space_id_list = sorted(int(space_id) for space_id in space_ids)
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
        return or_(business_match, link_match)

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
        return or_(pending, rejected)

    @classmethod
    def _review_filters(cls, req: TagConsoleReviewSearchReq, tenant_id: int, space_ids: set[int] | None) -> list:
        clauses = [ReviewTag.tenant_id == tenant_id, cls._status_clause(req.status, tenant_id)]
        scope_clause = cls._space_scope_clause(tenant_id, space_ids)
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
        return clauses

    async def search_review_tags(
        self,
        req: TagConsoleReviewSearchReq,
        tenant_id: int,
        space_ids: set[int] | None,
    ) -> tuple[list[tuple[str, str]], int]:
        """One page of ``(name, resource_type)`` pairs plus the unpaged total.

        Rows are grouped because one tag name produced in several knowledge
        spaces creates one ``review_tag`` row per space, and the whole review
        flow treats that pair as a single unit.

        ``id`` cannot break ties under a GROUP BY, so the order is
        ``MAX(create_time) DESC, name, resource_type`` — the pair itself is
        unique, which makes that a total order and keeps paging stable.
        """
        clauses = self._review_filters(req, tenant_id, space_ids)

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

    async def count_review_by_status(
        self,
        req: TagConsoleReviewSearchReq,
        tenant_id: int,
        space_ids: set[int] | None,
    ) -> tuple[int, int]:
        """Pending / rejected totals that deliberately ignore the status filter.

        The toolbar shows both numbers at once, so narrowing them by the status
        the user is currently looking at would make the heading useless.
        """
        counts = []
        for status in (TagConsoleReviewStatus.PENDING, TagConsoleReviewStatus.REJECTED):
            scoped = req.model_copy(update={"status": status})
            clauses = self._review_filters(scoped, tenant_id, space_ids)
            statement = select(func.count()).select_from(
                select(ReviewTag.name, ReviewTag.resource_type)
                .where(*clauses)
                .group_by(ReviewTag.name, ReviewTag.resource_type)
                .subquery()
            )
            counts.append(int(await self.session.scalar(statement) or 0))
        return counts[0], counts[1]

    async def load_review_group(
        self,
        pairs: list[tuple[str, str]],
        tenant_id: int,
        space_ids: set[int] | None,
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
        scope_clause = self._space_scope_clause(tenant_id, space_ids)
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
