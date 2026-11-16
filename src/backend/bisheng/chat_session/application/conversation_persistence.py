"""Keep a conversation's durable owner separate from its resource execution."""

from contextlib import contextmanager

from bisheng.chat_session.domain.repositories.moderation_repository import ModerationRepository
from bisheng.chat_session.domain.services.moderation_scope import _principal_tenant, _require_active, _verify_subject
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope


class ConversationPersistence:
    def __init__(self, user_id, *, user=None):
        # A missing user is only for a trusted, already-admitted platform task.
        self.user_id = user_id
        self.user = user

    @contextmanager
    def scope(self, chat_id, resource_id, user_id):
        if user_id != self.user_id:
            raise UnAuthorizedError.http_exception()
        execution_tenant = get_current_tenant_id()
        subject = ModerationRepository.session_subject(chat_id)
        target = execution_tenant
        if subject is not None:
            if self.user is not None:
                target = _verify_subject(subject, self.user)
            else:
                if subject.user_id != user_id or subject.is_delete or subject.api_subject_type is not None:
                    raise UnAuthorizedError.http_exception()
                target = subject.tenant_id
            if subject.flow_id != resource_id:
                raise UnAuthorizedError.http_exception()
            if target != execution_tenant:
                if self.user is not None:
                    if (
                        not self.user.is_global_super
                        or getattr(self.user, "_dsh_web_session_tenant_id", None) is not None
                        or target != _principal_tenant(self.user)
                    ):
                        raise UnAuthorizedError.http_exception()
                _, resource = ModerationRepository.resource(resource_id)
                if resource is None or resource.tenant_id != execution_tenant:
                    raise NotFoundError.http_exception()
        _require_active(target)
        # An old mixed/orphaned history is not repaired by a continuation.
        messages = ModerationRepository.message_subjects(chat_id)
        if (subject is None and messages) or any(
            owner != user_id or flow != resource_id or tenant != target for owner, flow, tenant in messages
        ):
            raise UnAuthorizedError.http_exception()
        with tenant_execution_scope(target):
            yield

    def save(self, message, new_session=None):
        if message.user_id != self.user_id:
            raise UnAuthorizedError.http_exception()
        return ModerationRepository.save_message(message, new_session)


@contextmanager
def conversation_read_scope(user, chat_id, resource_id=None):
    """Bridge only an owned Home conversation; normal lists/shares stay scoped."""
    subject = ModerationRepository.session_subject(chat_id)
    if subject is None or subject.tenant_id == get_current_tenant_id() or subject.user_id != user.user_id:
        yield
        return
    with ConversationPersistence(user.user_id, user=user).scope(chat_id, resource_id or subject.flow_id, user.user_id):
        yield
