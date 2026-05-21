from .endpoints.knowledge import router as knowledge_router
from .endpoints.qa import router as qa_router
from .endpoints.knowledge_space import router as knowledge_space_router
from .endpoints.knowledge_space_tag_library import router as knowledge_space_tag_library_router

__all__ = ['knowledge_router', 'qa_router', 'knowledge_space_router', 'knowledge_space_tag_library_router']
