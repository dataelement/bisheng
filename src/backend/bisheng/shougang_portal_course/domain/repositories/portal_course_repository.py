from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseMediaCleanup,
    PortalCourseVideo,
    PortalCourseVideoProgress,
)


class PortalCourseRepository:
    """Transaction-scoped persistence operations for the course aggregate."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_courses(
        self,
        *,
        tenant_id: int,
        public_only: bool,
        home_only: bool = False,
    ) -> list[PortalCourse]:
        statement = select(PortalCourse).where(PortalCourse.tenant_id == tenant_id)
        if public_only:
            statement = statement.where(PortalCourse.enabled.is_(True))
            if home_only:
                statement = statement.where(PortalCourse.show_on_home.is_(True))
        statement = statement.order_by(
            PortalCourse.sort_order.asc(),
            PortalCourse.create_time.desc(),
            PortalCourse.id.asc(),
        )
        return list((await self.session.exec(statement)).all())

    async def get_course(
        self,
        *,
        tenant_id: int,
        course_id: str,
        public_only: bool = False,
        for_update: bool = False,
    ) -> PortalCourse | None:
        statement = select(PortalCourse).where(
            PortalCourse.tenant_id == tenant_id,
            PortalCourse.id == course_id,
        )
        if public_only:
            statement = statement.where(PortalCourse.enabled.is_(True))
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def list_videos(
        self,
        *,
        tenant_id: int,
        course_id: str,
        public_only: bool = False,
    ) -> list[PortalCourseVideo]:
        statement = select(PortalCourseVideo).where(
            PortalCourseVideo.tenant_id == tenant_id,
            PortalCourseVideo.course_id == course_id,
        )
        if public_only:
            statement = statement.where(PortalCourseVideo.enabled.is_(True))
        statement = statement.order_by(
            PortalCourseVideo.sort_order.asc(),
            PortalCourseVideo.create_time.asc(),
            PortalCourseVideo.id.asc(),
        )
        return list((await self.session.exec(statement)).all())

    async def get_video(
        self,
        *,
        tenant_id: int,
        video_id: str,
        public_only: bool = False,
        for_update: bool = False,
    ) -> PortalCourseVideo | None:
        statement = select(PortalCourseVideo).where(
            PortalCourseVideo.tenant_id == tenant_id,
            PortalCourseVideo.id == video_id,
        )
        if public_only:
            statement = statement.where(PortalCourseVideo.enabled.is_(True))
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def count_playable_videos(self, *, tenant_id: int, course_id: str) -> int:
        statement = select(func.count(PortalCourseVideo.id)).where(
            PortalCourseVideo.tenant_id == tenant_id,
            PortalCourseVideo.course_id == course_id,
            PortalCourseVideo.enabled.is_(True),
            PortalCourseVideo.duration_seconds > 0,
            or_(
                (
                    (PortalCourseVideo.source_type == "upload")
                    & PortalCourseVideo.object_name.is_not(None)
                ),
                (
                    (PortalCourseVideo.source_type == "url")
                    & PortalCourseVideo.source_url.is_not(None)
                ),
            ),
        )
        return int((await self.session.exec(statement)).one())

    async def add(self, model) -> None:
        self.session.add(model)
        await self.session.flush()

    async def delete_progress_by_video(self, *, tenant_id: int, video_id: str) -> None:
        await self.session.execute(
            delete(PortalCourseVideoProgress).where(
                PortalCourseVideoProgress.tenant_id == tenant_id,
                PortalCourseVideoProgress.video_id == video_id,
            )
        )

    async def delete_progress_by_course(self, *, tenant_id: int, course_id: str) -> None:
        video_ids = select(PortalCourseVideo.id).where(
            PortalCourseVideo.tenant_id == tenant_id,
            PortalCourseVideo.course_id == course_id,
        )
        await self.session.execute(
            delete(PortalCourseVideoProgress).where(
                PortalCourseVideoProgress.tenant_id == tenant_id,
                PortalCourseVideoProgress.video_id.in_(video_ids),
            )
        )

    async def delete_video(self, *, tenant_id: int, video_id: str) -> None:
        await self.delete_progress_by_video(tenant_id=tenant_id, video_id=video_id)
        await self.session.execute(
            delete(PortalCourseVideo).where(
                PortalCourseVideo.tenant_id == tenant_id,
                PortalCourseVideo.id == video_id,
            )
        )

    async def delete_course(self, *, tenant_id: int, course_id: str) -> None:
        await self.delete_progress_by_course(tenant_id=tenant_id, course_id=course_id)
        await self.session.execute(
            delete(PortalCourseVideo).where(
                PortalCourseVideo.tenant_id == tenant_id,
                PortalCourseVideo.course_id == course_id,
            )
        )
        await self.session.execute(
            delete(PortalCourse).where(
                PortalCourse.tenant_id == tenant_id,
                PortalCourse.id == course_id,
            )
        )

    async def get_progress(
        self,
        *,
        tenant_id: int,
        user_id: int,
        video_id: str,
        for_update: bool = False,
    ) -> PortalCourseVideoProgress | None:
        statement = select(PortalCourseVideoProgress).where(
            PortalCourseVideoProgress.tenant_id == tenant_id,
            PortalCourseVideoProgress.user_id == user_id,
            PortalCourseVideoProgress.video_id == video_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def list_progress_for_course(
        self,
        *,
        tenant_id: int,
        user_id: int,
        course_id: str,
    ) -> list[PortalCourseVideoProgress]:
        statement = (
            select(PortalCourseVideoProgress)
            .join(
                PortalCourseVideo,
                PortalCourseVideo.id == PortalCourseVideoProgress.video_id,
            )
            .where(
                PortalCourseVideoProgress.tenant_id == tenant_id,
                PortalCourseVideoProgress.user_id == user_id,
                PortalCourseVideo.tenant_id == tenant_id,
                PortalCourseVideo.course_id == course_id,
            )
        )
        return list((await self.session.exec(statement)).all())

    async def object_is_referenced(self, *, tenant_id: int, object_name: str) -> bool:
        statement = select(PortalCourseVideo.id).where(
            PortalCourseVideo.tenant_id == tenant_id,
            PortalCourseVideo.object_name == object_name,
        )
        return (await self.session.exec(statement)).first() is not None

    async def create_cleanup_job(
        self,
        *,
        tenant_id: int,
        object_name: str,
        reason: str,
        not_before: datetime,
    ) -> PortalCourseMediaCleanup:
        job = PortalCourseMediaCleanup(
            tenant_id=tenant_id,
            object_name=object_name,
            reason=reason,
            not_before=not_before,
        )
        await self.add(job)
        return job

    async def cancel_cleanup_job(self, *, tenant_id: int, job_id: str) -> None:
        await self.session.execute(
            update(PortalCourseMediaCleanup)
            .where(
                PortalCourseMediaCleanup.tenant_id == tenant_id,
                PortalCourseMediaCleanup.id == job_id,
                PortalCourseMediaCleanup.status == "pending",
            )
            .values(status="done", lease_until=None, last_error=None)
        )

    async def claim_cleanup_jobs(
        self,
        *,
        now: datetime,
        limit: int,
        lease_seconds: int = 300,
    ) -> list[PortalCourseMediaCleanup]:
        statement = (
            select(PortalCourseMediaCleanup)
            .where(
                PortalCourseMediaCleanup.status == "pending",
                PortalCourseMediaCleanup.not_before <= now,
            )
            .order_by(PortalCourseMediaCleanup.not_before.asc(), PortalCourseMediaCleanup.id.asc())
            .limit(limit)
            .with_for_update()
        )
        jobs = list((await self.session.exec(statement)).all())
        for job in jobs:
            job.status = "processing"
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.update_time = now
            self.session.add(job)
        await self.session.flush()
        return jobs

    async def recover_expired_cleanup_leases(self, *, now: datetime) -> None:
        await self.session.execute(
            update(PortalCourseMediaCleanup)
            .where(
                PortalCourseMediaCleanup.status == "processing",
                PortalCourseMediaCleanup.lease_until < now,
            )
            .values(status="pending", lease_until=None, update_time=now)
        )

    async def get_cleanup_job(
        self,
        *,
        tenant_id: int,
        job_id: str,
        for_update: bool = False,
    ) -> PortalCourseMediaCleanup | None:
        statement = select(PortalCourseMediaCleanup).where(
            PortalCourseMediaCleanup.tenant_id == tenant_id,
            PortalCourseMediaCleanup.id == job_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def list_due_cleanup_refs(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[tuple[str, int]]:
        statement = (
            select(PortalCourseMediaCleanup.id, PortalCourseMediaCleanup.tenant_id)
            .where(
                PortalCourseMediaCleanup.status == "pending",
                PortalCourseMediaCleanup.not_before <= now,
            )
            .order_by(PortalCourseMediaCleanup.not_before.asc(), PortalCourseMediaCleanup.id.asc())
            .limit(limit)
        )
        return [(str(job_id), int(tenant_id)) for job_id, tenant_id in (await self.session.exec(statement)).all()]
