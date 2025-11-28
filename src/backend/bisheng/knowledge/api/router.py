from .endpoints.knowledge import router as knowledge_router
from .endpoints.qa import router as qa_router

__all__ = ['knowledge_router', 'qa_router']
