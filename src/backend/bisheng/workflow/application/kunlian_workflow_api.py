"""昆联管理协议的窄适配, 业务规则由已有服务拥有。"""

from asyncio import to_thread

from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError
from bisheng.permission.application.business_authorization import require_business_action


def _read_workflow_tenant_id_sync(workflow_id: str) -> int | None:
    from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentPublicationError
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository

    # Run inside worker thread so ContextVar tenant bypass always applies to sync SQLModel sessions.
    with bypass_tenant_filter():
        try:
            target = PlatformAgentRepository().get_workflow(workflow_id)
        except (PlatformAgentPublicationError, PlatformAgentExecutionError):
            return None
    if not target or target.get("flow_type") != 10:
        return None
    tenant_id = target.get("tenant_id")
    return tenant_id if type(tenant_id) is int and tenant_id > 0 else None


async def resolve_kunlian_workflow_tenant_id(workflow_id: str) -> int | None:
    """Resolve owning tenant_id for a Kunlian workflow path parameter; returns None if missing."""
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        return None
    return await to_thread(_read_workflow_tenant_id_sync, workflow_id.strip())


class KunlianWorkflowApi:
    def __init__(self, *, target_reader=None, flow_service=None, workflow_service=None, repository=None):
        from bisheng.api.services.flow import FlowService
        from bisheng.api.services.workflow import WorkFlowService
        from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository

        self.flow_service = flow_service or FlowService
        self.workflow_service = workflow_service or WorkFlowService
        from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository

        self.repository = repository or RegistrationRepository()
        self.reader = PlatformAgentRepository()
        self.target_reader = target_reader or self._read_target

    async def _read_target(self, workflow_id):
        return await to_thread(self.reader.get_workflow, workflow_id)

    async def target(self, user, workflow_id):
        target = await self.target_reader(workflow_id)
        if not target or target["tenant_id"] != user.tenant_id or target.get("flow_type") != 10:
            raise KunlianAccessError("NOT_FOUND")
        return target

    async def list(self, user, *, name=None, cursor=None, page_size=20):
        return await self.workflow_service.get_all_flows_envelope(
            user,
            name,
            None,
            None,
            10,
            cursor=cursor,
            page_size=page_size,
            managed=False,
            action="visible",
            workflow_management=True,
        )

    async def describe(self, user, workflow_id, version_id=None):
        from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository

        await self.target(user, workflow_id)
        await require_business_action(user, resource_type="workflow", resource_id=workflow_id, action="visible")
        return await to_thread(
            PublishedRunRegistrationRepository().describe_published, user.tenant_id, workflow_id, version_id
        )

    async def detail(self, user, workflow_id, *, for_edit=False):
        await self.target(user, workflow_id)
        from bisheng.workflow.domain.schemas.kunlian_redaction import redact_workflow_response

        return redact_workflow_response(
            await self.flow_service.get_management_flow(user, workflow_id, for_edit=for_edit),
            include_graph=for_edit,
        )

    async def update(self, user, request, workflow_id, values):
        from bisheng.workflow.domain.repositories.kunlian_workflow_api import KunlianWorkflowMetadataRepository

        await self.target(user, workflow_id)
        await require_business_action(user, resource_type="workflow", resource_id=workflow_id, action="edit")
        if not set(values) <= {"name", "description", "logo"}:
            raise KunlianAccessError("INVALID_INPUT")
        return await to_thread(KunlianWorkflowMetadataRepository().update_metadata, workflow_id, user.tenant_id, values)

    async def versions(self, user, workflow_id):
        await self.target(user, workflow_id)
        from fastapi.encoders import jsonable_encoder

        from bisheng.common.schemas.api import resp_200

        result = await self.flow_service.get_version_list_by_flow(user, workflow_id)
        if result.status_code != 200:
            return result
        payload = jsonable_encoder(result.data)
        fields = {"id", "name", "description", "is_current", "create_time", "update_time", "draft_revision"}
        return resp_200(
            {
                "data": [{key: value for key, value in row.items() if key in fields} for row in payload["data"]],
                "total": payload["total"],
            }
        )

    async def _version(self, user, workflow_id, version_id):
        await self.target(user, workflow_id)
        version = await to_thread(self.reader.get_version, version_id)
        if version.get("flow_id") != workflow_id or version.get("tenant_id") != user.tenant_id:
            raise KunlianAccessError("NOT_FOUND")
        return version

    async def version(self, user, workflow_id, version_id):
        raw_version = await self._version(user, workflow_id, version_id)
        from fastapi.encoders import jsonable_encoder

        from bisheng.common.schemas.api import resp_200
        from bisheng.workflow.domain.schemas.kunlian_redaction import redact_workflow_graph

        await require_business_action(user, resource_type="workflow", resource_id=workflow_id, action="edit")
        result = await self.flow_service.get_version_info(user, version_id)
        if result.status_code != 200:
            return result
        payload = jsonable_encoder(result.data)
        fields = {"id", "name", "description", "is_current", "create_time", "update_time", "draft_revision", "data"}
        public = {key: value for key, value in payload.items() if key in fields}
        if "data" in public:
            public["data"] = redact_workflow_graph(public["data"])
        from types import SimpleNamespace

        from bisheng.workflow.domain.repositories.kunlian_registration import version_revision

        public["draft_revision"] = version_revision(SimpleNamespace(**raw_version))
        return resp_200(public)

    async def create_version(self, user, workflow_id, body):
        await self.target(user, workflow_id)
        source_version_id = getattr(body, "original_version_id", None)
        if source_version_id is not None:
            await self._version(user, workflow_id, source_version_id)
        body.flow_type = 10
        from bisheng.workflow.domain.schemas.kunlian_redaction import redact_workflow_response

        return redact_workflow_response(await self.flow_service.create_new_version(user, workflow_id, body))

    async def save_version(self, user, request, workflow_id, version_id, body):
        from bisheng.workflow.domain.repositories.kunlian_workflow_api import KunlianWorkflowMetadataRepository
        from bisheng.workflow.domain.schemas.kunlian_redaction import redact_workflow_response

        await self._version(user, workflow_id, version_id)
        await require_business_action(user, resource_type="workflow", resource_id=workflow_id, action="edit")
        updated = await to_thread(
            KunlianWorkflowMetadataRepository().save_draft,
            workflow_id,
            user.tenant_id,
            version_id,
            request.headers.get("If-Match"),
            name=body.name,
            description=body.description,
            data=body.data,
        )
        return redact_workflow_response(updated)

    async def select_version(self, user, request, workflow_id, version_id):
        await self._version(user, workflow_id, version_id)
        return await self.flow_service.change_current_version(request, user, workflow_id, version_id)

    async def publish(self, user, workflow_id, version_id, *, online):
        from bisheng.database.models.flow import FlowStatus

        await self._version(user, workflow_id, version_id)
        if not online:
            from bisheng.workflow.domain.repositories.kunlian_workflow_api import KunlianWorkflowMetadataRepository

            await require_business_action(user, resource_type="workflow", resource_id=workflow_id, action="unpublish")
            return await to_thread(
                KunlianWorkflowMetadataRepository().unpublish, workflow_id, user.tenant_id, version_id
            )
        # Retain existing graph validation and platform Agent/knowledge publication.
        await self.workflow_service.update_flow_status(user, workflow_id, version_id, FlowStatus.ONLINE.value)

    async def create(self, user, request, body, key):
        from bisheng.permission.application.relation_api import is_tenant_admin
        from bisheng.role.domain.services.quota_service import QuotaResourceType, QuotaService
        from bisheng.workflow.application.kunlian_workflow_creation import create_registered_workflow

        if not await is_tenant_admin(user.user_id, user.tenant_id):
            from bisheng.common.dependencies.user_deps import UserPayload

            await UserPayload.assert_effective_web_menu_any(user.user_id, ("create_workflow", "create_app"))

        async def check_quota():
            await QuotaService.check_quota(
                user_id=user.user_id,
                resource_type=QuotaResourceType.WORKFLOW,
                tenant_id=user.tenant_id,
                login_user=user,
            )

        async def project_owner(flow):
            await self.flow_service.create_flow_hook(request, user, flow)

        # The formal endpoint supplies a fresh internal operation reference per request.
        flow, version = await create_registered_workflow(
            self.repository,
            user,
            body,
            key,
            check_quota,
            project_owner,
            workflow_management=True,
        )
        return {"id": flow.id, "version_id": version, "name": flow.name}

    async def delete(self, user, request, workflow_id):
        from bisheng.common.errcode.flow import WorkflowRegistrationConflict
        from bisheng.database.models.flow import FlowDao, FlowStatus
        from bisheng.workflow.application.kunlian_workflow_management import workflow_scope

        await self.target(user, workflow_id)
        db_flow = await to_thread(FlowDao.get_flow_by_id, workflow_id)
        if not db_flow or db_flow.tenant_id != user.tenant_id or db_flow.flow_type != 10:
            raise KunlianAccessError("NOT_FOUND")
        if db_flow.status == FlowStatus.ONLINE.value:
            raise WorkflowRegistrationConflict()
        scope = workflow_scope(db_flow.tenant_id, workflow_id, user=user, repository=self.repository)
        await self.flow_service.project_flow_delete(user, db_flow)
        if scope:
            await to_thread(self.repository.delete_offline, scope, workflow_id)
        else:
            await to_thread(FlowDao.delete_flow, db_flow)
        await to_thread(self.flow_service.delete_flow_hook, request, user, db_flow)
