"""F041: knowledge-space retrieval helpers shared by workflow nodes and assistants.

Adds knowledge-space (``type=3``) support to the flow / assistant retrieval path,
reusing F029's two-layer ``view_file`` filter (`KnowledgeFileVisibilityService`).
The filter identity is chosen by the「用户知识库权限校验」toggle:

  - toggle ON  → runtime user (workflow ``self.user_id`` / assistant ``invoke_user_id``)
  - toggle OFF → config author (``Flow.user_id`` / ``Assistant.user_id``), resolved
                 within the current (flow) tenant WITHOUT switching the tenant
                 ContextVar.

Lives in the knowledge domain (not ``workflow/common``) so both workflow nodes and
``AssistantAgent`` can import it without a cross-module workflow dependency.
See ``features/v2.6.0/041-knowledge-space-select-flow-assistant/design.md``
(decisions 1/2/3, gotchas 5.2/5.3/5.10).
"""

from __future__ import annotations

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.user.domain.models.user import UserDao


async def abuild_scoped_login_user(user_id: int | None, tenant_id: int | None) -> UserPayload | None:
    """Build a ``UserPayload`` for ``user_id`` scoped to ``tenant_id`` WITHOUT
    switching the current tenant ContextVar.

    Unlike ``resolve_operator`` (F030), this NEVER calls ``set_current_tenant_id``:
    the workflow node / assistant is mid-execution in the flow's tenant, and
    switching to the author's active tenant would pollute subsequent
    tenant-scoped queries in the same node (design gotcha 5.10). The author is
    resolved within the current (flow) tenant, which is correct because the
    selected knowledge spaces live in that tenant.

    Returns ``None`` when ``user_id`` is falsy or the user no longer exists — the
    caller treats a ``None`` identity as "no visible files" (empty retrieval).
    """
    if not user_id:
        return None
    user = await UserDao.aget_user(user_id)
    if not user:
        return None
    return await UserPayload.init_login_user(
        user_id=user.user_id,
        user_name=user.user_name,
        tenant_id=tenant_id if tenant_id is not None else DEFAULT_TENANT_ID,
    )
