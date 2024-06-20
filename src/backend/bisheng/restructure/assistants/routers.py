from fastapi import APIRouter
from bisheng.restructure.assistants.views import router

assistant_router = APIRouter(prefix='/api/v1')
assistant_router.include_router(router)
