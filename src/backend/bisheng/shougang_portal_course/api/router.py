from fastapi import APIRouter

from bisheng.shougang_portal_course.api.endpoints.admin import router as admin_router
from bisheng.shougang_portal_course.api.endpoints.catalog import router as catalog_router
from bisheng.shougang_portal_course.api.endpoints.learning import router as learning_router

router = APIRouter()
router.include_router(catalog_router)
router.include_router(admin_router)
router.include_router(learning_router)
