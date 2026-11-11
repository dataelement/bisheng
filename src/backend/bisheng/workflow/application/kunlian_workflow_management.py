from bisheng.common.errcode.flow import WorkflowRegistrationDenied, WorkflowRegistrationPending
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.flow import FlowType
from bisheng.permission.application.business_authorization import check_business_action, require_business_action
from bisheng.workflow.domain.repositories.kunlian_registration import RegistrationRepository, version_revision
from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationScope

__all__ = ["version_revision"]


def mock_scope(tenant_id):
    config = settings.kunlian_workflow_registration
    if config.mode == "mock" and tenant_id in config.tenant_ids:
        return RegistrationScope(tenant_id, config.connection_id, config.scope_generation)
    return None


def is_enrolled(workflow_id, created):
    return created is True or (created is None and workflow_id in settings.kunlian_workflow_registration.workflow_ids)


def workflow_scope(tenant_id, workflow_id, *, user=None, repository=None):
    if not tenant_id:
        return None
    scope = mock_scope(tenant_id)
    repository = repository or RegistrationRepository()
    created = repository.creation_by_workflow(tenant_id, workflow_id, management_only=scope is None)
    if created is not False and (scope is None or not is_enrolled(workflow_id, created)):
        return None
    if user is not None and user.tenant_id != tenant_id:
        raise UnAuthorizedError()
    if created is False:
        raise WorkflowRegistrationPending()
    return scope


async def summarize(user, row, repository):
    flow_id = row["id"]
    if row.get("tenant_id") != user.tenant_id or row.get("flow_type") != FlowType.WORKFLOW.value:
        raise WorkflowRegistrationDenied()
    with tenant_execution_scope(user.tenant_id):
        await require_business_action(user, resource_type="workflow", resource_id=flow_id, action="visible")
        scope = workflow_scope(user.tenant_id, flow_id, repository=repository)
        actions = {
            action: await check_business_action(user, resource_type="workflow", resource_id=flow_id, action=action)
            for action in ("edit", "publish", "unpublish")
        }
        return {
            "workflow_id": flow_id,
            "name": row["name"],
            "description": row.get("description"),
            "status": row.get("status"),
            "allowed_actions": actions,
            "registration": repository.status(scope, flow_id) if scope else None,
        }


class WorkflowManagementReader:
    def __init__(self, user, list_flows, get_flow, repository):
        self.user = user
        self.list_flows = list_flows
        self.get_flow = get_flow
        self.repository = repository

    async def list(self, name, cursor, limit):
        with tenant_execution_scope(self.user.tenant_id):
            page = await self.list_flows(
                self.user,
                name,
                None,
                None,
                FlowType.WORKFLOW.value,
                cursor=cursor,
                page_size=limit,
                action="visible",
            )
            workflow_ids = self.repository.workflow_ids_in_tenant(self.user.tenant_id, [row["id"] for row in page.data])
            return {
                "items": [
                    await summarize(self.user, {**row, "tenant_id": self.user.tenant_id}, self.repository)
                    for row in page.data
                    if row["id"] in workflow_ids
                ],
                "next_cursor": page.next_cursor,
                "has_more": page.has_more,
            }

    async def detail(self, workflow_id):
        with tenant_execution_scope(self.user.tenant_id):
            row = await self.get_flow(workflow_id)
            if row is None:
                raise WorkflowRegistrationDenied()
            return await summarize(self.user, row.model_dump(), self.repository)
