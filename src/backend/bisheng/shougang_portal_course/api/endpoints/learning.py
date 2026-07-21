from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.shougang_portal_course.domain.schemas.portal_course_schema import (
    ProgressUpdate,
)
from bisheng.shougang_portal_course.domain.services.progress_service import (
    PortalCourseProgressService,
)

router = APIRouter(
    prefix="/shougang-portal/course-learning",
    tags=["shougang-portal-course-learning"],
)

logger = logging.getLogger(__name__)

_MAX_PROGRESS_WRITE_ATTEMPTS = 2


def _tenant_id(user: UserPayload) -> int:
    return int(get_current_tenant_id() or user.tenant_id)


@router.get("/courses/{course_id}/progress")
async def get_course_progress(
    course_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    async with get_async_db_session() as session:
        items = await PortalCourseProgressService(session).get_course_progress(
            tenant_id=_tenant_id(login_user),
            user_id=login_user.user_id,
            course_id=course_id,
        )
    return resp_200(
        {"items": [item.model_dump(mode="json", exclude_none=True) for item in items]}
    )


@router.put("/videos/{video_id}/progress")
async def report_video_progress(
    video_id: str,
    payload: ProgressUpdate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    for attempt in range(_MAX_PROGRESS_WRITE_ATTEMPTS):
        try:
            async with get_async_db_session() as session:
                async with session.begin():
                    item = await PortalCourseProgressService(session).report(
                        tenant_id=_tenant_id(login_user),
                        user_id=login_user.user_id,
                        video_id=video_id,
                        payload=payload,
                    )
            break
        except IntegrityError:
            logger.warning(
                "portal course progress write conflict tenant_id=%s user_id=%s "
                "video_id=%s attempt=%s",
                _tenant_id(login_user),
                login_user.user_id,
                video_id,
                attempt + 1,
            )
            if attempt + 1 >= _MAX_PROGRESS_WRITE_ATTEMPTS:
                raise
    return resp_200(item.model_dump(mode="json", exclude_none=True))
