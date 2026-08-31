from __future__ import annotations

import json
from datetime import datetime

from bisheng.common.errcode.portal_course import (
    PortalCourseCatalogNotFoundError,
    PortalCourseExternalUrlRequiredError,
    PortalCourseNotFoundError,
    PortalCourseNotPublishableError,
    PortalCourseSourceInvalidError,
    PortalCourseVideoNotFoundError,
    PortalCourseVideoNotSupportedError,
)
from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseCatalog,
    PortalCourseVideo,
)
from bisheng.shougang_portal_course.domain.repositories.catalog_repository import (
    PortalCourseCatalogRepository,
)
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CourseCreate,
    CourseRead,
    CourseTag,
    CourseUpdate,
    OrderUpdate,
    UrlVideoCreate,
    VideoRead,
    VideoUpdate,
)
from bisheng.shougang_portal_course.domain.services.media_service import UploadedMedia


def serialize_tags(tags: list[CourseTag]) -> str:
    return json.dumps(
        [tag.model_dump(mode="json") for tag in tags],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def deserialize_tags(value: str) -> list[CourseTag]:
    try:
        raw = json.loads(value or "[]")
    except (TypeError, ValueError):
        raw = []
    return [CourseTag.model_validate(item) for item in raw]


class PortalCourseService:
    """Enforces course publication and video lifecycle invariants."""

    def __init__(self, session):
        self.repository = PortalCourseRepository(session)
        self.catalog_repository = PortalCourseCatalogRepository(session)

    async def create_course(
        self,
        *,
        tenant_id: int,
        user_id: int,
        payload: CourseCreate,
    ) -> PortalCourse:
        if payload.enabled:
            if payload.course_type == "external":
                if not payload.external_url:
                    raise PortalCourseExternalUrlRequiredError()
            else:
                raise PortalCourseNotPublishableError()
        catalog_id = await self._validated_catalog_id(
            tenant_id=tenant_id,
            catalog_id=payload.catalog_id,
        )
        course = PortalCourse(
            tenant_id=tenant_id,
            catalog_id=catalog_id,
            course_type=payload.course_type,
            external_url=payload.external_url if payload.course_type == "external" else "",
            external_id=payload.external_id if payload.course_type == "external" else None,
            cover_url=payload.cover_url or "",
            source_updated_at=payload.source_updated_at,
            name=payload.name,
            instructor=payload.instructor,
            organization=payload.organization,
            description=payload.description,
            tags_json=serialize_tags(payload.tags),
            enabled=bool(payload.enabled and payload.course_type == "external" and payload.external_url),
            show_on_home=payload.show_on_home,
            sort_order=payload.sort_order,
            create_user=user_id,
        )
        await self.repository.add(course)
        return course

    async def update_course(
        self,
        *,
        tenant_id: int,
        course_id: str,
        payload: CourseUpdate,
    ) -> PortalCourse:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()

        fields = payload.model_fields_set
        next_type = payload.course_type if "course_type" in fields else self._course_type(course)
        next_url = course.external_url or ""
        if next_type == "local":
            next_url = ""
        elif "external_url" in fields:
            next_url = payload.external_url or ""

        if next_type == "external" and self._course_type(course) != "external":
            videos = await self.repository.list_videos(
                tenant_id=tenant_id,
                course_id=course_id,
            )
            if videos:
                raise PortalCourseVideoNotSupportedError()

        next_enabled = payload.enabled if "enabled" in fields else course.enabled
        if next_enabled:
            await self._assert_publishable(
                tenant_id=tenant_id,
                course_id=course_id,
                course_type=next_type,
                external_url=next_url,
            )

        for field in (
            "name",
            "instructor",
            "organization",
            "description",
            "enabled",
            "show_on_home",
            "sort_order",
        ):
            if field in fields:
                setattr(course, field, getattr(payload, field))
        if "catalog_id" in fields:
            course.catalog_id = await self._validated_catalog_id(
                tenant_id=tenant_id,
                catalog_id=payload.catalog_id,
            )
        if "tags" in fields and payload.tags is not None:
            course.tags_json = serialize_tags(payload.tags)
        if "external_id" in fields:
            course.external_id = payload.external_id if next_type == "external" else None
        if "cover_url" in fields:
            course.cover_url = payload.cover_url or ""
        if "source_updated_at" in fields:
            course.source_updated_at = payload.source_updated_at
        if next_type != "external":
            course.external_id = None
        course.course_type = next_type
        course.external_url = next_url
        course.update_time = datetime.now()
        await self.repository.add(course)
        return course

    async def create_url_video(
        self,
        *,
        tenant_id: int,
        course_id: str,
        payload: UrlVideoCreate,
    ) -> PortalCourseVideo:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        self._reject_videos_on_external(course)
        video = PortalCourseVideo(
            tenant_id=tenant_id,
            course_id=course_id,
            title=payload.title,
            source_type="url",
            source_url=payload.source_url,
            duration_seconds=payload.duration_seconds,
            enabled=payload.enabled,
            sort_order=payload.sort_order,
        )
        await self.repository.add(video)
        return video

    async def update_video(
        self,
        *,
        tenant_id: int,
        video_id: str,
        payload: VideoUpdate,
    ) -> PortalCourseVideo:
        video = await self.repository.get_video(
            tenant_id=tenant_id,
            video_id=video_id,
            for_update=True,
        )
        if video is None:
            raise PortalCourseVideoNotFoundError()
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=video.course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        if video.enabled and payload.enabled is False and course.enabled:
            playable = await self.repository.count_playable_videos(
                tenant_id=tenant_id,
                course_id=video.course_id,
            )
            if playable <= 1:
                raise PortalCourseNotPublishableError()
        fields = payload.model_fields_set
        for field in ("title", "enabled", "sort_order"):
            if field in fields:
                setattr(video, field, getattr(payload, field))
        if "duration_seconds" in fields and video.source_type == "url":
            if payload.duration_seconds is None:
                raise PortalCourseSourceInvalidError()
            video.duration_seconds = payload.duration_seconds
        video.update_time = datetime.now()
        await self.repository.add(video)
        return video

    async def create_uploaded_video(
        self,
        *,
        tenant_id: int,
        course_id: str,
        title: str,
        enabled: bool,
        sort_order: int,
        video_id: str,
        uploaded: UploadedMedia,
    ) -> PortalCourseVideo:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        self._reject_videos_on_external(course)
        video = PortalCourseVideo(
            id=video_id,
            tenant_id=tenant_id,
            course_id=course_id,
            title=title.strip(),
            source_type="upload",
            object_name=uploaded.object_name,
            original_filename=uploaded.original_filename,
            duration_seconds=uploaded.duration_seconds,
            enabled=enabled,
            sort_order=sort_order,
        )
        await self.repository.add(video)
        if uploaded.provisional_job_id:
            await self.repository.cancel_cleanup_job(
                tenant_id=tenant_id,
                job_id=uploaded.provisional_job_id,
            )
        return video

    async def replace_video_url(
        self,
        *,
        tenant_id: int,
        video_id: str,
        payload: UrlVideoCreate,
    ) -> tuple[PortalCourseVideo, list[str]]:
        video = await self.repository.get_video(
            tenant_id=tenant_id,
            video_id=video_id,
            for_update=True,
        )
        if video is None:
            raise PortalCourseVideoNotFoundError()
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=video.course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        if video.enabled and payload.enabled is False and course.enabled:
            playable = await self.repository.count_playable_videos(
                tenant_id=tenant_id,
                course_id=video.course_id,
            )
            if playable <= 1:
                raise PortalCourseNotPublishableError()

        cleanup_jobs: list[str] = []
        source_changed = video.source_type != "url" or video.source_url != payload.source_url
        if source_changed:
            await self.repository.delete_progress_by_video(
                tenant_id=tenant_id,
                video_id=video_id,
            )
            if video.source_type == "upload" and video.object_name:
                job = await self.repository.create_cleanup_job(
                    tenant_id=tenant_id,
                    object_name=video.object_name,
                    reason="replace",
                    not_before=datetime.now(),
                )
                cleanup_jobs.append(job.id)
        video.title = payload.title
        video.source_type = "url"
        video.source_url = payload.source_url
        video.object_name = None
        video.original_filename = None
        video.duration_seconds = payload.duration_seconds
        video.enabled = payload.enabled
        video.sort_order = payload.sort_order
        video.update_time = datetime.now()
        await self.repository.add(video)
        return video, cleanup_jobs

    async def replace_video_upload(
        self,
        *,
        tenant_id: int,
        video_id: str,
        title: str,
        enabled: bool,
        sort_order: int,
        uploaded: UploadedMedia,
    ) -> tuple[PortalCourseVideo, list[str]]:
        video = await self.repository.get_video(
            tenant_id=tenant_id,
            video_id=video_id,
            for_update=True,
        )
        if video is None:
            raise PortalCourseVideoNotFoundError()
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=video.course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        if video.enabled and not enabled and course.enabled:
            playable = await self.repository.count_playable_videos(
                tenant_id=tenant_id,
                course_id=video.course_id,
            )
            if playable <= 1:
                raise PortalCourseNotPublishableError()

        await self.repository.delete_progress_by_video(
            tenant_id=tenant_id,
            video_id=video_id,
        )
        cleanup_jobs: list[str] = []
        if video.source_type == "upload" and video.object_name:
            job = await self.repository.create_cleanup_job(
                tenant_id=tenant_id,
                object_name=video.object_name,
                reason="replace",
                not_before=datetime.now(),
            )
            cleanup_jobs.append(job.id)
        video.title = title.strip()
        video.source_type = "upload"
        video.source_url = None
        video.object_name = uploaded.object_name
        video.original_filename = uploaded.original_filename
        video.duration_seconds = uploaded.duration_seconds
        video.enabled = enabled
        video.sort_order = sort_order
        video.update_time = datetime.now()
        await self.repository.add(video)
        if uploaded.provisional_job_id:
            await self.repository.cancel_cleanup_job(
                tenant_id=tenant_id,
                job_id=uploaded.provisional_job_id,
            )
        return video, cleanup_jobs

    async def delete_video(self, *, tenant_id: int, video_id: str) -> list[str]:
        video = await self.repository.get_video(
            tenant_id=tenant_id,
            video_id=video_id,
            for_update=True,
        )
        if video is None:
            raise PortalCourseVideoNotFoundError()
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=video.course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        if course.enabled and video.enabled:
            playable = await self.repository.count_playable_videos(
                tenant_id=tenant_id,
                course_id=video.course_id,
            )
            if playable <= 1:
                raise PortalCourseNotPublishableError()
        cleanup_jobs: list[str] = []
        if video.source_type == "upload" and video.object_name:
            job = await self.repository.create_cleanup_job(
                tenant_id=tenant_id,
                object_name=video.object_name,
                reason="delete",
                not_before=datetime.now(),
            )
            cleanup_jobs.append(job.id)
        await self.repository.delete_video(tenant_id=tenant_id, video_id=video_id)
        return cleanup_jobs

    async def delete_course(self, *, tenant_id: int, course_id: str) -> list[str]:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        videos = await self.repository.list_videos(
            tenant_id=tenant_id,
            course_id=course_id,
        )
        cleanup_jobs: list[str] = []
        for video in videos:
            if video.source_type == "upload" and video.object_name:
                job = await self.repository.create_cleanup_job(
                    tenant_id=tenant_id,
                    object_name=video.object_name,
                    reason="delete",
                    not_before=datetime.now(),
                )
                cleanup_jobs.append(job.id)
        await self.repository.delete_course(tenant_id=tenant_id, course_id=course_id)
        return cleanup_jobs

    async def delete_courses(self, *, tenant_id: int, course_ids: list[str]) -> list[str]:
        cleanup_jobs: list[str] = []
        for course_id in course_ids:
            cleanup_jobs.extend(
                await self.delete_course(tenant_id=tenant_id, course_id=course_id)
            )
        return cleanup_jobs

    async def update_course_order(self, *, tenant_id: int, payload: OrderUpdate) -> None:
        for item in payload.items:
            course = await self.repository.get_course(
                tenant_id=tenant_id,
                course_id=item.id,
                for_update=True,
            )
            if course is None:
                raise PortalCourseNotFoundError()
            course.sort_order = item.sort_order
            course.update_time = datetime.now()
            await self.repository.add(course)

    async def update_video_order(
        self,
        *,
        tenant_id: int,
        course_id: str,
        payload: OrderUpdate,
    ) -> None:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        self._reject_videos_on_external(course)
        for item in payload.items:
            video = await self.repository.get_video(
                tenant_id=tenant_id,
                video_id=item.id,
                for_update=True,
            )
            if video is None or video.course_id != course_id:
                raise PortalCourseVideoNotFoundError()
            video.sort_order = item.sort_order
            video.update_time = datetime.now()
            await self.repository.add(video)

    async def list_read_models(
        self,
        *,
        tenant_id: int,
        public_only: bool,
        home_only: bool = False,
        media_service=None,
        include_videos: bool = False,
        catalog_ids: list[str] | None = None,
        keyword: str | None = None,
    ) -> list[CourseRead]:
        courses = await self.repository.list_courses(
            tenant_id=tenant_id,
            public_only=public_only,
            home_only=home_only,
            catalog_ids=catalog_ids,
            keyword=keyword,
        )
        catalog_map = await self._catalog_map(
            tenant_id=tenant_id,
            catalog_ids=[course.catalog_id for course in courses if course.catalog_id],
        )
        return [
            await self._to_read(
                course,
                tenant_id=tenant_id,
                public_only=public_only,
                media_service=media_service,
                include_videos=include_videos,
                catalog=catalog_map.get(course.catalog_id) if course.catalog_id else None,
            )
            for course in courses
        ]

    async def get_read_model(
        self,
        *,
        tenant_id: int,
        course_id: str,
        public_only: bool,
        media_service=None,
    ) -> CourseRead:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            public_only=public_only,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        catalog = None
        if course.catalog_id:
            catalog = await self.catalog_repository.get_catalog(
                tenant_id=tenant_id,
                catalog_id=course.catalog_id,
                include_deleted=True,
            )
        return await self._to_read(
            course,
            tenant_id=tenant_id,
            public_only=public_only,
            media_service=media_service,
            include_videos=True,
            catalog=catalog,
        )

    async def _validated_catalog_id(
        self,
        *,
        tenant_id: int,
        catalog_id: str | None,
    ) -> str | None:
        if not catalog_id:
            return None
        catalog = await self.catalog_repository.get_catalog(
            tenant_id=tenant_id,
            catalog_id=catalog_id,
        )
        if catalog is None:
            raise PortalCourseCatalogNotFoundError()
        return catalog.id

    async def _catalog_map(
        self,
        *,
        tenant_id: int,
        catalog_ids: list[str],
    ) -> dict[str, PortalCourseCatalog]:
        unique_ids = list(dict.fromkeys(catalog_ids))
        result: dict[str, PortalCourseCatalog] = {}
        for catalog_id in unique_ids:
            catalog = await self.catalog_repository.get_catalog(
                tenant_id=tenant_id,
                catalog_id=catalog_id,
                include_deleted=True,
            )
            if catalog is not None:
                result[catalog.id] = catalog
        return result

    async def _to_read(
        self,
        course: PortalCourse,
        *,
        tenant_id: int,
        public_only: bool,
        media_service,
        include_videos: bool,
        catalog: PortalCourseCatalog | None = None,
    ) -> CourseRead:
        videos = await self.repository.list_videos(
            tenant_id=tenant_id,
            course_id=course.id,
            public_only=public_only,
        )
        video_reads: list[VideoRead] = []
        if include_videos:
            for video in videos:
                play_url = video.source_url or ""
                if video.source_type == "upload" and video.object_name:
                    if media_service is None:
                        play_url = ""
                    else:
                        play_url = await media_service.get_play_url(video.object_name)
                video_reads.append(
                    VideoRead(
                        id=video.id,
                        title=video.title,
                        source_type=video.source_type,
                        play_url=play_url,
                        duration_seconds=video.duration_seconds,
                        enabled=None if public_only else video.enabled,
                        sort_order=video.sort_order,
                        created_at=video.create_time,
                        updated_at=video.update_time,
                        source_url=None if public_only else video.source_url,
                        original_filename=None if public_only else video.original_filename,
                    )
                )
        return CourseRead(
            id=course.id,
            name=course.name,
            tags=deserialize_tags(course.tags_json),
            instructor=course.instructor,
            organization=course.organization,
            description=course.description,
            total_duration_seconds=sum(video.duration_seconds for video in videos if video.enabled),
            video_count=len(videos),
            sort_order=course.sort_order,
            created_at=course.create_time,
            updated_at=course.update_time,
            enabled=None if public_only else course.enabled,
            show_on_home=None if public_only else course.show_on_home,
            catalog_id=course.catalog_id,
            catalog_name=None if catalog is None else catalog.name,
            catalog_name_path=None if catalog is None else catalog.catalog_name_path,
            course_type=self._course_type(course),
            external_url=course.external_url or None,
            external_id=course.external_id,
            cover_url=course.cover_url or None,
            source_updated_at=course.source_updated_at,
            videos=video_reads if include_videos else None,
        )

    @staticmethod
    def _course_type(course: PortalCourse) -> str:
        if course.course_type == "external":
            return "external"
        return "local"

    @classmethod
    def _reject_videos_on_external(cls, course: PortalCourse) -> None:
        if cls._course_type(course) == "external":
            raise PortalCourseVideoNotSupportedError()

    async def _assert_publishable(
        self,
        *,
        tenant_id: int,
        course_id: str,
        course_type: str,
        external_url: str,
    ) -> None:
        if course_type == "external":
            if not (external_url or "").strip():
                raise PortalCourseExternalUrlRequiredError()
            return
        playable = await self.repository.count_playable_videos(
            tenant_id=tenant_id,
            course_id=course_id,
        )
        if playable < 1:
            raise PortalCourseNotPublishableError()
