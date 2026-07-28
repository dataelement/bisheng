"""Dictionary API router - 系统字典路由"""

from fastapi import APIRouter

from bisheng.dictionary.api.endpoints.dictionary_endpoint import router as dictionary_endpoint

router = APIRouter(prefix="/dictionaries")
router.include_router(dictionary_endpoint)
