"""积分模块路由聚合。"""

from fastapi import APIRouter

from bisheng.points.api.endpoints.admin import router as admin_router
from bisheng.points.api.endpoints.me import router as me_router

router = APIRouter(prefix="/points", tags=["points"])
router.include_router(me_router)
router.include_router(admin_router)
