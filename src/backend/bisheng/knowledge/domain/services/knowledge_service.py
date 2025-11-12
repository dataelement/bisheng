from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.api.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository


class KnowledgeService:
    """Service class for managing knowledge domain operations."""

    def __init__(self, knowledge_repository: 'KnowledgeRepository'):
        self.knowledge_repository = knowledge_repository

    async def add_metadata_fields(self, login_user: UserPayload, add_metadata_fields: AddKnowledgeMetadataFieldsReq):
        """Add metadata fields to a knowledge entity."""

        knowledge_model = await self.knowledge_repository.find_by_id(entity_id=add_metadata_fields.knowledge_id)

        # Permission check
        if not await login_user.async_access_check(
                knowledge_model.user_id, str(knowledge_model.id), AccessType.KNOWLEDGE_WRITE
        ):
            raise UnAuthorizedError()

        # Initialize metadata_fields if it's None
        if knowledge_model.metadata_fields is None:
            knowledge_model.metadata_fields = []

        existing_field_names = {field.field_name for field in knowledge_model.metadata_fields}

        # Add new metadata fields, avoiding duplicates
        for field in add_metadata_fields.metadata_fields:
            if field.field_name not in existing_field_names:
                knowledge_model.metadata_fields.append(field.model_dump())

        knowledge_model = await self.knowledge_repository.update(knowledge_model)

        return knowledge_model
