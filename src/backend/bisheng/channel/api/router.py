from fastapi import APIRouter
from .endpoints.channel_manager import router as channel_manager
from .endpoints.channel_chat import router as channel_chat

router = APIRouter(prefix='/channel')

router.include_router(channel_manager)
router.include_router(channel_chat)
