from .endpoints.deletion import router as deletion_router
from .endpoints.knowledge import router as knowledge_router
from .endpoints.knowledge_space import router as knowledge_space_router
from .endpoints.knowledge_space_tag_library import router as knowledge_space_tag_library_router
from .endpoints.knowledge_version import router as knowledge_version_router
from .endpoints.move_processing import router as move_processing_router
from .endpoints.processing import router as processing_router
from .endpoints.qa import router as qa_router
from .endpoints.references import router as references_router

knowledge_space_router.include_router(processing_router)
knowledge_space_router.include_router(move_processing_router)
knowledge_space_router.include_router(references_router)
knowledge_space_router.include_router(deletion_router)

__all__ = [
    "knowledge_router",
    "knowledge_space_router",
    "knowledge_space_tag_library_router",
    "knowledge_version_router",
    "qa_router",
]
