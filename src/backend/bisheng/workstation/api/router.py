from fastapi import APIRouter

from .endpoints.apps import router as apps_router
from .endpoints.chat import router as chat_router
from .endpoints.config import router as config_router
from .endpoints.knowledge import router as knowledge_router

router = APIRouter(prefix='/workstation', tags=['WorkStation'])
router.include_router(config_router)
router.include_router(knowledge_router)
router.include_router(chat_router)
router.include_router(apps_router)
