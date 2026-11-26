"""Validate every business target encoded by the legacy share-link formats."""

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.session import MessageSessionDao
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao
from bisheng.permission.application import business_authorization
from bisheng.share_link.domain.models.share_link import ResourceTypeEnum, ShareMode


async def authorize_share_target(request, login_user) -> int:
    """Resolve real objects before issuing a bearer capability, not from metadata."""
    tenant_id = get_current_tenant_id() or login_user.tenant_id
    if type(tenant_id) is not int or tenant_id <= 0:  # noqa: E721  # exact type, bool must not pass as int
        raise UnAuthorizedError()
    metadata = request.meta_data or {}
    session = await MessageSessionDao.async_get_one(request.resource_id)
    session_types = {ResourceTypeEnum.WORKBENCH_CHAT, ResourceTypeEnum.LINSIGHT_SESSION}
    if session is not None:
        subject = SessionSubject.natural_person(tenant_id=tenant_id, user_id=login_user.user_id)
        if not subject.matches(session):
            raise UnAuthorizedError()
        if metadata.get("flowId") and metadata["flowId"] != session.flow_id:
            raise UnAuthorizedError()
        if request.resource_type == ResourceTypeEnum.WORKFLOW and session.flow_type != FlowType.WORKFLOW.value:
            raise UnAuthorizedError()
        if request.resource_type == ResourceTypeEnum.ASSISTANT and session.flow_type != FlowType.ASSISTANT.value:
            raise UnAuthorizedError()
        if request.resource_type == ResourceTypeEnum.LINSIGHT_SESSION and session.flow_type not in {
            FlowType.LINSIGHT.value,
            FlowType.WORKSTATION.value,
        }:
            raise UnAuthorizedError()
        version_id = metadata.get("versionId")
        if version_id:
            version = await LinsightSessionVersionDao.get_by_id(version_id)
            if (
                version is None
                or version.session_id != session.chat_id
                or version.tenant_id != tenant_id
                or version.user_id != login_user.user_id
            ):
                raise UnAuthorizedError()
        app_id = session.flow_id
    else:
        if request.resource_type in session_types:
            raise NotFoundError()
        if metadata.get("versionId") or (metadata.get("flowId") and metadata["flowId"] != request.resource_id):
            raise UnAuthorizedError()
        app_id = request.resource_id

    resource_type = None
    if request.resource_type in {ResourceTypeEnum.WORKFLOW, ResourceTypeEnum.ASSISTANT}:
        resource_type = request.resource_type.value
    elif metadata.get("flowId"):
        resource_type = {FlowType.WORKFLOW.value: "workflow", FlowType.ASSISTANT.value: "assistant"}.get(
            session.flow_type
        )
        if resource_type is None:
            raise UnAuthorizedError()
    if resource_type is not None:
        if resource_type == "workflow":
            resource = await FlowDao.aget_flow_by_id(app_id)
            if resource is None or resource.flow_type != FlowType.WORKFLOW.value:
                raise NotFoundError()
        else:
            resource = await AssistantDao.aget_one_assistant(app_id)
        if resource is None or resource.is_delete:
            raise NotFoundError()
        if resource.tenant_id != tenant_id:
            raise UnAuthorizedError()
        await business_authorization.require_business_action(
            login_user, resource_type=resource_type, resource_id=resource.id, action="share"
        )
        if request.share_mode == ShareMode.EDITABLE:
            await business_authorization.require_business_action(
                login_user, resource_type=resource_type, resource_id=resource.id, action="edit"
            )
    return tenant_id
