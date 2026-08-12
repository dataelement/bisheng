from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    InitialPermissionResult,
    KnowledgeSpaceCreateReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.schemas.permission_schema import AuthorizeRequest
from bisheng.permission.domain.services.grant_subject_query_service import GrantSubjectQueryService
from bisheng.permission.domain.services.resource_authorization_service import ResourceAuthorizationService


class KnowledgeSpaceCreationApplicationService:
    """Create a knowledge space and optionally apply its initial grants."""

    def __init__(
        self,
        *,
        knowledge_space_service: KnowledgeSpaceService,
        grant_subject_query_service: GrantSubjectQueryService | None = None,
        resource_authorization_service: ResourceAuthorizationService | None = None,
    ):
        self.knowledge_space_service = knowledge_space_service
        self.grant_subject_query_service = grant_subject_query_service or GrantSubjectQueryService()
        self.resource_authorization_service = resource_authorization_service or ResourceAuthorizationService()

    async def create(self, req: KnowledgeSpaceCreateReq, login_user: UserPayload):
        grants = list(req.initial_permissions.grants) if req.initial_permissions else []
        if grants and req.auth_type == AuthTypeEnum.PRIVATE:
            raise PermissionDeniedError()
        if grants:
            await self.grant_subject_query_service.validate_creation_grants(
                resource_type="knowledge_space",
                grants=grants,
                login_user=login_user,
            )

        space = await self.knowledge_space_service.create_knowledge_space(
            name=req.name,
            description=req.description,
            icon=req.icon,
            auth_type=req.auth_type,
            is_released=req.is_released,
            auto_tag_enabled=req.auto_tag_enabled,
            auto_tag_library_id=req.auto_tag_library_id,
            auto_tag_custom_tags=req.auto_tag_custom_tags,
        )
        if not grants:
            return space

        try:
            await self.resource_authorization_service.authorize(
                "knowledge_space",
                str(space.id),
                AuthorizeRequest(grants=grants, revokes=[]),
                login_user,
            )
            permission_result = InitialPermissionResult(status="success")
        except BaseErrorCode as error:
            permission_result = InitialPermissionResult(status="failed", error_code=error.code)

        return {
            **space.model_dump(mode="json"),
            "initial_permission_result": permission_result.model_dump(mode="json"),
        }
