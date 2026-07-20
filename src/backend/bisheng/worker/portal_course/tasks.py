from __future__ import annotations

import logging
from datetime import datetime

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.services.cleanup_service import (
    PortalCourseCleanupService,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)


@bisheng_celery.task(
    acks_late=True,
    time_limit=300,
    soft_time_limit=240,
    name="bisheng.worker.portal_course.tasks.scan_portal_course_media_cleanup",
)
def scan_portal_course_media_cleanup() -> int:
    return run_async_task(_scan_cleanup_jobs)


@bisheng_celery.task(
    acks_late=True,
    time_limit=180,
    soft_time_limit=150,
    name="bisheng.worker.portal_course.tasks.process_portal_course_media_cleanup",
)
def process_portal_course_media_cleanup(job_id: str, tenant_id: int) -> bool:
    return run_async_task(lambda: _process_cleanup_job(job_id=job_id, tenant_id=tenant_id))


async def _scan_cleanup_jobs(limit: int = 100) -> int:
    now = datetime.now()
    async with get_async_db_session() as session:
        repository = PortalCourseRepository(session)
        async with session.begin():
            with bypass_tenant_filter():
                await repository.recover_expired_cleanup_leases(now=now)
                jobs = await repository.claim_cleanup_jobs(now=now, limit=limit)
                refs = [(job.id, job.tenant_id) for job in jobs]
    for job_id, tenant_id in refs:
        process_portal_course_media_cleanup.apply_async(
            args=(job_id, tenant_id),
            headers={"tenant_id": tenant_id},
        )
    return len(refs)


async def _process_cleanup_job(*, job_id: str, tenant_id: int) -> bool:
    token = set_current_tenant_id(tenant_id)
    try:
        storage = await get_minio_storage()
        async with get_async_db_session() as session:
            service = PortalCourseCleanupService(session, storage)
            async with session.begin():
                return await service.process_job(tenant_id=tenant_id, job_id=job_id)
    finally:
        current_tenant_id.reset(token)


def enqueue_portal_course_cleanup(job_ids: list[str], tenant_id: int) -> None:
    for job_id in job_ids:
        process_portal_course_media_cleanup.apply_async(
            args=(job_id, tenant_id),
            headers={"tenant_id": tenant_id},
        )
