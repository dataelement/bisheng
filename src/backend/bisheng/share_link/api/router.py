from fastapi import APIRouter
from .endpoints.share_link import router as share_link_router

router = APIRouter(prefix='/share-link', tags=['ShareLink'])

router.include_router(share_link_router)
