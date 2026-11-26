from .endpoints.batch import router as batch_router
from .endpoints.deletion import router as deletion_router
from .endpoints.knowledge import router as knowledge_router
from .endpoints.knowledge_space import router as knowledge_space_router
from .endpoints.knowledge_space_tag_library import router as knowledge_space_tag_library_router
from .endpoints.knowledge_version import router as knowledge_version_router
from .endpoints.move_processing import router as move_processing_router
from .endpoints.processing import router as processing_router
from .endpoints.provider_diagnostics import router as provider_diagnostics_router
from .endpoints.provider_instances import router as provider_instances_router
from .endpoints.provider_tags import router as provider_tags_router
from .endpoints.provider_wiki import router as wiki_router
from .endpoints.qa import router as qa_router
from .endpoints.references import router as references_router
from .endpoints.space_copy import router as space_copy_router
from .endpoints.upload_preview import router as upload_preview_router
from .endpoints.upload_settings import router as upload_settings_router

knowledge_router.include_router(provider_instances_router)
knowledge_space_router.include_router(space_copy_router)
knowledge_space_router.include_router(batch_router)
knowledge_space_router.include_router(wiki_router)
knowledge_space_router.include_router(provider_tags_router)
knowledge_space_router.include_router(provider_diagnostics_router)
knowledge_space_router.include_router(processing_router)
knowledge_space_router.include_router(move_processing_router)
knowledge_space_router.include_router(references_router)
knowledge_space_router.include_router(deletion_router)
knowledge_space_router.include_router(upload_settings_router)
knowledge_space_router.include_router(upload_preview_router)

__all__ = [
    "knowledge_router",
    "knowledge_space_router",
    "knowledge_space_tag_library_router",
    "knowledge_version_router",
    "qa_router",
]
