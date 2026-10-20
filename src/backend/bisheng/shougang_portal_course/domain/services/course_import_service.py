"""把在线课堂导出表写入课程目录和第三方课程."""

from __future__ import annotations

import logging
from datetime import datetime

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseCatalog,
)
from bisheng.shougang_portal_course.domain.repositories.catalog_repository import (
    PortalCourseCatalogRepository,
)
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CatalogCreate,
    CourseImportPreview,
    CourseImportResult,
)
from bisheng.shougang_portal_course.domain.services.catalog_service import PortalCourseCatalogService
from bisheng.shougang_portal_course.domain.services.course_service import serialize_tags
from bisheng.shougang_portal_course.domain.services.yunxuetang_course_sheet import (
    ParsedCourseRow,
    build_template,
    catalog_node_count,
    parse_workbook,
)

logger = logging.getLogger(__name__)

CatalogCache = dict[tuple[str | None, str], PortalCourseCatalog]


class PortalCourseImportService:
    """按在线课堂表同时保存目录和第三方课程."""

    def __init__(self, session):
        self.session = session
        self.catalog_repository = PortalCourseCatalogRepository(session)
        self.catalog_service = PortalCourseCatalogService(session)
        self.course_repository = PortalCourseRepository(session)

    @staticmethod
    def build_template() -> bytes:
        """生成在线课堂空表.

        Returns:
            只含表头的 xlsx 字节.
        """
        return build_template()

    async def preview_excel(self, *, tenant_id: int, content: bytes) -> CourseImportPreview:
        """预检在线课堂表, 不写库.

        Args:
            tenant_id: 当前租户. 预检不读目录, 保留该参数以便和导入接口一致.
            content: xlsx 文件字节.

        Returns:
            数据行数, 可导入课程数, 将确保的目录节点数, 以及失败行.
        """
        del tenant_id
        rows, issues, total = parse_workbook(content)
        return CourseImportPreview(
            total=total,
            valid=len(rows),
            catalog_count=catalog_node_count(rows),
            issues=issues,
        )

    async def import_excel(
        self,
        *,
        tenant_id: int,
        user_id: int,
        content: bytes,
        force: bool = False,
    ) -> CourseImportResult:
        """把在线课堂表中的有效行写入目录和课程.

        Args:
            tenant_id: 当前租户.
            user_id: 操作人.
            content: xlsx 文件字节.
            force: 兼容旧前端的查询参数. 无效行会跳过, 不再把课程改到未分类.

        Returns:
            数据行数, 成功课程行数, 失败行数, 失败原因, 以及成功行确保的目录节点数.

        Raises:
            PortalCourseImportError: 整表无法解析, 表头不对, 或超过 2000 行.
        """
        del force
        rows, issues, total = parse_workbook(content)
        errors = [issue.message for issue in issues]
        failed = len(issues)
        cache = await self._catalog_cache(tenant_id)
        ready: list[tuple[ParsedCourseRow, str]] = []
        for row in rows:
            try:
                async with self.session.begin_nested():
                    leaf, overlay = await self._ensure_catalog_path(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        names=row.catalog_names,
                        cache=cache,
                    )
            except Exception as exc:
                self._log_row_failure(tenant_id, row.row_idx, exc)
                errors.append(self._row_error_message(row.row_idx, exc))
                failed += 1
                continue
            cache = overlay
            ready.append((row, leaf.id))
        await self._write_courses(
            tenant_id=tenant_id,
            user_id=user_id,
            ready=ready,
        )
        return CourseImportResult(
            total=total,
            success=len(ready),
            failed=failed,
            errors=errors,
            catalog_count=catalog_node_count([row for row, _catalog_id in ready]),
        )

    async def _catalog_cache(self, tenant_id: int) -> CatalogCache:
        catalogs = await self.catalog_repository.list_catalogs(tenant_id=tenant_id)
        cache: CatalogCache = {}
        for item in catalogs:
            cache.setdefault((item.parent_id, item.name), item)
        return cache

    async def _ensure_catalog_path(
        self,
        *,
        tenant_id: int,
        user_id: int,
        names: list[str],
        cache: CatalogCache,
    ) -> tuple[PortalCourseCatalog, CatalogCache]:
        """按从根到叶的名称复用或新建目录.

        已有的同父同名目录不改公开和排序. 新建目录公开, 排序为 0.

        Args:
            tenant_id: 当前租户.
            user_id: 操作人.
            names: 从根到叶的目录名称.
            cache: 已有的同父同名目录.

        Returns:
            叶子目录, 以及包含本次新建目录的缓存.
        """
        overlay = dict(cache)
        parent_id: str | None = None
        leaf: PortalCourseCatalog | None = None
        for name in names:
            key = (parent_id, name)
            current = overlay.get(key)
            if current is None:
                current = await self.catalog_service.create_catalog(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    payload=CatalogCreate(
                        name=name,
                        parent_id=parent_id,
                        order_index=0,
                        opened=True,
                    ),
                )
                overlay[key] = current
            parent_id = current.id
            leaf = current
        if leaf is None:
            raise ValueError("目录路径为空")
        return leaf, overlay

    async def _write_courses(
        self,
        *,
        tenant_id: int,
        user_id: int,
        ready: list[tuple[ParsedCourseRow, str]],
    ) -> None:
        """按平台课程编号批量新增或更新课程.

        同一文件里编号重复时, 后面的行覆盖前面的映射字段. 已有课程不改封面,
        首页展示, 排序和所属单位.

        Args:
            tenant_id: 当前租户.
            user_id: 操作人, 只写入新课程.
            ready: 目录已确保的行和叶子目录 id.
        """
        if not ready:
            return
        existing = await self.course_repository.list_by_external_ids(
            tenant_id=tenant_id,
            external_ids=[row.external_id for row, _catalog_id in ready],
        )
        by_external = {
            course.external_id: course
            for course in existing
            if course.external_id
        }
        pending_new: dict[str, PortalCourse] = {}
        now = datetime.now()
        for row, catalog_id in ready:
            current = by_external.get(row.external_id)
            if current is None:
                current = PortalCourse(
                    tenant_id=tenant_id,
                    cover_url="",
                    organization="",
                    show_on_home=True,
                    sort_order=0,
                    create_user=user_id,
                    create_time=now,
                )
                pending_new[row.external_id] = current
                by_external[row.external_id] = current
            self._apply_mapped_fields(current, row, catalog_id, now)
        if pending_new:
            self.session.add_all(list(pending_new.values()))
        await self.session.flush()

    @staticmethod
    def _apply_mapped_fields(
        course: PortalCourse,
        row: ParsedCourseRow,
        catalog_id: str,
        now: datetime,
    ) -> None:
        """写入导入映射字段.

        Args:
            course: 新课程或已有课程.
            row: 已通过校验的表格行.
            catalog_id: 该行叶子目录.
            now: 本次导入的更新时间.
        """
        course.name = row.name
        course.instructor = row.instructor
        course.description = row.description
        course.tags_json = serialize_tags(row.tags)
        course.enabled = bool(row.external_url)
        course.catalog_id = catalog_id
        course.course_type = "external"
        course.external_url = row.external_url
        course.external_id = row.external_id
        course.source_updated_at = row.source_updated_at
        course.duration_seconds = row.duration_seconds
        course.update_time = now

    @staticmethod
    def _log_row_failure(tenant_id: int, row_idx: int, exc: Exception) -> None:
        if isinstance(exc, (BaseErrorCode, ValueError)):
            logger.warning(
                "portal course import row skipped tenant_id=%s row=%s error_type=%s",
                tenant_id,
                row_idx,
                type(exc).__name__,
            )
            return
        logger.exception(
            "portal course import row failed tenant_id=%s row=%s",
            tenant_id,
            row_idx,
        )

    @staticmethod
    def _row_error_message(row_idx: int, exc: Exception) -> str:
        if isinstance(exc, BaseErrorCode):
            return f"第 {row_idx} 行: {exc.message}"
        if isinstance(exc, ValueError):
            return f"第 {row_idx} 行: {exc}"
        return f"第 {row_idx} 行: 保存失败"
