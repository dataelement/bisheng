"""Low-frequency profile outbox; no Gateway IO in the user transaction."""

from contextlib import contextmanager
from uuid import NAMESPACE_URL, uuid5

from bisheng.core.context import tenant as context
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository


@contextmanager
def profile_scope(tenant_id: int):
    tokens = [
        context.set_current_tenant_id(tenant_id),
        context.set_admin_scope_tenant_id(None),
        context.set_visible_tenant_ids(frozenset({tenant_id})),
        context._bypass_tenant_filter.set(False),
    ]
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


class DshProfileService:
    @staticmethod
    def record_change(session, snapshot: dict):
        """Consume a snapshot already versioned by the owning user repository."""
        tenant_id, user_id = int(snapshot["tenant_id"]), int(snapshot["user_id"])
        version = snapshot["profile_version"]
        operation_id = str(uuid5(NAMESPACE_URL, f"bisheng:dsh-profile:{tenant_id}:{user_id}:{version}"))
        with profile_scope(tenant_id):
            return DshOperationRepository(session).register_intent(
                operation_id=operation_id, user_id=user_id, actor_user_id=None, action="SYNC_PROFILE", payload=snapshot
            )
