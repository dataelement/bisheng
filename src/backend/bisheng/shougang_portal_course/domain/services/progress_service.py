from __future__ import annotations

from datetime import datetime

from bisheng.common.errcode.portal_course import (
    PortalCourseNotFoundError,
    PortalCourseVideoNotFoundError,
)
from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourseVideoProgress,
)
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    ProgressRead,
    ProgressUpdate,
)


def _progress_read(progress: PortalCourseVideoProgress) -> ProgressRead:
    return ProgressRead(
        video_id=progress.video_id,
        progress_seconds=progress.progress_seconds,
        completed=progress.completed,
        completed_at=progress.completed_at,
        updated_at=progress.update_time,
    )


class PortalCourseProgressService:
    """Stores one rewritable progress row until completion becomes final."""

    def __init__(self, session):
        self.repository = PortalCourseRepository(session)

    async def report(
        self,
        *,
        tenant_id: int,
        user_id: int,
        video_id: str,
        payload: ProgressUpdate,
    ) -> ProgressRead:
        video = await self.repository.get_video(
            tenant_id=tenant_id,
            video_id=video_id,
            public_only=True,
            for_update=True,
        )
        if video is None:
            raise PortalCourseVideoNotFoundError()
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=video.course_id,
            public_only=True,
            for_update=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()

        progress = await self.repository.get_progress(
            tenant_id=tenant_id,
            user_id=user_id,
            video_id=video_id,
            for_update=True,
        )
        if progress is not None and progress.completed:
            return _progress_read(progress)

        now = datetime.now()
        value = max(0, min(round(payload.progress_seconds), video.duration_seconds))
        if progress is None:
            progress = PortalCourseVideoProgress(
                tenant_id=tenant_id,
                user_id=user_id,
                video_id=video_id,
                progress_seconds=0,
                completed=False,
            )
        if payload.completed:
            progress.progress_seconds = video.duration_seconds
            progress.completed = True
            progress.completed_at = now
        else:
            progress.progress_seconds = value
        progress.update_time = now
        await self.repository.add(progress)
        return _progress_read(progress)

    async def get_course_progress(
        self,
        *,
        tenant_id: int,
        user_id: int,
        course_id: str,
    ) -> list[ProgressRead]:
        course = await self.repository.get_course(
            tenant_id=tenant_id,
            course_id=course_id,
            public_only=True,
        )
        if course is None:
            raise PortalCourseNotFoundError()
        videos = await self.repository.list_videos(
            tenant_id=tenant_id,
            course_id=course_id,
            public_only=True,
        )
        stored = {
            item.video_id: item
            for item in await self.repository.list_progress_for_course(
                tenant_id=tenant_id,
                user_id=user_id,
                course_id=course_id,
            )
        }
        result: list[ProgressRead] = []
        for video in videos:
            progress = stored.get(video.id)
            if progress is None:
                result.append(
                    ProgressRead(
                        video_id=video.id,
                        progress_seconds=0,
                        completed=False,
                    )
                )
                continue
            read = _progress_read(progress)
            read.progress_seconds = min(read.progress_seconds, video.duration_seconds)
            result.append(read)
        return result
