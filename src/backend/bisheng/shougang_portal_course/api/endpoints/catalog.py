from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.shougang_portal_course.domain.services.course_service import (
    PortalCourseService,
)
from bisheng.shougang_portal_course.domain.services.media_service import (
    PortalCourseMediaService,
)

router = APIRouter(
    prefix="/shougang-portal/course-catalog",
    tags=["shougang-portal-course-catalog"],
)


def _tenant_id(user: UserPayload) -> int:
    return int(get_current_tenant_id() or user.tenant_id)


@router.get("/courses")
async def list_courses(
    placement: Literal["all", "home"] = Query(default="all"),
    service_user: UserPayload = Depends(UserPayload.get_login_user),
):
    async with get_async_db_session() as session:
        items = await PortalCourseService(session).list_read_models(
            tenant_id=_tenant_id(service_user),
            public_only=True,
            home_only=placement == "home",
        )
    return resp_200(
        {"items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
    )


@router.get("/courses/{course_id}")
async def get_course(
    course_id: str,
    service_user: UserPayload = Depends(UserPayload.get_login_user),
):
    storage = await get_minio_storage()
    async with get_async_db_session() as session:
        item = await PortalCourseService(session).get_read_model(
            tenant_id=_tenant_id(service_user),
            course_id=course_id,
            public_only=True,
            media_service=PortalCourseMediaService(storage=storage),
        )
    return resp_200(item.model_dump(mode="json", exclude_none=True))
