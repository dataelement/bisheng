from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)

logger = logging.getLogger(__name__)


class PortalCourseCleanupService:
    """删除无引用媒体, 达到累计预算后等待人工恢复。"""

    _BASE_BACKOFF_SECONDS = 60
    _MAX_BACKOFF_SECONDS = 6 * 60 * 60
    MAX_ATTEMPTS = 8

    def __init__(self, session, storage):
        self.repository = PortalCourseRepository(session)
        self.storage = storage

    async def process_job(self, *, tenant_id: int, job_id: str, lease_until: datetime | None = None) -> bool:
        job = await self.repository.get_cleanup_job(
            tenant_id=tenant_id,
            job_id=job_id,
            for_update=True,
        )
        if job is None or job.status == "done":
            return True
        if job.status == "dead":
            return False
        if lease_until is not None and (
            job.status != "processing" or job.lease_until != lease_until or lease_until <= datetime.now()
        ):
            return False
        if job.attempt_count >= self.MAX_ATTEMPTS and (
            job.status != "processing" or job.lease_until is None or job.lease_until <= datetime.now()
        ):
            job.status = "dead"
            job.lease_until = None
            await self.repository.add(job)
            return False
        now = datetime.now()
        if job.status == "pending" and job.not_before > now:
            return False
        if job.status == "pending" or job.attempt_count == 0:
            job.attempt_count += 1
        if await self.repository.object_is_referenced(
            tenant_id=tenant_id,
            object_name=job.object_name,
        ):
            job.status = "done"
            job.lease_until = None
            job.last_error = None
            job.update_time = now
            await self.repository.add(job)
            return True

        try:
            await asyncio.wait_for(self.storage.remove_object(
                bucket_name=self.storage.bucket,
                object_name=job.object_name,
            ), timeout=60)
        except Exception as exc:
            if getattr(exc, "code", None) not in {"NoSuchKey", "NoSuchObject"}:
                delay = min(
                    self._BASE_BACKOFF_SECONDS * (2 ** min(job.attempt_count - 1, 20)),
                    self._MAX_BACKOFF_SECONDS,
                )
                job.status = "dead" if job.attempt_count >= self.MAX_ATTEMPTS else "pending"
                job.lease_until = None
                job.not_before = now + timedelta(seconds=delay)
                job.last_error = type(exc).__name__[:1000]
                job.update_time = now
                await self.repository.add(job)
                logger.warning(
                    "portal course media cleanup retry tenant_id=%s job_id=%s attempt=%s error_type=%s",
                    tenant_id,
                    job_id,
                    job.attempt_count,
                    type(exc).__name__,
                )
                return False

        job.status = "done"
        job.lease_until = None
        job.last_error = None
        job.update_time = now
        await self.repository.add(job)
        return True
