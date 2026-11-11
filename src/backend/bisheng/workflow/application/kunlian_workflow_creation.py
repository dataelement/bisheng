from loguru import logger

from bisheng.common.errcode.flow import WorkflowRegistrationConflict, WorkflowRegistrationPending
from bisheng.common.errcode.tenant_quota import TenantQuotaExceededError, TenantRoleQuotaExceededError
from bisheng.database.models.flow import Flow, FlowStatus, FlowType
from bisheng.workflow.domain.repositories.platform_node_publication import PlatformNodePublication
from bisheng.workflow.domain.schemas.kunlian_registration import MANAGEMENT_CREATION_KEY_PREFIX
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest


async def create_registered_workflow(
    repository, user, request, request_key, check_quota, project_owner, *, workflow_management=False
):
    if not request_key or len(request_key) > 128 or not request_key.isascii() or not request_key.isprintable():
        raise WorkflowRegistrationConflict()
    values = request.model_dump(exclude={"user_id", "status", "flow_type", "flow_id", "is_shared"})
    if values.get("data") is not None:
        values["data"] = PlatformNodePublication.candidate_graph(values["data"])
    key = canonical_digest([user.tenant_id, user.user_id, request_key])
    if workflow_management:
        # 前缀不属于原十六进制键空间，同时保持数据库键长度。
        key = MANAGEMENT_CREATION_KEY_PREFIX + key[len(MANAGEMENT_CREATION_KEY_PREFIX) :]
    digest = canonical_digest(values)
    found = repository.find_creation(user.tenant_id, key, digest)
    if found is None:
        try:
            await check_quota()
        except (TenantQuotaExceededError, TenantRoleQuotaExceededError):
            # 并发同键请求可能在配额检查期间已用掉最后一份配额。
            found = repository.find_creation(user.tenant_id, key, digest)
            if found is None:
                raise
    if found is None:
        found = repository.create(
            key,
            digest,
            Flow.model_validate(
                {
                    **values,
                    "user_id": user.user_id,
                    "tenant_id": user.tenant_id,
                    "flow_type": FlowType.WORKFLOW.value,
                    "status": FlowStatus.OFFLINE.value,
                }
            ),
        )
    flow, version_id, complete = found
    if not complete:
        try:
            await project_owner(flow)
            repository.finish_creation(user.tenant_id, key)
        except Exception as error:
            logger.warning("昆联工作流创建待恢复 workflow_id={} error={}", flow.id, type(error).__name__)
            raise WorkflowRegistrationPending() from None
    return flow, version_id
