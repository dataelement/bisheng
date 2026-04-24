"""Department module router aggregation.

Part of F002-department-tree.
"""

from fastapi import APIRouter

from bisheng.department.api.endpoints.department import router as department_router
from bisheng.department.api.endpoints.department_member import router as member_router

router = APIRouter(prefix='/departments', tags=['Department'])
# 先挂 member：``/{dept_id}/members/...`` 等多段路径；department 内字面路由（含 ``/search/global-members``）须在 ``GET /{dept_id}`` 之前定义。
# 全组织搜索已改为 ``/search/global-members``（两段），避免与 ``GET /{dept_id}`` 将 ``global-members`` 误解析为部门 id。
router.include_router(member_router)
router.include_router(department_router)
