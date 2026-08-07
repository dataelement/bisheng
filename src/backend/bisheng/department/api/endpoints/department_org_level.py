"""积分组织四级标签 API（Platform 部门树）。

字面路径须挂在 ``GET /{dept_id}`` 之前，避免被路径参数吞掉。
"""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.points.domain.schemas.points_schema import SetCompanyRootRequest
from bisheng.points.domain.services.department_org_level_service import DepartmentOrgLevelService

router = APIRouter()
_service = DepartmentOrgLevelService()


@router.get("/org-levels")
async def list_org_levels(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """返回当前租户活跃部门的 org_level 列表。"""
    try:
        rows = await _service.list_org_levels(login_user)
        return resp_200([row.model_dump() for row in rows])
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/{dept_id}/set-company-root")
async def set_company_root(
    dept_id: str,
    body: SetCompanyRootRequest | None = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """指定唯一公司根并级联打标；非超管 18201，冲突 18205。"""
    _ = body  # confirm 预留；当前一次调用即执行。
    try:
        data = await _service.set_company_root(login_user, dept_id)
        return resp_200(data.model_dump())
    except BaseErrorCode as exc:
        return exc.return_resp_instance()
