"""Bind old Cookie-only callbacks to their verified, durable conversation."""

from contextlib import contextmanager

from bisheng.chat_session.domain.repositories.moderation_repository import ModerationRepository
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.tenant import TenantDisabledError
from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, tenant_execution_scope, visible_tenant_ids
from bisheng.utils.async_utils import run_async_safe


def _principal_tenant(user):
    credential = getattr(user, "_dsh_web_session_tenant_id", None)
    return credential if credential is not None else user.tenant_id


def _verify_subject(subject, user):
    if subject is None:
        raise NotFoundError.http_exception()
    if type(subject.tenant_id) is not int or subject.tenant_id <= 0:
        raise TenantContextMissingError()
    if (
        subject.user_id != user.user_id
        or not subject.chat_id
        or not subject.flow_id
        or subject.is_delete
        or subject.api_subject_type is not None
    ):
        raise UnAuthorizedError.http_exception()
    credential = getattr(user, "_dsh_web_session_tenant_id", None)
    if (credential is not None or not user.is_global_super) and subject.tenant_id != _principal_tenant(user):
        raise UnAuthorizedError.http_exception()
    return subject.tenant_id


def _require_active(tenant_id):
    if type(tenant_id) is not int or tenant_id <= 0:
        raise TenantContextMissingError()
    if ModerationRepository.tenant_status(tenant_id) != "active":
        raise TenantDisabledError()


@contextmanager
def moderation_add_scope(data, user):
    subject = ModerationRepository.session_subject(data.chat_id)
    target = _verify_subject(subject, user) if subject is not None else _principal_tenant(user)
    if subject is not None and subject.flow_id != data.flow_id:
        raise UnAuthorizedError.http_exception()
    if subject is None and ModerationRepository.has_messages(data.chat_id):
        raise NotFoundError.http_exception()
    _require_active(target)
    with tenant_execution_scope(target):
        resource = None
        if subject is None:
            from bisheng.database.models.flow import FlowType
            from bisheng.permission.application.business_authorization import require_business_action

            kind, resource = ModerationRepository.resource(data.flow_id)
            if resource is None or getattr(resource, "is_delete", False):
                raise NotFoundError.http_exception()
            if kind == "workflow" and resource.flow_type != FlowType.WORKFLOW.value:
                raise UnAuthorizedError.http_exception()
            # Keep Root sharing and the sole concrete-action authority. A
            # resource identifier is not proof of permission to use it.
            if type(resource.tenant_id) is not int or resource.tenant_id <= 0:
                raise TenantContextMissingError()
            # Permit the action resolver to read this exact candidate owner.
            # This is not an ALLOW: F048 still checks sharing/use privileges.
            token = visible_tenant_ids.set(frozenset({target, DEFAULT_TENANT_ID, resource.tenant_id}))
            try:
                run_async_safe(
                    require_business_action(user, resource_type=kind, resource_id=data.flow_id, action="use"),
                    timeout=60,
                )
            finally:
                visible_tenant_ids.reset(token)
        yield resource


@contextmanager
def moderation_update_scope(message_id, user):
    message = ModerationRepository.message_subject(message_id)
    target = _verify_subject(message, user)
    conversation = ModerationRepository.session_subject(message.chat_id)
    _verify_subject(conversation, user)
    if conversation.tenant_id != target or conversation.flow_id != message.flow_id:
        raise UnAuthorizedError.http_exception()
    _require_active(target)
    with tenant_execution_scope(target):
        yield
