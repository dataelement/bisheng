from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile
from kombu.exceptions import KombuError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.portal_course import (
    PortalCourseNotFoundError,
    PortalCourseSourceInvalidError,
    PortalCourseVideoNotFoundError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.shougang_portal_course.domain.repositories.portal_course_repository import (
    PortalCourseRepository,
)
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    CourseCreate,
    CourseUpdate,
    OrderUpdate,
    UrlVideoCreate,
    VideoUpdate,
)
from bisheng.shougang_portal_course.domain.services.course_service import (
    PortalCourseService,
)
from bisheng.shougang_portal_course.domain.services.media_service import (
    PortalCourseMediaService,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/shougang-portal/course-admin",
    tags=["shougang-portal-course-admin"],
)


def _tenant_id(user: UserPayload) -> int:
    return int(get_current_tenant_id() or user.tenant_id)


def _normalize_title(title: str) -> str:
    value = title.strip()
    if not value or len(value) > 200:
        raise PortalCourseSourceInvalidError()
    return value


async def _create_provisional_cleanup(tenant_id: int, object_name: str) -> str:
    async with get_async_db_session() as session:
        async with session.begin():
            job = await PortalCourseRepository(session).create_cleanup_job(
                tenant_id=tenant_id,
                object_name=object_name,
                reason="provisional",
                not_before=datetime.now() + timedelta(hours=24),
            )
    return job.id


def _enqueue_cleanup(job_ids: list[str], tenant_id: int) -> None:
    if not job_ids:
        return
    from bisheng.worker.portal_course.tasks import enqueue_portal_course_cleanup

    try:
        enqueue_portal_course_cleanup(job_ids, tenant_id)
    except (KombuError, OSError) as exc:
        logger.warning(
            "portal course media cleanup enqueue failed tenant_id=%s job_ids=%s "
            "error_type=%s; recovery scan will retry",
            tenant_id,
            job_ids,
            type(exc).__name__,
            exc_info=True,
        )


async def _admin_course_read(tenant_id: int, course_id: str):
    storage = await get_minio_storage()
    async with get_async_db_session() as session:
        return await PortalCourseService(session).get_read_model(
            tenant_id=tenant_id,
            course_id=course_id,
            public_only=False,
            media_service=PortalCourseMediaService(storage=storage),
        )


@router.get("/courses")
async def list_courses(
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    storage = await get_minio_storage()
    async with get_async_db_session() as session:
        items = await PortalCourseService(session).list_read_models(
            tenant_id=_tenant_id(admin_user),
            public_only=False,
            media_service=PortalCourseMediaService(storage=storage),
            include_videos=True,
        )
    return resp_200(
        {"items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
    )


@router.post("/courses")
async def create_course(
    payload: CourseCreate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            course = await PortalCourseService(session).create_course(
                tenant_id=tenant_id,
                user_id=admin_user.user_id,
                payload=payload,
            )
            course_id = course.id
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))


@router.put("/courses/order")
async def update_course_order(
    payload: OrderUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseService(session).update_course_order(
                tenant_id=_tenant_id(admin_user),
                payload=payload,
            )
    return resp_200({"updated": True})


@router.put("/courses/{course_id}")
async def update_course(
    course_id: str,
    payload: CourseUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseService(session).update_course(
                tenant_id=tenant_id,
                course_id=course_id,
                payload=payload,
            )
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))


@router.delete("/courses/{course_id}")
async def delete_course(
    course_id: str,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            job_ids = await PortalCourseService(session).delete_course(
                tenant_id=tenant_id,
                course_id=course_id,
            )
    _enqueue_cleanup(job_ids, tenant_id)
    return resp_200({"deleted": True})


@router.post("/courses/{course_id}/videos/url")
async def create_url_video(
    course_id: str,
    payload: UrlVideoCreate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseService(session).create_url_video(
                tenant_id=tenant_id,
                course_id=course_id,
                payload=payload,
            )
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))


@router.post("/courses/{course_id}/videos/upload")
async def create_upload_video(
    course_id: str,
    file: UploadFile = File(...),
    title: str = Form(...),
    enabled: bool = Form(False),
    sort_order: int = Form(0),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    title = _normalize_title(title)
    video_id = uuid.uuid4().hex
    async with get_async_db_session() as session:
        course = await PortalCourseRepository(session).get_course(
            tenant_id=tenant_id,
            course_id=course_id,
        )
        if course is None:
            raise PortalCourseNotFoundError()
    storage = await get_minio_storage()
    uploaded = await PortalCourseMediaService(storage=storage).save_upload(
        file,
        tenant_id=tenant_id,
        course_id=course_id,
        video_id=video_id,
        before_store=lambda object_name: _create_provisional_cleanup(
            tenant_id,
            object_name,
        ),
    )
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseService(session).create_uploaded_video(
                tenant_id=tenant_id,
                course_id=course_id,
                title=title,
                enabled=enabled,
                sort_order=sort_order,
                video_id=video_id,
                uploaded=uploaded,
            )
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))


@router.put("/courses/{course_id}/videos/order")
async def update_video_order(
    course_id: str,
    payload: OrderUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    async with get_async_db_session() as session:
        async with session.begin():
            await PortalCourseService(session).update_video_order(
                tenant_id=_tenant_id(admin_user),
                course_id=course_id,
                payload=payload,
            )
    return resp_200({"updated": True})


@router.put("/videos/{video_id}")
async def update_video(
    video_id: str,
    payload: VideoUpdate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            video = await PortalCourseService(session).update_video(
                tenant_id=tenant_id,
                video_id=video_id,
                payload=payload,
            )
            course_id = video.course_id
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))


@router.delete("/videos/{video_id}")
async def delete_video(
    video_id: str,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            repository = PortalCourseRepository(session)
            video = await repository.get_video(tenant_id=tenant_id, video_id=video_id)
            if video is None:
                raise PortalCourseVideoNotFoundError()
            course_id = video.course_id
            job_ids = await PortalCourseService(session).delete_video(
                tenant_id=tenant_id,
                video_id=video_id,
            )
    _enqueue_cleanup(job_ids, tenant_id)
    return resp_200({"deleted": True, "course_id": course_id})


@router.put("/videos/{video_id}/source/url")
async def replace_video_url(
    video_id: str,
    payload: UrlVideoCreate,
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    async with get_async_db_session() as session:
        async with session.begin():
            video, job_ids = await PortalCourseService(session).replace_video_url(
                tenant_id=tenant_id,
                video_id=video_id,
                payload=payload,
            )
            course_id = video.course_id
    _enqueue_cleanup(job_ids, tenant_id)
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))


@router.post("/videos/{video_id}/source/upload")
async def replace_video_upload(
    video_id: str,
    file: UploadFile = File(...),
    title: str = Form(...),
    enabled: bool = Form(False),
    sort_order: int = Form(0),
    admin_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    tenant_id = _tenant_id(admin_user)
    title = _normalize_title(title)
    async with get_async_db_session() as session:
        video = await PortalCourseRepository(session).get_video(
            tenant_id=tenant_id,
            video_id=video_id,
        )
        if video is None:
            raise PortalCourseVideoNotFoundError()
        course_id = video.course_id
    storage = await get_minio_storage()
    uploaded = await PortalCourseMediaService(storage=storage).save_upload(
        file,
        tenant_id=tenant_id,
        course_id=course_id,
        video_id=video_id,
        before_store=lambda object_name: _create_provisional_cleanup(
            tenant_id,
            object_name,
        ),
    )
    async with get_async_db_session() as session:
        async with session.begin():
            _, job_ids = await PortalCourseService(session).replace_video_upload(
                tenant_id=tenant_id,
                video_id=video_id,
                title=title,
                enabled=enabled,
                sort_order=sort_order,
                uploaded=uploaded,
            )
    _enqueue_cleanup(job_ids, tenant_id)
    item = await _admin_course_read(tenant_id, course_id)
    return resp_200(item.model_dump(mode="json", exclude_none=True))
