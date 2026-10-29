from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, update
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileProjectionStatus,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.models.knowledge_tag_library_link import KnowledgeTagLibraryLink
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.schemas.knowledge_similarity_context import KnowledgeSimilarityContext
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    commit_tracked_fulltext_changes,
    track_fulltext_file_changes,
)
from bisheng.knowledge.domain.services.uploader_org_names import (
    EMPTY_UPLOADER_ORG,
    path_ids,
    resolve_uploader_org_names,
)

_ABNORMAL_UPLOAD_STATUSES = (
    KnowledgeFileStatus.FAILED.value,
    KnowledgeFileStatus.TIMEOUT.value,
    KnowledgeFileStatus.VIOLATION.value,
)
_SOURCE_SPACE_LEVELS = (
    KnowledgeSpaceLevelEnum.PUBLIC.value,
    KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    KnowledgeSpaceLevelEnum.TEAM.value,
    KnowledgeSpaceLevelEnum.TEAM_KS.value,
    KnowledgeSpaceLevelEnum.PERSONAL.value,
)


def _path_segments(path_column):
    """`/1/2/3/` 这种路径的段数. 斜杠是单字节, MySQL 与 DM8 的 LENGTH 结果一致."""
    return func.length(path_column) - func.length(func.replace(path_column, "/", "")) - 1


def _uploader_org_name_filter(level: str, name: str):
    """上传人组织路径上存在指定层级和名称的有效部门.

    文件没登记 belonging_organization_id 时, 用上传人当前主部门.
    部门没写 org_level 时, 按公司根路径的相对深度判断.
    """
    start = aliased(Department)
    ancestor = aliased(Department)
    primary = aliased(UserDepartment)
    company_path = (
        select(Department.path)
        .where(Department.org_level == "company", Department.status == "active")
        .limit(1)
        .scalar_subquery()
    )
    relative_depth = {"company": 0, "dept": 1, "office": 2}[level]
    return exists(
        select(start.id)
        .select_from(start)
        .outerjoin(
            primary,
            and_(
                KnowledgeFile.belonging_organization_id.is_(None),
                primary.user_id == KnowledgeFile.user_id,
                primary.is_primary == 1,
            ),
        )
        .join(
            ancestor,
            or_(
                ancestor.id == start.id,
                and_(
                    ancestor.path != "",
                    start.path.like(func.concat(ancestor.path, "%")),
                ),
            ),
        )
        .where(
            start.id == func.coalesce(KnowledgeFile.belonging_organization_id, primary.department_id),
            ancestor.name == name,
            ancestor.status == "active",
            or_(
                ancestor.org_level == level,
                and_(
                    or_(ancestor.org_level.is_(None), ancestor.org_level == ""),
                    company_path.is_not(None),
                    ancestor.path.like(func.concat(company_path, "%")),
                    _path_segments(ancestor.path) - _path_segments(company_path) == relative_depth,
                ),
            ),
        )
    )


def _source_upload_filters():
    """源文件: 知识空间、未删除、文件而非文件夹, 入口为空或 manager."""
    return and_(
        KnowledgeFile.deleted_at.is_(None),
        KnowledgeFile.file_type == FileType.FILE.value,
        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        KnowledgeSpaceScope.level.in_(_SOURCE_SPACE_LEVELS),
        or_(
            KnowledgeFile.entry_type.is_(None),
            KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
        ),
    )


class KnowledgeFileRepositoryImpl(BaseRepositoryImpl[KnowledgeFile, int], KnowledgeFileRepository):
    """Knowledge Base Repository Implementation Class"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)
        track_fulltext_file_changes(session)

    async def find_portal_tag_file_ids(self, space_ids: list[int], tag_name: str) -> list[int]:
        ids = sorted({int(item) for item in space_ids if int(item) > 0})
        name = (tag_name or "").strip()
        if not ids or not name:
            return []
        libraries = (
            await self.session.exec(
                select(KnowledgeTagLibraryLink.tag_library_id)
                .where(KnowledgeTagLibraryLink.knowledge_id.in_(ids))
                .distinct()
            )
        ).all()
        conditions = [
            and_(
                Tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
                Tag.business_id.in_([str(item) for item in ids]),
            )
        ]
        if libraries:
            conditions.append(
                and_(
                    Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                    Tag.business_id.in_([str(item) for item in libraries]),
                )
            )
        tag_ids = (await self.session.exec(select(Tag.id).where(Tag.name == name, or_(*conditions)))).all()
        if not tag_ids:
            return []
        resources = (
            await self.session.exec(
                select(TagLink.resource_id)
                .where(
                    TagLink.tag_id.in_(tag_ids),
                    TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                )
                .distinct()
            )
        ).all()
        return sorted({int(item) for item in resources if str(item).isdigit()})

    async def list_qa_subtree_page(
        self, *, space_id: int, prefix: str, after_id: int, limit: int
    ) -> list[KnowledgeFile]:
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == space_id,
                KnowledgeFile.id > after_id,
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                col(KnowledgeFile.deleted_at).is_(None),
                or_(
                    KnowledgeFile.file_level_path == prefix,
                    col(KnowledgeFile.file_level_path).startswith(prefix + "/", autoescape=True),
                ),
            )
            .order_by(KnowledgeFile.id)
            .limit(max(1, min(limit, 500)))
        )
        return list((await self.session.exec(statement)).all())

    async def list_qa_favorite_page(self, *, space_id: int, after_id: int, limit: int) -> list[KnowledgeFile]:
        statement = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_id == space_id,
                KnowledgeFile.id > after_id,
                KnowledgeFile.file_source == "favorite_reference",
                KnowledgeFile.file_type == FileType.FILE.value,
                col(KnowledgeFile.deleted_at).is_(None),
            )
            .order_by(KnowledgeFile.id)
            .limit(max(1, min(limit, 500)))
        )
        return list((await self.session.exec(statement)).all())

    async def list_qa_category_candidates(
        self,
        *,
        space_ids: list[int],
        document_type: str | None,
        file_subcategory_code: str | None,
        before_id: int | None,
        limit: int | None,
    ) -> list[KnowledgeFile]:
        if not space_ids:
            return []
        statement = select(KnowledgeFile).where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            col(KnowledgeFile.deleted_at).is_(None),
            or_(col(KnowledgeFile.file_source).is_(None), KnowledgeFile.file_source != "favorite_reference"),
        )
        if document_type:
            # 编码解析会忽略分段两侧空白, 候选查询也保留这一兼容行为。
            encoding = func.upper(KnowledgeFile.file_encoding)
            for whitespace in (" ", "\t", "\r", "\n"):
                encoding = func.replace(encoding, whitespace, "")
            statement = statement.where(
                encoding.contains(
                    f"-{document_type.strip().upper()}-",
                    autoescape=True,
                )
            )
        if file_subcategory_code:
            statement = statement.where(
                func.upper(func.trim(KnowledgeFile.file_subcategory_code)) == file_subcategory_code.strip().upper()
            )
        if before_id is not None:
            statement = statement.where(KnowledgeFile.id < before_id)
        if limit is not None:
            statement = statement.order_by(col(KnowledgeFile.id).desc()).limit(min(max(limit, 1), 200))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def save(self, entity: KnowledgeFile) -> KnowledgeFile:
        self.session.add(entity)
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_file_repository_saved",
        )
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: KnowledgeFile) -> KnowledgeFile:
        merged = await self.session.merge(entity)
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_file_repository_updated",
        )
        await self.session.refresh(merged)
        return merged

    async def delete(self, entity_id: int) -> bool:
        entity = await self.find_by_id(entity_id)
        if entity is None:
            return False
        await self.session.delete(entity)
        await commit_tracked_fulltext_changes(
            self.session,
            trigger_type="knowledge_file_repository_deleted",
        )
        return True

    async def find_by_ids(self, entity_ids: list[int]) -> Sequence[KnowledgeFile]:
        """Fetch multiple KnowledgeFile rows by id list.

        Overrides the base class to use session.execute() so this impl works
        with both SQLModel AsyncSession and plain SQLAlchemy AsyncSession (tests).
        """
        if not entity_ids:
            return []
        query = select(KnowledgeFile).where(col(KnowledgeFile.id).in_(entity_ids))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_by_id(self, entity_id: int):
        """Fetch a single KnowledgeFile by id.

        Override: bypass SQLAlchemy identity map so reads after bulk UPDATE
        statements return fresh data (matches KnowledgeDocumentRepositoryImpl pattern).
        """
        stmt = select(KnowledgeFile).where(KnowledgeFile.id == entity_id)
        result = await self.session.execute(stmt.execution_options(populate_existing=True))
        return result.scalars().first()

    async def find_by_id_for_update(self, entity_id: int) -> KnowledgeFile | None:
        stmt = (
            select(KnowledgeFile)
            .where(KnowledgeFile.id == entity_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    def _source_upload_select(self):
        return (
            select(KnowledgeFile)
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
        )

    async def list_abnormal_source_uploads(
        self,
        *,
        offset: int,
        limit: int,
        status: int | None = None,
        space_level: str | None = None,
        keyword: str | None = None,
        knowledge_name: str | None = None,
        uploader_name: str | None = None,
        uploader_company: str | None = None,
        uploader_department: str | None = None,
        uploader_office: str | None = None,
        update_time_from: date | None = None,
        update_time_to: date | None = None,
    ) -> tuple[list[dict], int]:
        status_filter = (status,) if status is not None else _ABNORMAL_UPLOAD_STATUSES
        filters = [and_(_source_upload_filters(), KnowledgeFile.status.in_(status_filter))]
        if space_level:
            filters.append(KnowledgeSpaceScope.level == space_level)
        if keyword:
            filters.append(KnowledgeFile.file_name.like(f"%{keyword}%"))
        if knowledge_name:
            filters.append(Knowledge.name.like(f"%{knowledge_name}%"))
        if uploader_name:
            filters.append(KnowledgeFile.user_name.like(f"%{uploader_name}%"))
        if uploader_company:
            filters.append(_uploader_org_name_filter("company", uploader_company))
        if uploader_department:
            filters.append(_uploader_org_name_filter("dept", uploader_department))
        if uploader_office:
            filters.append(_uploader_org_name_filter("office", uploader_office))
        if update_time_from is not None:
            filters.append(KnowledgeFile.update_time >= datetime.combine(update_time_from, time.min))
        if update_time_to is not None:
            filters.append(KnowledgeFile.update_time < datetime.combine(update_time_to + timedelta(days=1), time.min))
        filters = and_(*filters)
        count_stmt = (
            select(func.count(KnowledgeFile.id))
            .select_from(KnowledgeFile)
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
            .where(filters)
        )
        total = int((await self.session.execute(count_stmt)).scalar_one())
        rows = (
            await self.session.execute(
                select(
                    KnowledgeFile.id,
                    KnowledgeFile.file_name,
                    KnowledgeFile.knowledge_id,
                    Knowledge.name,
                    KnowledgeSpaceScope.level,
                    KnowledgeFile.status,
                    KnowledgeFile.user_id,
                    KnowledgeFile.user_name,
                    KnowledgeFile.belonging_organization_id,
                    KnowledgeFile.remark,
                    KnowledgeFile.update_time,
                )
                .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
                .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                .where(filters)
                .order_by(KnowledgeFile.update_time.desc(), KnowledgeFile.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        start_ids = await self._org_start_ids([(row.belonging_organization_id, row.user_id) for row in rows])
        org_names = await self._uploader_org_names_by_id(set(start_ids.values()))
        items = []
        for index, row in enumerate(rows):
            updated = row.update_time
            organization_id = start_ids.get(index, 0)
            items.append(
                {
                    "file_id": int(row.id),
                    "file_name": row.file_name,
                    "knowledge_id": int(row.knowledge_id),
                    "knowledge_name": row.name,
                    "space_level": getattr(row.level, "value", row.level),
                    "status": int(row.status),
                    "uploader_name": row.user_name or "",
                    **org_names.get(organization_id, EMPTY_UPLOADER_ORG),
                    "remark": row.remark or "",
                    "update_time": updated.isoformat() if updated is not None else "",
                }
            )
        return items, total

    async def list_abnormal_uploader_org_options(self) -> dict[str, list[str]]:
        filters = and_(_source_upload_filters(), KnowledgeFile.status.in_(_ABNORMAL_UPLOAD_STATUSES))
        pairs = (
            await self.session.execute(
                select(KnowledgeFile.belonging_organization_id, KnowledgeFile.user_id)
                .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
                .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                .where(filters)
                .distinct()
            )
        ).all()
        start_ids = await self._org_start_ids(pairs)
        org_names = await self._uploader_org_names_by_id(set(start_ids.values()))
        name_rows = (
            await self.session.execute(
                select(Knowledge.name, KnowledgeFile.user_name)
                .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
                .join(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
                .where(filters)
                .distinct()
            )
        ).all()
        companies: set[str] = set()
        departments: set[str] = set()
        offices: set[str] = set()
        knowledges: set[str] = set()
        uploaders: set[str] = set()
        for names in org_names.values():
            if names["company_name"]:
                companies.add(names["company_name"])
            if names["department_name"]:
                departments.add(names["department_name"])
            if names["office_name"]:
                offices.add(names["office_name"])
        for knowledge_name, uploader_name in name_rows:
            if knowledge_name:
                knowledges.add(str(knowledge_name))
            if uploader_name:
                uploaders.add(str(uploader_name))
        return {
            "companies": sorted(companies),
            "departments": sorted(departments),
            "offices": sorted(offices),
            "knowledges": sorted(knowledges),
            "uploaders": sorted(uploaders),
        }

    async def _org_start_ids(self, pairs: list[tuple]) -> dict[int, int]:
        """每行用来拆名称的部门: 文件登记的组织优先, 没有则用上传人唯一主部门."""
        missing_users = {int(user_id) for organization_id, user_id in pairs if not organization_id and user_id}
        primary_by_user = await self._primary_department_ids(missing_users)
        start_ids: dict[int, int] = {}
        for index, (organization_id, user_id) in enumerate(pairs):
            if organization_id:
                start_ids[index] = int(organization_id)
                continue
            department_id = primary_by_user.get(int(user_id or 0))
            if department_id:
                start_ids[index] = department_id
        return start_ids

    async def _primary_department_ids(self, user_ids: set[int]) -> dict[int, int]:
        if not user_ids:
            return {}
        rows = (
            await self.session.execute(
                select(UserDepartment.user_id, UserDepartment.department_id).where(
                    col(UserDepartment.user_id).in_(user_ids),
                    UserDepartment.is_primary == 1,
                )
            )
        ).all()
        grouped: dict[int, list[int]] = {}
        for user_id, department_id in rows:
            grouped.setdefault(int(user_id), []).append(int(department_id))
        return {user_id: departments[0] for user_id, departments in grouped.items() if len(departments) == 1}

    async def _uploader_org_names_by_id(self, organization_ids: set[int]) -> dict[int, dict[str, str]]:
        if not organization_ids:
            return {}
        rows = list(
            (await self.session.execute(select(Department).where(col(Department.id).in_(organization_ids)))).scalars()
        )
        by_id = {int(row.id): row for row in rows if row.id is not None}
        missing = {department_id for row in rows for department_id in path_ids(row.path)} - set(by_id)
        if missing:
            ancestors = (
                await self.session.execute(select(Department).where(col(Department.id).in_(missing)))
            ).scalars()
            for row in ancestors:
                if row.id is not None:
                    by_id[int(row.id)] = row
        company = next(
            (row for row in by_id.values() if str(getattr(row, "org_level", "") or "") == "company"),
            None,
        )
        if company is None:
            company_path = (
                await self.session.execute(
                    select(Department.path)
                    .where(Department.org_level == "company", Department.status == "active")
                    .limit(1)
                )
            ).scalar_one_or_none()
        else:
            company_path = company.path
        return {
            organization_id: resolve_uploader_org_names(
                by_id.get(organization_id),
                by_id,
                company_path,
            )
            for organization_id in organization_ids
        }

    async def lock_abnormal_source_file(self, file_id: int) -> KnowledgeFile | None:
        stmt = (
            self._source_upload_select()
            .where(KnowledgeFile.id == file_id, _source_upload_filters())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def set_parse_priority_if_unset(
        self,
        file_id: int,
        priority: str,
    ) -> KnowledgeFile | None:
        try:
            await self.session.execute(
                update(KnowledgeFile)
                .where(
                    KnowledgeFile.id == file_id,
                    KnowledgeFile.parse_priority.is_(None),
                )
                .values(parse_priority=priority)
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return await self.find_by_id(file_id)

    async def find_by_ids_in_knowledge(
        self,
        entity_ids: list[int],
        knowledge_id: int,
    ) -> list[KnowledgeFile]:
        if not entity_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                col(KnowledgeFile.id).in_(entity_ids),
                KnowledgeFile.knowledge_id == knowledge_id,
            )
        )
        return list(result.scalars().all())

    async def find_by_ids_for_update(
        self,
        entity_ids: list[int],
    ) -> list[KnowledgeFile]:
        if not entity_ids:
            return []
        stmt = (
            select(KnowledgeFile)
            .where(col(KnowledgeFile.id).in_(sorted(set(entity_ids))))
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_favorite_referrers_by_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> list[KnowledgeFile]:
        normalized_ids = {int(file_id) for file_id in source_file_ids if int(file_id) > 0}
        if not normalized_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                KnowledgeFile.file_source == "favorite_reference",
            )
        )
        rows = list(result.scalars().all())
        matched: list[KnowledgeFile] = []
        for row in rows:
            reference = (row.user_metadata or {}).get("favorite_reference") or {}
            try:
                source_file_id = int(reference.get("source_file_id") or 0)
            except (TypeError, ValueError):
                continue
            if source_file_id in normalized_ids:
                matched.append(row)
        return matched

    async def prepare_delete_by_ids(self, entity_ids: list[int]) -> int:
        if not entity_ids:
            return 0
        result = await self.session.execute(delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(entity_ids)))
        await self.session.flush()
        return int(result.rowcount or 0)

    async def find_distribution_entries_by_document_id(
        self,
        document_id: int,
        *,
        statuses: set[str] | None = None,
        for_update: bool = False,
    ) -> list[KnowledgeFile]:
        stmt = (
            select(KnowledgeFile)
            .where(KnowledgeFile.reference_document_id == document_id)
            .order_by(KnowledgeFile.id.asc())
            .execution_options(populate_existing=True)
        )
        if statuses is not None:
            stmt = stmt.where(col(KnowledgeFile.entry_status).in_(sorted(statuses)))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_entries_for_documents(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
        knowledge_ids: list[int],
    ) -> list[KnowledgeFile]:
        normalized_document_ids = sorted({int(d) for d in document_ids if int(d) > 0})
        normalized_knowledge_ids = sorted({int(k) for k in knowledge_ids if int(k) > 0})
        if not normalized_document_ids or not normalized_knowledge_ids:
            return []
        stmt = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                col(KnowledgeFile.reference_document_id).in_(normalized_document_ids),
                KnowledgeFile.knowledge_id.in_(normalized_knowledge_ids),
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.MANAGER.value,
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
            )
            .order_by(KnowledgeFile.reference_document_id.asc(), KnowledgeFile.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_entries_for_documents_any_space(
        self,
        *,
        tenant_id: int,
        document_ids: list[int],
    ) -> list[KnowledgeFile]:
        normalized_document_ids = sorted({int(d) for d in document_ids if int(d) > 0})
        if not normalized_document_ids:
            return []
        stmt = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.tenant_id == int(tenant_id),
                col(KnowledgeFile.reference_document_id).in_(normalized_document_ids),
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.MANAGER.value,
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
            )
            .order_by(KnowledgeFile.reference_document_id.asc(), KnowledgeFile.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_entry_in_space_for_update(
        self,
        document_id: int,
        knowledge_id: int,
        *,
        ignore_deleting_shares: bool = False,
    ) -> KnowledgeFile | None:
        stmt = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == document_id,
                KnowledgeFile.knowledge_id == knowledge_id,
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.PREPARING.value,
                        KnowledgeFileEntryStatus.ACTIVE.value,
                        KnowledgeFileEntryStatus.DELETING.value,
                    ]
                ),
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if ignore_deleting_shares:
            stmt = stmt.where(
                or_(
                    KnowledgeFile.entry_type.is_(None),
                    KnowledgeFile.entry_type != KnowledgeFileEntryType.SHARE.value,
                    KnowledgeFile.entry_status != KnowledgeFileEntryStatus.DELETING.value,
                )
            )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def has_visible_content_in_space(
        self,
        *,
        tenant_id: int,
        knowledge_id: int,
        md5: str,
    ) -> bool:
        if not md5:
            return False

        any_version = select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id
        )
        primary_version = (
            select(KnowledgeDocumentVersion.id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.primary_version_id == KnowledgeDocumentVersion.id,
            )
            .where(
                KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value,
            )
        )
        physical_stmt = (
            select(KnowledgeFile.id)
            .where(
                KnowledgeFile.tenant_id == tenant_id,
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                KnowledgeFile.md5 == md5,
                col(KnowledgeFile.deleted_at).is_(None),
                or_(
                    KnowledgeFile.entry_type.is_(None),
                    and_(
                        KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
                        KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                    ),
                ),
                or_(
                    ~exists(any_version),
                    exists(primary_version),
                ),
            )
            .limit(1)
        )
        physical_result = await self.session.exec(physical_stmt)
        if physical_result.first() is not None:
            return True

        logical_entry = aliased(KnowledgeFile)
        content_file = aliased(KnowledgeFile)
        logical_stmt = (
            select(logical_entry.id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == logical_entry.reference_document_id,
            )
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeDocument.primary_version_id,
            )
            .join(
                content_file,
                content_file.id == KnowledgeDocumentVersion.knowledge_file_id,
            )
            .where(
                logical_entry.tenant_id == tenant_id,
                logical_entry.knowledge_id == knowledge_id,
                col(logical_entry.deleted_at).is_(None),
                col(logical_entry.entry_type).in_(
                    [
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
                logical_entry.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value,
                content_file.tenant_id == tenant_id,
                content_file.file_type == FileType.FILE.value,
                content_file.status == KnowledgeFileStatus.SUCCESS.value,
                content_file.md5 == md5,
                col(content_file.deleted_at).is_(None),
            )
            .limit(1)
        )
        logical_result = await self.session.exec(logical_stmt)
        return logical_result.first() is not None

    async def find_manager_for_update(
        self,
        document_id: int,
    ) -> KnowledgeFile | None:
        stmt = (
            select(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == document_id,
                KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            )
            .order_by(KnowledgeFile.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_approval_instance_id(
        self,
        approval_instance_id: int,
    ) -> KnowledgeFile | None:
        result = await self.session.execute(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.approval_instance_id == approval_instance_id,
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
            )
            .order_by(KnowledgeFile.id.asc())
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def mark_document_entries_content_generation(
        self,
        document_id: int,
        generation: int,
    ) -> int:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.reference_document_id == document_id,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            )
            .values(
                desired_content_generation=generation,
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_retry_count=0,
                projection_next_retry_at=None,
                projection_last_error=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    async def request_projection_checks(self, entry_ids: list[int]) -> int:
        changed = 0
        ids = sorted(set(entry_ids))
        for offset in range(0, len(ids), 500):
            result = await self.session.execute(
                update(KnowledgeFile)
                .where(
                    col(KnowledgeFile.id).in_(ids[offset : offset + 500]),
                    KnowledgeFile.reference_document_id.is_not(None),
                    col(KnowledgeFile.entry_type).in_(["manager", "publish", "share"]),
                    KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                    KnowledgeFile.deleted_at.is_(None),
                    KnowledgeFile.projection_status == KnowledgeFileProjectionStatus.READY.value,
                    KnowledgeFile.projection_lease_owner.is_(None),
                )
                .values(projection_status=KnowledgeFileProjectionStatus.PENDING.value)
            )
            changed += int(result.rowcount or 0)
        await self.session.flush()
        return changed

    async def request_projection_rebuild(self, entry_id: int) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_type).in_(
                    [
                        KnowledgeFileEntryType.MANAGER.value,
                        KnowledgeFileEntryType.PUBLISH.value,
                        KnowledgeFileEntryType.SHARE.value,
                    ]
                ),
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
                col(KnowledgeFile.projection_status).in_(
                    [
                        KnowledgeFileProjectionStatus.READY.value,
                        KnowledgeFileProjectionStatus.FAILED.value,
                    ]
                ),
                KnowledgeFile.projection_lease_owner.is_(None),
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
                projection_lease_owner=None,
                projection_lease_until=None,
                projection_retry_count=0,
                projection_last_error=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    @staticmethod
    def _projection_candidate_predicate(
        now: datetime,
        max_retries: int | None = None,
    ):
        is_distribution_row = or_(
            KnowledgeFile.reference_document_id.is_not(None),
            KnowledgeFile.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        )
        has_work = or_(
            KnowledgeFile.desired_content_generation > KnowledgeFile.applied_content_generation,
            KnowledgeFile.desired_entry_generation > KnowledgeFile.applied_entry_generation,
            col(KnowledgeFile.projection_status).in_(
                [
                    KnowledgeFileProjectionStatus.PENDING.value,
                    KnowledgeFileProjectionStatus.FAILED.value,
                    KnowledgeFileProjectionStatus.PROCESSING.value,
                ]
            ),
            KnowledgeFile.entry_status == KnowledgeFileEntryStatus.DELETING.value,
            KnowledgeFile.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
        )
        retry_due = or_(
            KnowledgeFile.projection_next_retry_at.is_(None),
            KnowledgeFile.projection_next_retry_at <= now,
        )
        lease_available = or_(
            KnowledgeFile.projection_lease_until.is_(None),
            KnowledgeFile.projection_lease_until <= now,
        )
        predicates = [
            is_distribution_row,
            col(KnowledgeFile.entry_status).in_(
                [
                    KnowledgeFileEntryStatus.ACTIVE.value,
                    KnowledgeFileEntryStatus.DELETING.value,
                    KnowledgeFileEntryStatus.INVALID.value,
                ]
            ),
            has_work,
            retry_due,
            lease_available,
        ]
        if max_retries is not None:
            predicates.append(KnowledgeFile.projection_retry_count < max(int(max_retries), 1))
        return and_(*predicates)

    async def find_projection_candidates(
        self,
        *,
        now: datetime,
        limit: int,
        max_retries: int | None = None,
        after_id: int = 0,
    ) -> list[KnowledgeFile]:
        if limit <= 0:
            return []
        result = await self.session.execute(
            select(KnowledgeFile)
            .where(self._projection_candidate_predicate(now, max_retries), KnowledgeFile.id > after_id)
            .order_by(KnowledgeFile.id.asc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def claim_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        max_retries: int | None = None,
    ) -> KnowledgeFile | None:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                self._projection_candidate_predicate(now, max_retries),
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.PROCESSING.value,
                projection_lease_owner=lease_owner,
                projection_lease_until=lease_until,
            )
        )
        await self.session.flush()
        if int(result.rowcount or 0) != 1:
            return None
        return await self.find_by_id(entry_id)

    async def apply_projection_result(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        target_content_generation: int,
        target_entry_generation: int,
        retain_cleanup_lease: bool = False,
    ) -> bool:
        target_is_current = and_(
            KnowledgeFile.desired_content_generation == target_content_generation,
            KnowledgeFile.desired_entry_generation == target_entry_generation,
        )
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.projection_lease_owner == lease_owner,
                KnowledgeFile.applied_content_generation <= target_content_generation,
                KnowledgeFile.applied_entry_generation <= target_entry_generation,
                # 清理不能把旧代次的完成结果用于删除新代次入口。
                target_is_current if retain_cleanup_lease else True,
            )
            .values(
                applied_content_generation=target_content_generation,
                applied_entry_generation=target_entry_generation,
                projection_status=case(
                    (
                        target_is_current,
                        KnowledgeFileProjectionStatus.READY.value,
                    ),
                    else_=KnowledgeFileProjectionStatus.PENDING.value,
                ),
                projection_retry_count=(KnowledgeFile.projection_retry_count if retain_cleanup_lease else 0),
                projection_next_retry_at=None,
                projection_lease_owner=(lease_owner if retain_cleanup_lease else None),
                projection_lease_until=(KnowledgeFile.projection_lease_until if retain_cleanup_lease else None),
                projection_last_error=(KnowledgeFile.projection_last_error if retain_cleanup_lease else None),
                projection_previous_file_id=case(
                    (
                        and_(
                            target_is_current,
                            col(KnowledgeFile.entry_status).in_(
                                [
                                    KnowledgeFileEntryStatus.ACTIVE.value,
                                    KnowledgeFileEntryStatus.INVALID.value,
                                ]
                            ),
                        ),
                        None,
                    ),
                    else_=KnowledgeFile.projection_previous_file_id,
                ),
            )
        )
        await self.session.flush()
        if int(result.rowcount or 0) == 1:
            from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
                KnowledgeBackgroundRepositoryImpl,
            )

            entry = (
                await self.session.exec(
                    select(KnowledgeFile).where(KnowledgeFile.id == entry_id).execution_options(populate_existing=True)
                )
            ).first()
            if entry is not None:
                await self.session.run_sync(
                    lambda sync: KnowledgeBackgroundRepositoryImpl(sync).request_similarity_refresh(entry)
                )
        return int(result.rowcount or 0) == 1

    async def defer_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        next_retry_at: datetime,
        error_summary: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.projection_lease_owner == lease_owner,
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=next_retry_at,
                projection_last_error=error_summary[:4000],
                projection_lease_owner=None,
                projection_lease_until=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def recover_failed_projection(
        self,
        *,
        entry_id: int,
        now: datetime,
        audit_summary: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.ACTIVE.value,
                        KnowledgeFileEntryStatus.DELETING.value,
                        KnowledgeFileEntryStatus.INVALID.value,
                    ]
                ),
                KnowledgeFile.projection_status == KnowledgeFileProjectionStatus.FAILED.value,
                or_(KnowledgeFile.projection_lease_until.is_(None), KnowledgeFile.projection_lease_until <= now),
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_retry_count=0,
                projection_next_retry_at=None,
                projection_lease_owner=None,
                projection_lease_until=None,
                projection_last_error=audit_summary[:4000],
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def fail_projection_lease(
        self,
        *,
        entry_id: int,
        lease_owner: str,
        next_retry_at: datetime,
        error_summary: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.projection_lease_owner == lease_owner,
            )
            .values(
                projection_status=KnowledgeFileProjectionStatus.FAILED.value,
                projection_retry_count=KnowledgeFile.projection_retry_count + 1,
                projection_next_retry_at=next_retry_at,
                projection_lease_owner=None,
                projection_lease_until=None,
                projection_last_error=error_summary[:4000],
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def activate_prepared_entry(self, entry_id: int) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.PREPARING.value,
            )
            .values(
                entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
                desired_entry_generation=(KnowledgeFile.desired_entry_generation + 1),
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def mark_entry_deleting(self, entry_id: int) -> bool:
        result = await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.id == entry_id,
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.PREPARING.value,
                        KnowledgeFileEntryStatus.ACTIVE.value,
                    ]
                ),
            )
            .values(
                entry_status=KnowledgeFileEntryStatus.DELETING.value,
                desired_entry_generation=(KnowledgeFile.desired_entry_generation + 1),
                projection_status=KnowledgeFileProjectionStatus.PENDING.value,
                projection_next_retry_at=None,
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0) == 1

    async def find_permission_reconcile_candidates(
        self,
        *,
        older_than: datetime,
        limit: int,
        after_id: int = 0,
    ) -> list[KnowledgeFile]:
        if limit <= 0:
            return []
        result = await self.session.execute(
            select(KnowledgeFile)
            .where(
                KnowledgeFile.id > after_id,
                KnowledgeFile.reference_document_id.is_not(None),
                col(KnowledgeFile.entry_status).in_(
                    [
                        KnowledgeFileEntryStatus.PREPARING.value,
                        KnowledgeFileEntryStatus.DELETING.value,
                    ]
                ),
                KnowledgeFile.update_time <= older_than,
            )
            .order_by(KnowledgeFile.id.asc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def has_preparing_approval_entries(self, approval_instance_id: int) -> bool:
        result = await self.session.execute(
            select(KnowledgeFile.id)
            .where(
                KnowledgeFile.approval_instance_id == approval_instance_id,
                KnowledgeFile.entry_status == KnowledgeFileEntryStatus.PREPARING.value,
                KnowledgeFile.reference_document_id.is_not(None),
                KnowledgeFile.deleted_at.is_(None),
            )
            .limit(1)
        )
        return result.first() is not None

    async def find_similarity_files_in_space(
        self, knowledge_id: int, exclude_file_id: int | None = None
    ) -> list[KnowledgeFile]:
        primary = await self.find_main_version_files_in_space(knowledge_id, exclude_file_id)
        stmt = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.entry_type == KnowledgeFileEntryType.PUBLISH.value,
            KnowledgeFile.entry_status == KnowledgeFileEntryStatus.ACTIVE.value,
            KnowledgeFile.deleted_at.is_(None),
        )
        if exclude_file_id is not None:
            stmt = stmt.where(KnowledgeFile.id != exclude_file_id)
        published = (await self.session.exec(stmt)).all()
        return sorted({row.id: row for row in [*primary, *published]}.values(), key=lambda row: row.id)

    async def store_similarity_state(self, file_id: int, snapshot: dict | None, has_candidates: bool) -> None:
        current = await self.find_by_id_for_update(file_id)
        if current is None:
            return
        if snapshot is not None:
            current.user_metadata = {**(current.user_metadata or {}), "_similarity_snapshot": snapshot}
        if current.similar_status != 2:
            current.similar_status = 1 if has_candidates else 0
        self.session.add(current)
        await self.session.commit()

    async def resolve_similarity_file(self, file_id: int) -> KnowledgeSimilarityContext | None:
        return (await self.resolve_similarity_files([file_id])).get(file_id)

    async def resolve_similarity_files(self, file_ids: list[int]) -> dict[int, KnowledgeSimilarityContext]:
        if not file_ids:
            return {}
        own_version = aliased(KnowledgeDocumentVersion)
        primary_version = aliased(KnowledgeDocumentVersion)
        content = aliased(KnowledgeFile)
        stmt = (
            select(KnowledgeFile, KnowledgeDocument, primary_version, content)
            .outerjoin(own_version, own_version.knowledge_file_id == KnowledgeFile.id)
            .outerjoin(
                KnowledgeDocument,
                KnowledgeDocument.id
                == case(
                    (KnowledgeFile.reference_document_id.is_not(None), KnowledgeFile.reference_document_id),
                    else_=own_version.document_id,
                ),
            )
            .outerjoin(primary_version, primary_version.id == KnowledgeDocument.primary_version_id)
            .outerjoin(content, content.id == primary_version.knowledge_file_id)
            .where(KnowledgeFile.id.in_(file_ids))
            .execution_options(populate_existing=True)
        )
        contexts = {}
        for entry, document, version, body in (await self.session.execute(stmt)).all():
            if document is None and entry.reference_document_id is None and entry.entry_type is None:
                body = entry
            contexts[entry.id] = KnowledgeSimilarityContext(
                *(
                    type(item)(**item.model_dump()) if item is not None else None
                    for item in (entry, document, version, body)
                )
            )
        return contexts

    async def find_main_version_files_in_space(
        self,
        knowledge_id: int,
        exclude_file_id: int | None = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS files in a space that are the primary version of their logical document.

        Joins KnowledgeDocumentVersion to filter only rows where is_primary=True,
        then applies the SUCCESS status filter. Optionally excludes a single file
        (used to skip the file currently being scanned from its own results).
        """
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

        stmt = (
            select(KnowledgeFile)
            .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id)
            .where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                KnowledgeFile.file_type == 1,  # FILE
                KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
            )
        )
        if exclude_file_id is not None:
            stmt = stmt.where(KnowledgeFile.id != exclude_file_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_success_files_in_space(
        self,
        knowledge_id: int,
        exclude_file_id: int | None = None,
    ) -> list[KnowledgeFile]:
        """Parsed-SUCCESS physical files in a space, including files without a version document."""
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

        stmt = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            KnowledgeFile.file_type == 1,
        )
        if exclude_file_id is not None:
            stmt = stmt.where(KnowledgeFile.id != exclude_file_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_file_sync_folders_by_ids(
        self,
        folder_ids: set[int],
    ) -> list[KnowledgeFile]:
        if not folder_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                col(KnowledgeFile.id).in_(folder_ids),
                KnowledgeFile.file_type == FileType.DIR.value,
            )
        )
        return list(result.scalars().all())

    async def find_file_sync_folder_candidates(
        self,
        *,
        space_ids: set[int],
    ) -> list[KnowledgeFile]:
        if not space_ids:
            return []
        result = await self.session.execute(
            select(KnowledgeFile).where(
                col(KnowledgeFile.knowledge_id).in_(space_ids),
                KnowledgeFile.file_type == FileType.DIR.value,
            )
        )
        return list(result.scalars().all())

    async def list_file_sync_direct_children(
        self,
        *,
        knowledge_id: int,
        parent_path: str,
        visible_folder_ids: set[int] | None,
        after: tuple[str, int] | None,
        limit: int,
    ) -> list[KnowledgeFile]:
        if visible_folder_ids is not None and not visible_folder_ids:
            return []
        stmt = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == FileType.DIR.value,
            KnowledgeFile.file_level_path == parent_path,
        )
        if visible_folder_ids is not None:
            stmt = stmt.where(col(KnowledgeFile.id).in_(visible_folder_ids))
        if after is not None:
            after_name, after_id = after
            stmt = stmt.where(
                or_(
                    KnowledgeFile.file_name > after_name,
                    and_(
                        KnowledgeFile.file_name == after_name,
                        KnowledgeFile.id > after_id,
                    ),
                )
            )
        result = await self.session.execute(
            stmt.order_by(KnowledgeFile.file_name.asc(), KnowledgeFile.id.asc()).limit(limit)
        )
        return list(result.scalars().all())

    async def find_file_sync_space_ids_with_folders(
        self,
        *,
        space_ids: set[int],
        visible_folder_ids: set[int] | None,
    ) -> set[int]:
        if not space_ids or (visible_folder_ids is not None and not visible_folder_ids):
            return set()
        stmt = select(KnowledgeFile.knowledge_id).where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == FileType.DIR.value,
        )
        if visible_folder_ids is not None:
            stmt = stmt.where(col(KnowledgeFile.id).in_(visible_folder_ids))
        result = await self.session.execute(stmt.distinct())
        return {int(value) for value in result.scalars().all()}

    async def find_file_sync_parent_paths_with_children(
        self,
        *,
        knowledge_id: int,
        parent_paths: set[str],
        visible_folder_ids: set[int] | None,
    ) -> set[str]:
        if not parent_paths or (visible_folder_ids is not None and not visible_folder_ids):
            return set()
        stmt = select(KnowledgeFile.file_level_path).where(
            KnowledgeFile.knowledge_id == knowledge_id,
            KnowledgeFile.file_type == FileType.DIR.value,
            col(KnowledgeFile.file_level_path).in_(parent_paths),
        )
        if visible_folder_ids is not None:
            stmt = stmt.where(col(KnowledgeFile.id).in_(visible_folder_ids))
        result = await self.session.execute(stmt.distinct())
        return {str(value or "") for value in result.scalars().all()}

    # according knowledge_idAndknowledge_file_ids Dapatkanuser_metadata Data field
    async def get_user_metadata_by_knowledge_file_ids(
        self, knowledge_id: int, knowledge_file_ids: list[int]
    ) -> dict[int | None, list[dict[str, Any]] | None]:
        query = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == knowledge_id, col(KnowledgeFile.id).in_(knowledge_file_ids)
        )

        result = await self.session.exec(query)

        knowledge_files = result.all()

        user_metadata_dict = {}

        for knowledge_file in knowledge_files:
            if knowledge_file.user_metadata:
                # Sort by newness
                sorted_user_metadata = dict(
                    sorted(
                        knowledge_file.user_metadata.items(),
                        key=lambda item: item[1].get("updated_at", 0),
                        reverse=False,
                    )
                )
                user_metadata_dict[knowledge_file.id] = sorted_user_metadata
            else:
                user_metadata_dict[knowledge_file.id] = {}

        return user_metadata_dict
