"""前台按本地或第三方课程过滤目录和课程列表."""

from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CatalogCreate,
    CourseCreate,
)
from bisheng.shougang_portal_course.domain.services.catalog_service import (
    PortalCourseCatalogService,
)
from bisheng.shougang_portal_course.domain.services.course_service import PortalCourseService


def _names(nodes) -> list[str]:
    found: list[str] = []
    for node in nodes:
        found.append(node.name)
        found.extend(_names(node.children or []))
    return found


async def test_course_type_limits_catalog_nav_and_course_list(course_session):
    """本地和第三方各自只看到有已启用课程的目录, 上级目录仍保留.

    Args:
        course_session: 课程模块的 sqlite 会话.
    """
    catalog_service = PortalCourseCatalogService(course_session)
    course_service = PortalCourseService(course_session)
    finance = await catalog_service.create_catalog(
        tenant_id=1,
        user_id=7,
        payload=CatalogCreate(name="财务"),
    )
    report = await catalog_service.create_catalog(
        tenant_id=1,
        user_id=7,
        payload=CatalogCreate(name="报表", parent_id=finance.id),
    )
    safety = await catalog_service.create_catalog(
        tenant_id=1,
        user_id=7,
        payload=CatalogCreate(name="安全"),
    )
    await catalog_service.create_catalog(
        tenant_id=1,
        user_id=7,
        payload=CatalogCreate(name="空目录"),
    )
    await course_service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(
            name="云学堂报表",
            catalog_id=report.id,
            course_type="external",
            external_url="https://example.com/report",
            enabled=True,
        ),
    )
    local_course = await course_service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="本地安全", catalog_id=safety.id),
    )
    local_course.enabled = True
    await course_service.repository.add(local_course)

    external_nav = await catalog_service.list_course_list_nav(
        tenant_id=1,
        course_type="external",
    )
    local_nav = await catalog_service.list_course_list_nav(
        tenant_id=1,
        course_type="local",
    )
    all_nav = await catalog_service.list_course_list_nav(tenant_id=1)

    assert _names(external_nav) == ["财务", "报表"]
    assert _names(local_nav) == ["安全"]
    assert "空目录" in _names(all_nav)

    finance_ids = await catalog_service.resolve_catalog_ids(
        tenant_id=1,
        catalog_id=finance.id,
        include_descendants=True,
        public_only=False,
    )
    external_courses = await course_service.list_read_models(
        tenant_id=1,
        public_only=True,
        catalog_ids=finance_ids,
        course_type="external",
    )
    local_in_finance = await course_service.list_read_models(
        tenant_id=1,
        public_only=True,
        catalog_ids=finance_ids,
        course_type="local",
    )

    assert [item.name for item in external_courses] == ["云学堂报表"]
    assert local_in_finance == []
