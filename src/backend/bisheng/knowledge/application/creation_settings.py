"""Creation-only initial values, preserving invalid saved IDs for repair."""

import json

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.knowledge.application.file_processing_adapter import system_processing_defaults
from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy
from bisheng.llm.application.model_default_read import get_model_default_read_runtime


async def get_space_creation_settings(login_user, *, session):
    await KnowledgeCreationPolicy.prepare(login_user)
    raw = await get_model_default_read_runtime().aget_default(
        ConfigKeyEnum.KNOWLEDGE_LLM.value, login_user=login_user, session=session
    )
    model_id = json.loads(raw.payload_json).get("embedding_model_id")
    return {
        "embedding_model": {"id": str(model_id), "name": ""} if type(model_id) in (int, str) else None,
        # This is a pure legacy-schema projection; zero is never a queried,
        # authorized or persisted resource ID.
        "system_defaults": system_processing_defaults(0),
    }
