from fastapi import APIRouter

from .endpoints.apps import router as apps_router
from .endpoints.chat import router as chat_router
from .endpoints.config import router as config_router
from .endpoints.knowledge import router as knowledge_router
from .endpoints.shougang_portal import router as shougang_portal_router
from .endpoints.review_tag import router as review_tag_router
from .endpoints.tag_console import router as tag_console_router

router = APIRouter(prefix="/workstation", tags=["WorkStation"])
router.include_router(config_router)
router.include_router(knowledge_router)
router.include_router(shougang_portal_router)
router.include_router(chat_router)
router.include_router(apps_router)
router.include_router(review_tag_router)
# Registered after review_tag: its /tags/console prefix is more specific, and
# review_tag has no conflicting path, so ordering is informational only.
router.include_router(tag_console_router)
