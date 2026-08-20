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
        if not grants:
            return await self.knowledge_space_service.create_knowledge_space(
                name=req.name,
                description=req.description,
                icon=req.icon,
                auth_type=req.auth_type,
                is_released=req.is_released,
                auto_tag_enabled=req.auto_tag_enabled,
                auto_tag_library_id=req.auto_tag_library_id,
                auto_tag_custom_tags=req.auto_tag_custom_tags,
            )

        from bisheng.core.context.tenant import get_current_tenant_id

        tenant_id = get_current_tenant_id() or int(login_user.tenant_id)
        async with self.resource_authorization_service.invite_scenario_guard_for_grants(
            grants=grants,
            tenant_id=int(tenant_id),
        ):
            validated_tenant_id = await self.grant_subject_query_service.validate_creation_grant_request(
                resource_type="knowledge_space",
                grants=grants,
                login_user=login_user,
            )
            direct_grants = [grant for grant in grants if grant.subject_type != "user"]
            await self.grant_subject_query_service.validate_creation_grant_subjects(
                resource_type="knowledge_space",
                grants=direct_grants,
                login_user=login_user,
                tenant_id=validated_tenant_id,
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

            try:
                authorization_result = await self.resource_authorization_service.authorize(
                    "knowledge_space",
                    str(space.id),
                    AuthorizeRequest(grants=grants, revokes=[]),
                    login_user,
                    scenario_guarded=True,
                )
                if authorization_result is None:
                    permission_result = InitialPermissionResult(status="success")
                else:
                    permission_result = InitialPermissionResult(
                        status="failed" if authorization_result.failed_count else "success",
                        direct_applied_count=authorization_result.direct_applied_count,
                        invite_created_count=authorization_result.invite_created_count,
                        invite_existing_count=authorization_result.invite_existing_count,
                        failed_count=authorization_result.failed_count,
                        results=authorization_result.results,
                    )
            except BaseErrorCode as error:
                permission_result = InitialPermissionResult(status="failed", error_code=error.code)

        return {
            **space.model_dump(mode="json"),
            "initial_permission_result": permission_result.model_dump(mode="json"),
        }
