from fastapi import APIRouter
from .endpoints.knowledge import router as knowledge
from .endpoints.qa import router as qa

knowledge_router = APIRouter(prefix='/knowledge', tags=['Knowledge'])
qa_router = APIRouter(prefix='/qa', tags=['QA'])

knowledge_router.include_router(knowledge)
qa_router.include_router(qa)
