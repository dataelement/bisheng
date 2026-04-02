from fastapi import APIRouter

from .endpoints.chat import router as chat_endpoints
from .endpoints.feedback import router as feedback_endpoints
from .endpoints.session import router as session_endpoints

router = APIRouter(tags=['Chat'])
router.include_router(chat_endpoints)
router.include_router(feedback_endpoints)
router.include_router(session_endpoints, prefix='/session')
