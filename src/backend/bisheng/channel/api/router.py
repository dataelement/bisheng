from fastapi import APIRouter
from .endpoints.channel_manager import router as channel_manager

router = APIRouter(prefix='/channel')

router.include_router(channel_manager)
