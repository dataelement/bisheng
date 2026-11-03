"""Serialize file processing and destructive retries for the DocFlow provider."""

import functools


def docflow_file_guard(function):
    @functools.wraps(function)
    def wrapped(file_id, *args, **kwargs):
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, ParseType
        from bisheng.knowledge.domain.services.docflow_state import DocFlowState

        files = KnowledgeFileDao.get_file_by_ids([file_id])
        eligible = bool(files) and files[0].file_name.rsplit(".", 1)[-1].lower() in {
            "pdf",
            "png",
            "jpg",
            "jpeg",
            "bmp",
            "ofd",
        }
        selected = eligible and settings.get_knowledge().loader_provider == ParseType.DOCFLOW.value
        existing = files and files[0].parse_type == ParseType.DOCFLOW.value
        if not selected and not existing:
            return function(file_id, *args, **kwargs)
        state = DocFlowState(get_current_tenant_id())
        # The same lease protects parsing and retry cleanup, even when the fair
        # scheduler is disabled. Acquisition failures propagate; never run unlocked.
        with state.lease(f"file:{file_id}"):
            return function(file_id, *args, **kwargs)

    return wrapped
