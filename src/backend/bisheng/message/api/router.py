from fastapi import APIRouter
from .endpoints.message_endpoint import router as message_endpoint

router = APIRouter(prefix='/message')

router.include_router(message_endpoint)
