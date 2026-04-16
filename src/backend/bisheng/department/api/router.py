"""Department module router aggregation.

Part of F002-department-tree.
"""

from fastapi import APIRouter

from bisheng.department.api.endpoints.department import router as department_router
from bisheng.department.api.endpoints.department_member import router as member_router

router = APIRouter(prefix='/departments', tags=['Department'])
# 必须先挂 member：其路径含 ``/{dept_id}/members/...`` 多段；若后挂则可能被 ``GET /{dept_id}`` 抢先匹配导致 404。
# department 内已把 ``POST /local-members`` 放在 ``GET /{dept_id}`` 之前，避免字面路径被误吞。
router.include_router(member_router)
router.include_router(department_router)
