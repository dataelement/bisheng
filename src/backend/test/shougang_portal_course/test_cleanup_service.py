from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from bisheng.shougang_portal_course.domain.models.portal_course import (
    PortalCourse,
    PortalCourseMediaCleanup,
    PortalCourseVideo,
)
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.services.cleanup_service import (
    PortalCourseCleanupService,
)


async def test_cleanup_does_not_delete_referenced_object(course_session):
    course = PortalCourse(tenant_id=1, name="课", create_user=1)
    course_session.add(course)
    await course_session.flush()
    video = PortalCourseVideo(
        tenant_id=1,
        course_id=course.id,
        title="视频",
        source_type="upload",
        object_name="portal-course/1/object.mp4",
        duration_seconds=10,
    )
    job = PortalCourseMediaCleanup(
        tenant_id=1,
        object_name="portal-course/1/object.mp4",
        reason="delete",
        not_before=datetime.now() - timedelta(seconds=1),
    )
    course_session.add_all([video, job])
    await course_session.commit()
    storage = AsyncMock()
    storage.bucket = "bisheng"

    result = await PortalCourseCleanupService(course_session, storage).process_job(
        tenant_id=1,
        job_id=job.id,
    )

    assert result is True
    storage.remove_object.assert_not_awaited()
    assert job.status == "done"


async def test_cleanup_exhausted_job_never_deletes_again(course_session):
    job = PortalCourseMediaCleanup(
        tenant_id=1,
        object_name="portal-course/1/orphan.mp4",
        reason="provisional",
        not_before=datetime.now() - timedelta(seconds=1),
        attempt_count=20,
        status="processing",
    )
    course_session.add(job)
    await course_session.commit()
    storage = AsyncMock()
    storage.bucket = "bisheng"
    storage.remove_object.side_effect = RuntimeError("temporary minio failure")

    result = await PortalCourseCleanupService(course_session, storage).process_job(
        tenant_id=1,
        job_id=job.id,
    )

    assert result is False
    assert job.status == "dead"
    assert job.attempt_count == 20
    storage.remove_object.assert_not_awaited()


async def test_cleanup_scan_claims_due_jobs_with_a_recoverable_lease(course_session):
    now = datetime.now()
    due = PortalCourseMediaCleanup(
        tenant_id=1,
        object_name="portal-course/1/due.mp4",
        reason="delete",
        not_before=now - timedelta(seconds=1),
    )
    future = PortalCourseMediaCleanup(
        tenant_id=2,
        object_name="portal-course/2/future.mp4",
        reason="delete",
        not_before=now + timedelta(hours=1),
    )
    course_session.add_all([due, future])
    await course_session.commit()

    claimed = await PortalCourseRepository(course_session).claim_cleanup_jobs(
        now=now,
        limit=100,
    )

    assert [job.id for job in claimed] == [due.id]
    assert due.status == "processing"
    assert due.lease_until == (now + timedelta(seconds=300)).replace(microsecond=0)
    assert future.status == "pending"


def test_worker_and_beat_registration_are_stable():
    from bisheng.core.config.settings import CeleryConf

    config = CeleryConf()
    assert config.task_routers["bisheng.worker.portal_course.*"] == {"queue": "celery"}
    assert config.beat_schedule["scan_portal_course_media_cleanup"]["task"] == (
        "bisheng.worker.portal_course.tasks.scan_portal_course_media_cleanup"
    )
    assert config.beat_schedule["scan_portal_course_media_cleanup"]["schedule"] == 60.0
    scan_source = (Path(__file__).parents[2] / "bisheng/worker/portal_course/tasks.py").read_text(encoding="utf-8")
    assert "claim_cleanup_jobs" in scan_source
    assert "list_due_cleanup_refs" not in scan_source


async def test_last_claim_crash_is_terminal_and_stale_lease_cannot_delete(course_session):
    now = datetime.now()
    job = PortalCourseMediaCleanup(tenant_id=1, object_name='portal-course/1/dead.mp4', reason='delete',
                                  not_before=now - timedelta(seconds=1), attempt_count=7)
    course_session.add(job)
    await course_session.commit()
    repo = PortalCourseRepository(course_session)
    lease = await repo.claim_cleanup_job(tenant_id=1, job_id=job.id, now=now)
    await course_session.commit()
    assert lease and lease.microsecond == 0
    assert job.attempt_count == 8
    await repo.recover_expired_cleanup_leases(now=now + timedelta(minutes=6))
    await course_session.commit()
    storage = AsyncMock()
    storage.bucket = 'files'
    assert not await PortalCourseCleanupService(course_session, storage).process_job(
        tenant_id=1, job_id=job.id, lease_until=lease)
    storage.remove_object.assert_not_awaited()
    assert job.status == 'dead'
