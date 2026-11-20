"""Explicit session read authority; never reuse it as mutation authority."""

from fastapi import Depends

from bisheng.api.services.audit_log import AuditLogService
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.share_link.domain.models.share_link import ResourceTypeEnum
from bisheng.user.domain.services.auth import AuthJwt


async def optional_session_reader(auth_jwt: AuthJwt = Depends()) -> UserPayload | None:
    try:
        return await UserPayload.get_login_user(auth_jwt)
    except JWTDecodeError:
        return None


def token_matches_session(share_link, session) -> bool:
    if share_link is None or session is None or session.is_delete:
        return False
    if share_link.tenant_id != session.tenant_id or share_link.resource_id != session.chat_id:
        return False
    expected_type = {5: ResourceTypeEnum.ASSISTANT, 10: ResourceTypeEnum.WORKFLOW}.get(
        session.flow_type, ResourceTypeEnum.WORKBENCH_CHAT
    )
    valid_types = {expected_type}
    if session.flow_type in {15, 20}:
        valid_types.add(ResourceTypeEnum.LINSIGHT_SESSION)
    if share_link.resource_type not in valid_types:
        return False
    flow_id = (share_link.meta_data or {}).get("flowId")
    return not flow_id or flow_id == session.flow_id


async def require_session_read(session, login_user, share_link=None) -> None:
    if session is None or session.is_delete:
        raise UnAuthorizedError()
    if token_matches_session(share_link, session):
        return
    if login_user is None:
        raise UnAuthorizedError()
    tenant_id = get_current_tenant_id() or login_user.tenant_id
    if session.tenant_id != tenant_id:
        raise UnAuthorizedError()
    subject = SessionSubject.natural_person(tenant_id=tenant_id, user_id=login_user.user_id)
    if subject.matches(session):
        return
    # Audit and annotation are explicit read-only business adapters, never a
    # raw compatibility user_id shortcut for service/public conversations.
    await AuditLogService.assert_session_in_audit_scope(login_user, session.chat_id, app_id=session.flow_id)
