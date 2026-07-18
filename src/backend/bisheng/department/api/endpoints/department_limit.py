"""Department traffic-control API.

The department-level limit is stored on ``department.concurrent_session_limit``.
Per-resource limits are intentionally returned as an empty page until the
department-resource limit table is introduced.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department

router = APIRouter()


class DepartmentLimitSaveRequest(BaseModel):
    department_id: int
    dept_limit: int = Field(default=0, ge=0)
    assistant: List[dict[str, Any]] = Field(default_factory=list)
    skill: List[dict[str, Any]] = Field(default_factory=list)
    work_flows: List[dict[str, Any]] = Field(default_factory=list)


@router.get('/detail/{department_id}')
async def get_department_limit_detail(
    department_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    async with get_async_db_session() as session:
        dept = (await session.exec(
            select(Department).where(Department.id == department_id),
        )).first()
    return resp_200({
        'department_id': department_id,
        'dept_limit': int(getattr(dept, 'concurrent_session_limit', 0) or 0)
        if dept else 0,
    })


@router.get('/resources')
async def get_department_limit_resources(
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    resourceType: Optional[str] = None,
    departmentId: Optional[int] = None,
    name: Optional[str] = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200({'data': [], 'total': 0})


@router.post('/save')
async def save_department_limit(
    data: DepartmentLimitSaveRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    async with get_async_db_session() as session:
        dept = (await session.exec(
            select(Department).where(Department.id == data.department_id),
        )).first()
        if dept is not None:
            dept.concurrent_session_limit = int(data.dept_limit or 0)
            session.add(dept)
            await session.commit()
    return resp_200()

