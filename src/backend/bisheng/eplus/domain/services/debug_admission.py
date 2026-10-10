"""Read-only admission; caller-supplied space/model scopes are never accepted."""

from typing import Any, Protocol

from fastapi import HTTPException

from bisheng.eplus.domain.schemas.debug import DebugContext


class DebugAuthorization(Protocol):
    async def require_admin(self, operator: Any) -> None: ...
    async def require_assistant_edit(self, operator: Any, assistant_id: str) -> None: ...


class DebugContextReader(Protocol):
    async def load_context(self, assistant_id: str, test_user_id: int, operator_id: int) -> DebugContext | None: ...


def validate_debug_context(
    context: DebugContext | None, operator: Any, assistant_id: str, user_id: int
) -> DebugContext:
    if context is None:
        raise HTTPException(404, "debug target unavailable")
    assistant = context.assistant
    if (
        context.tenant_id != operator.tenant_id
        or context.operator_id != operator.user_id
        or context.test_user_id != user_id
        or int(assistant.tenant_id) != context.tenant_id
        or str(assistant.id) != assistant_id
    ):
        raise HTTPException(403, "debug scope mismatch")
    if assistant.is_delete or assistant.status != 2:
        raise HTTPException(409, "saved assistant must be online")
    if not context.robot_scope.space_ids or {s["id"] for s in context.spaces} != set(context.robot_scope.space_ids):
        raise HTTPException(409, "robot requires valid bound spaces")
    return context


class DebugAdmissionService:
    def __init__(self, authorization: DebugAuthorization, reader: DebugContextReader):
        self.authorization = authorization
        self.reader = reader

    async def context(self, operator: Any, assistant_id: str, test_user_id: int) -> DebugContext:
        await self.authorization.require_admin(operator)
        await self.authorization.require_assistant_edit(operator, assistant_id)
        snapshot = await self.reader.load_context(assistant_id, test_user_id, operator.user_id)
        return validate_debug_context(snapshot, operator, assistant_id, test_user_id)
