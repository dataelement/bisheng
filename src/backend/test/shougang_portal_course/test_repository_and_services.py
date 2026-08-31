from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.portal_course import (
    PortalCourseExternalUrlRequiredError,
    PortalCourseNotFoundError,
    PortalCourseNotPublishableError,
    PortalCourseSourceInvalidError,
    PortalCourseVideoNotSupportedError,
)
from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseVideo,
)
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CourseBatchDelete,
    CourseCreate,
    CourseTag,
    CourseUpdate,
    ProgressUpdate,
    UrlVideoCreate,
    VideoUpdate,
)
from bisheng.shougang_portal_course.domain.services.course_service import (
    PortalCourseService,
)
from bisheng.shougang_portal_course.domain.services.progress_service import (
    PortalCourseProgressService,
)


def test_course_schemas_normalize_tags_and_reject_invalid_urls():
    payload = CourseCreate(
        name="  高炉安全  ",
        tags=[
            {"label": " 炼铁 ", "display_type": "domain"},
            {"label": " 初级 ", "display_type": "level"},
        ],
    )
    assert payload.name == "高炉安全"
    assert [tag.label for tag in payload.tags] == ["炼铁", "初级"]

    with pytest.raises(ValidationError):
        CourseTag(label="危险", display_type="script")
    with pytest.raises(ValidationError):
        UrlVideoCreate(
            title="非法",
            source_url="javascript:alert(1)",
            duration_seconds=10,
        )
    with pytest.raises(ValidationError):
        UrlVideoCreate(
            title="凭据",
            source_url="https://user:pass@example.com/video.mp4",
            duration_seconds=10,
        )
    with pytest.raises(ValidationError):
        CourseCreate(
            name="外链课",
            course_type="external",
            external_url="javascript:alert(1)",
        )


async def test_repository_filters_tenant_and_uses_stable_admin_order(course_session):
    now = datetime.now()
    course_session.add_all(
        [
            PortalCourse(
                id="a" * 32,
                tenant_id=1,
                name="后创建",
                tags_json='[{"label":"A","display_type":"gray"}]',
                sort_order=3,
                create_user=1,
                create_time=now,
            ),
            PortalCourse(
                id="b" * 32,
                tenant_id=1,
                name="先创建",
                tags_json="[]",
                sort_order=3,
                create_user=1,
                create_time=now - timedelta(seconds=1),
            ),
            PortalCourse(
                id="c" * 32,
                tenant_id=2,
                name="其他租户",
                tags_json="[]",
                sort_order=0,
                create_user=2,
                create_time=now + timedelta(seconds=1),
            ),
        ]
    )
    await course_session.commit()

    repository = PortalCourseRepository(course_session)
    courses = await repository.list_courses(tenant_id=1, public_only=False)

    assert [course.id for course in courses] == ["a" * 32, "b" * 32]
    assert courses[0].tags_json.startswith('[{"label":"A"')


async def test_repository_searches_name_description_instructor_and_tags(course_session):
    course_session.add_all(
        [
            PortalCourse(
                id="a" * 32,
                tenant_id=1,
                name="高炉安全",
                instructor="张三",
                description="工艺培训",
                tags_json='[{"label":"炼钢","display_type":"domain"}]',
                create_user=1,
            ),
            PortalCourse(
                id="b" * 32,
                tenant_id=1,
                name="消防演练",
                instructor="李四",
                description="灭火器使用",
                tags_json="[]",
                create_user=1,
            ),
            PortalCourse(
                id="c" * 32,
                tenant_id=1,
                name="其他课程",
                instructor="",
                description="",
                tags_json="[]",
                create_user=1,
            ),
        ]
    )
    await course_session.commit()
    repository = PortalCourseRepository(course_session)

    by_name = await repository.list_courses(tenant_id=1, public_only=False, keyword="高炉")
    by_instructor = await repository.list_courses(tenant_id=1, public_only=False, keyword="张三")
    by_description = await repository.list_courses(tenant_id=1, public_only=False, keyword="灭火器")
    by_tag = await repository.list_courses(tenant_id=1, public_only=False, keyword="炼钢")

    assert [course.id for course in by_name] == ["a" * 32]
    assert [course.id for course in by_instructor] == ["a" * 32]
    assert [course.id for course in by_description] == ["b" * 32]
    assert [course.id for course in by_tag] == ["a" * 32]


async def test_course_publish_and_last_playable_video_are_guarded(course_session):
    service = PortalCourseService(course_session)
    course = await service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="安全课"),
    )

    with pytest.raises(PortalCourseNotPublishableError):
        await service.update_course(
            tenant_id=1,
            course_id=course.id,
            payload=CourseUpdate(
                name="安全课",
                enabled=True,
            ),
        )

    video = await service.create_url_video(
        tenant_id=1,
        course_id=course.id,
        payload=UrlVideoCreate(
            title="第一讲",
            source_url="https://media.example.com/lesson.mp4",
            duration_seconds=120,
            enabled=True,
        ),
    )
    updated = await service.update_course(
        tenant_id=1,
        course_id=course.id,
        payload=CourseUpdate(name="安全课", enabled=True),
    )
    assert updated.enabled is True

    with pytest.raises(PortalCourseNotPublishableError):
        await service.update_video(
            tenant_id=1,
            video_id=video.id,
            payload=VideoUpdate(title="第一讲", enabled=False, sort_order=0),
        )


async def test_external_course_publishes_with_url_and_rejects_videos(course_session):
    service = PortalCourseService(course_session)
    with pytest.raises(PortalCourseExternalUrlRequiredError):
        await service.create_course(
            tenant_id=1,
            user_id=7,
            payload=CourseCreate(
                name="云学堂课程",
                course_type="external",
                enabled=True,
            ),
        )

    course = await service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="云学堂课程", course_type="external"),
    )
    assert course.enabled is False
    assert course.course_type == "external"

    with pytest.raises(PortalCourseExternalUrlRequiredError):
        await service.update_course(
            tenant_id=1,
            course_id=course.id,
            payload=CourseUpdate(enabled=True),
        )

    published = await service.update_course(
        tenant_id=1,
        course_id=course.id,
        payload=CourseUpdate(
            enabled=True,
            external_url="https://learn.example.com/course/42",
        ),
    )
    assert published.enabled is True
    assert published.course_type == "external"
    assert published.external_url == "https://learn.example.com/course/42"

    with pytest.raises(PortalCourseVideoNotSupportedError):
        await service.create_url_video(
            tenant_id=1,
            course_id=course.id,
            payload=UrlVideoCreate(
                title="不应添加",
                source_url="https://media.example.com/lesson.mp4",
                duration_seconds=120,
                enabled=True,
            ),
        )

    local = await service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="本地课"),
    )
    await service.create_url_video(
        tenant_id=1,
        course_id=local.id,
        payload=UrlVideoCreate(
            title="第一讲",
            source_url="https://media.example.com/lesson.mp4",
            duration_seconds=120,
            enabled=True,
        ),
    )
    with pytest.raises(PortalCourseVideoNotSupportedError):
        await service.update_course(
            tenant_id=1,
            course_id=local.id,
            payload=CourseUpdate(course_type="external"),
        )


async def test_batch_delete_removes_courses_and_rejects_missing(course_session):
    service = PortalCourseService(course_session)
    first = await service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="第一课"),
    )
    second = await service.create_course(
        tenant_id=1,
        user_id=7,
        payload=CourseCreate(name="第二课"),
    )
    with pytest.raises(ValidationError):
        CourseBatchDelete(ids=[first.id, first.id])
    with pytest.raises(ValidationError):
        CourseBatchDelete(ids=[])

    await service.delete_courses(tenant_id=1, course_ids=[first.id, second.id])
    remaining = await PortalCourseRepository(course_session).list_courses(
        tenant_id=1,
        public_only=False,
    )
    assert remaining == []

    with pytest.raises(PortalCourseNotFoundError):
        await service.delete_courses(tenant_id=1, course_ids=["a" * 32])


async def test_update_video_does_not_convert_constructed_null_duration_to_zero(
    course_session,
):
    course = PortalCourse(
        tenant_id=1,
        name="已发布课程",
        enabled=True,
        create_user=1,
    )
    video = PortalCourseVideo(
        tenant_id=1,
        course_id=course.id,
        title="第一讲",
        source_type="url",
        source_url="https://media.example.com/lesson.mp4",
        duration_seconds=120,
        enabled=True,
    )
    course_session.add_all([course, video])
    await course_session.commit()

    service = PortalCourseService(course_session)
    invalid_payload = VideoUpdate.model_construct(duration_seconds=None)

    with pytest.raises(PortalCourseSourceInvalidError):
        await service.update_video(
            tenant_id=1,
            video_id=video.id,
            payload=invalid_payload,
        )

    assert video.duration_seconds == 120


async def test_progress_allows_rewind_then_freezes_after_completion(course_session):
    course = PortalCourse(
        tenant_id=1,
        name="进度课",
        enabled=True,
        create_user=1,
    )
    course_session.add(course)
    await course_session.flush()
    video = PortalCourseVideo(
        tenant_id=1,
        course_id=course.id,
        title="视频",
        source_type="url",
        source_url="https://media.example.com/lesson.mp4",
        duration_seconds=100,
        enabled=True,
    )
    course_session.add(video)
    await course_session.commit()

    service = PortalCourseProgressService(course_session)
    first = await service.report(
        tenant_id=1,
        user_id=9,
        video_id=video.id,
        payload=ProgressUpdate(progress_seconds=80, completed=False),
    )
    rewound = await service.report(
        tenant_id=1,
        user_id=9,
        video_id=video.id,
        payload=ProgressUpdate(progress_seconds=20, completed=False),
    )
    completed = await service.report(
        tenant_id=1,
        user_id=9,
        video_id=video.id,
        payload=ProgressUpdate(progress_seconds=99, completed=True),
    )
    completed_at = completed.completed_at
    frozen_update_time = completed.updated_at
    ignored = await service.report(
        tenant_id=1,
        user_id=9,
        video_id=video.id,
        payload=ProgressUpdate(progress_seconds=1, completed=False),
    )

    assert first.progress_seconds == 80
    assert rewound.progress_seconds == 20
    assert completed.progress_seconds == 100
    assert ignored.completed is True
    assert ignored.progress_seconds == 100
    assert ignored.completed_at == completed_at
    assert ignored.updated_at == frozen_update_time
