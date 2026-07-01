"""F041 unit tests — space retrieval helpers (identity, no tenant switch).

Covers design decision 2/3 + gotcha 5.10: building the config-author identity for
knowledge-space retrieval must NOT switch the current tenant ContextVar.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.services import space_flow_retrieval


async def test_scoped_login_user_no_tenant_switch():
    """abuild_scoped_login_user builds the author payload without touching the
    current tenant ContextVar (gotcha 5.10)."""
    set_current_tenant_id(7)  # flow tenant already in context

    fake_user = SimpleNamespace(user_id=42, user_name="author")
    fake_payload = SimpleNamespace(user_id=42, user_name="author", tenant_id=7)

    with (
        patch.object(space_flow_retrieval.UserDao, "aget_user", AsyncMock(return_value=fake_user)),
        patch.object(
            space_flow_retrieval.UserPayload,
            "init_login_user",
            AsyncMock(return_value=fake_payload),
        ) as init_mock,
    ):
        result = await space_flow_retrieval.abuild_scoped_login_user(user_id=42, tenant_id=7)

    assert result is fake_payload
    # Identity built within the passed (flow) tenant, not the author's active tenant.
    assert init_mock.await_args.kwargs["tenant_id"] == 7
    assert init_mock.await_args.kwargs["user_id"] == 42
    # The crucial invariant: current tenant is untouched.
    assert get_current_tenant_id() == 7


async def test_scoped_login_user_none_when_missing():
    """No user_id / unknown user → None (caller treats as 'no visible files')."""
    assert await space_flow_retrieval.abuild_scoped_login_user(user_id=None, tenant_id=1) is None

    with patch.object(space_flow_retrieval.UserDao, "aget_user", AsyncMock(return_value=None)):
        assert await space_flow_retrieval.abuild_scoped_login_user(user_id=999, tenant_id=1) is None
