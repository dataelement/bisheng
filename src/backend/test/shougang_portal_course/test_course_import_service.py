from __future__ import annotations

import importlib
from datetime import datetime
from io import BytesIO

import openpyxl
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy import inspect as sa_inspect

from bisheng.common.errcode.portal_course import PortalCourseImportError
from bisheng.shougang_portal_course.domain.models.portal_course import PortalCourseVideo
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CourseCreate,
    CourseUpdate,
)
from bisheng.shougang_portal_course.domain.services.catalog_service import PortalCourseCatalogService
from bisheng.shougang_portal_course.domain.services.course_import_service import (
    PortalCourseImportService,
)
from bisheng.shougang_portal_course.domain.services.course_service import PortalCourseService
from bisheng.shougang_portal_course.domain.services.yunxuetang_course_sheet import (
    REQUIRED_HEADERS,
    SHEET_NAME,
    TEMPLATE_HEADERS,
    parse_workbook,
)


def _workbook(rows: list[dict]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    for col, header in enumerate(TEMPLATE_HEADERS, start=1):
        sheet.cell(row=1, column=col, value=header)
    for row_idx, row in enumerate(rows, start=2):
        for col, header in enumerate(TEMPLATE_HEADERS, start=1):
            if header in row:
                sheet.cell(row=row_idx, column=col, value=row[header])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _course(**overrides) -> dict:
    row = {
        "课件名称": "备件采购方式与定价谈判",
        "全路径": "内部知识->运营管控->财务管理类",
        "分类名称": "财务管理类",
        "主讲老师": "吴铮",
        "标准时长": "30分0秒",
        "平台课程编号": "ZXKT2026091100010",
        "分享链接": "https://short-phx-ali.yunxuetang.cn/h11pil44i",
        "课程简介": "采购谈判要点",
        "更新日期": "2026-09-11 09:06:08",
        "标签": "采购,谈判",
    }
    row.update(overrides)
    return row


def test_template_headers_match_online_classroom_export():
    workbook = openpyxl.load_workbook(BytesIO(PortalCourseImportService.build_template()))
    sheet = workbook[SHEET_NAME]
    headers = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
    assert tuple(headers) == TEMPLATE_HEADERS
    assert all(name in headers for name in REQUIRED_HEADERS)
    assert workbook.sheetnames == [SHEET_NAME]
    workbook.close()


def test_old_course_template_is_rejected():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "第三方课程"
    for col, header in enumerate(["课程ID", "课程名称", "主讲人"], start=1):
        sheet.cell(row=1, column=col, value=header)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    with pytest.raises(PortalCourseImportError, match="表头必须包含"):
        parse_workbook(output.getvalue())


async def test_import_creates_catalog_tree_and_course(course_session):
    service = PortalCourseImportService(course_session)
    content = _workbook([_course()])
    preview = await service.preview_excel(tenant_id=1, content=content)
    assert preview.total == 1
    assert preview.valid == 1
    assert preview.catalog_count == 3
    assert preview.issues == []

    result = await service.import_excel(tenant_id=1, user_id=7, content=content)
    assert result.success == 1
    assert result.failed == 0
    assert result.catalog_count == 3

    courses = await PortalCourseService(course_session).repository.list_courses(
        tenant_id=1,
        public_only=False,
    )
    assert len(courses) == 1
    course = courses[0]
    assert course.course_type == "external"
    assert course.external_id == "ZXKT2026091100010"
    assert course.name == "备件采购方式与定价谈判"
    assert course.instructor == "吴铮"
    assert course.description == "采购谈判要点"
    assert course.duration_seconds == 1800
    assert course.external_url.startswith("https://short-phx-ali.yunxuetang.cn/")
    assert course.enabled is True
    assert course.show_on_home is True
    assert course.cover_url == ""
    assert course.source_updated_at == datetime(2026, 9, 11, 9, 6, 8)
    assert "采购" in course.tags_json

    catalogs = await PortalCourseCatalogService(course_session).repository.list_catalogs(tenant_id=1)
    by_name = {item.name: item for item in catalogs}
    leaf = by_name["财务管理类"]
    middle = by_name["运营管控"]
    root = by_name["内部知识"]
    assert course.catalog_id == leaf.id
    assert leaf.parent_id == middle.id
    assert middle.parent_id == root.id
    assert root.parent_id is None
    assert leaf.opened is True
    assert leaf.order_index == 0
    assert leaf.catalog_name_path == "内部知识->运营管控->财务管理类"

    read_model = await PortalCourseService(course_session).get_read_model(
        tenant_id=1,
        course_id=course.id,
        public_only=False,
    )
    assert read_model.total_duration_seconds == 1800
    assert read_model.source_updated_at == datetime(2026, 9, 11, 9, 6, 8)


async def test_reimport_updates_mapped_fields_and_keeps_manual_settings(course_session):
    service = PortalCourseImportService(course_session)
    await service.import_excel(tenant_id=1, user_id=7, content=_workbook([_course()]))
    course_service = PortalCourseService(course_session)
    courses = await course_service.repository.list_courses(tenant_id=1, public_only=False)
    await course_service.update_course(
        tenant_id=1,
        course_id=courses[0].id,
        payload=CourseUpdate(
            show_on_home=False,
            sort_order=6,
            organization="首钢股份",
            cover_url="https://example.com/cover.jpg",
        ),
    )
    catalog = await PortalCourseCatalogService(course_session).repository.get_catalog(
        tenant_id=1,
        catalog_id=courses[0].catalog_id,
    )
    catalog.opened = False
    catalog.order_index = 9
    await PortalCourseCatalogService(course_session).repository.add(catalog)

    updated = await service.import_excel(
        tenant_id=1,
        user_id=7,
        content=_workbook(
            [
                _course(
                    课件名称="采购谈判进阶",
                    主讲老师="--",
                    标准时长="1时2分3秒",
                    课程简介="",
                    标签="--",
                    更新日期="2026-09-12 15:45:04",
                )
            ]
        ),
    )
    assert updated.success == 1
    assert updated.failed == 0
    courses = await course_service.repository.list_courses(tenant_id=1, public_only=False)
    assert len(courses) == 1
    course = courses[0]
    assert course.name == "采购谈判进阶"
    assert course.instructor == ""
    assert course.description == ""
    assert course.tags_json == "[]"
    assert course.duration_seconds == 3723
    assert course.source_updated_at == datetime(2026, 9, 12, 15, 45, 4)
    assert course.show_on_home is False
    assert course.sort_order == 6
    assert course.organization == "首钢股份"
    assert course.cover_url == "https://example.com/cover.jpg"
    refreshed = await PortalCourseCatalogService(course_session).repository.get_catalog(
        tenant_id=1,
        catalog_id=course.catalog_id,
    )
    assert refreshed.opened is False
    assert refreshed.order_index == 9
    catalogs = await PortalCourseCatalogService(course_session).repository.list_catalogs(tenant_id=1)
    assert len(catalogs) == 3


async def test_invalid_row_does_not_create_partial_catalog(course_session):
    service = PortalCourseImportService(course_session)
    result = await service.import_excel(
        tenant_id=1,
        user_id=7,
        content=_workbook(
            [
                _course(分类名称="不会建出来", 平台课程编号="ZXKT-BAD"),
                _course(平台课程编号="ZXKT-OK", 分享链接=""),
            ]
        ),
    )
    assert result.success == 1
    assert result.failed == 1
    assert any("分类名称必须与全路径最后一级一致" in item for item in result.errors)
    courses = await PortalCourseService(course_session).repository.list_courses(
        tenant_id=1,
        public_only=False,
    )
    assert len(courses) == 1
    assert courses[0].external_id == "ZXKT-OK"
    assert courses[0].enabled is False
    catalogs = await PortalCourseCatalogService(course_session).repository.list_catalogs(tenant_id=1)
    assert {item.name for item in catalogs} == {"内部知识", "运营管控", "财务管理类"}


async def test_duplicate_external_id_in_one_file_keeps_the_later_row(course_session):
    service = PortalCourseImportService(course_session)
    result = await service.import_excel(
        tenant_id=1,
        user_id=7,
        content=_workbook(
            [
                _course(课件名称="第一稿", 平台课程编号="ZXKT-DUP"),
                _course(课件名称="第二稿", 平台课程编号="ZXKT-DUP"),
            ]
        ),
    )
    assert result.success == 2
    courses = await PortalCourseService(course_session).repository.list_courses(
        tenant_id=1,
        public_only=False,
    )
    assert len(courses) == 1
    assert courses[0].name == "第二稿"


async def test_blank_duration_and_bad_url_fail_without_writing(course_session):
    service = PortalCourseImportService(course_session)
    result = await service.import_excel(
        tenant_id=1,
        user_id=7,
        content=_workbook(
            [
                _course(平台课程编号="ZXKT-DURATION", 标准时长="--"),
                _course(平台课程编号="ZXKT-URL", 分享链接="ftp://files.example.com/a"),
            ]
        ),
    )
    assert result.success == 0
    assert result.failed == 2
    courses = await PortalCourseService(course_session).repository.list_courses(
        tenant_id=1,
        public_only=False,
    )
    catalogs = await PortalCourseCatalogService(course_session).repository.list_catalogs(tenant_id=1)
    assert courses == []
    assert catalogs == []


async def test_local_course_duration_still_sums_enabled_videos(course_session):
    course_service = PortalCourseService(course_session)
    course = await course_service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="本地课", course_type="local"),
    )
    course.duration_seconds = 999
    await course_service.repository.add(course)
    await course_service.repository.add(
        PortalCourseVideo(
            tenant_id=1,
            course_id=course.id,
            title="第一节",
            source_type="url",
            source_url="https://example.com/a.mp4",
            duration_seconds=95,
            enabled=True,
            sort_order=0,
        )
    )
    read_model = await course_service.get_read_model(
        tenant_id=1,
        course_id=course.id,
        public_only=False,
    )
    assert read_model.total_duration_seconds == 95


def test_f117_migration_adds_duration_seconds_with_chinese_comment():
    migration = importlib.import_module(
        "bisheng.core.database.alembic.versions.v2_6_0_f117_portal_course_duration_seconds"
    )
    assert migration.revision == "f117_portal_course_duration_seconds"
    assert migration.down_revision == "f116_knowledge_violation_deduct"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE portal_course (id CHAR(32) PRIMARY KEY, tenant_id INTEGER NOT NULL)"
        )
        original_op = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            migration.upgrade()
            columns = {item["name"]: item for item in sa_inspect(connection).get_columns("portal_course")}
            assert "duration_seconds" in columns
            assert columns["duration_seconds"]["nullable"] is False
            migration.downgrade()
            columns = {item["name"] for item in sa_inspect(connection).get_columns("portal_course")}
            assert "duration_seconds" not in columns
        finally:
            migration.op = original_op
    engine.dispose()
    assert "课程时长秒数" in importlib.import_module(
        "bisheng.core.database.alembic.versions.v2_6_0_f117_portal_course_duration_seconds"
    )._COMMENT
