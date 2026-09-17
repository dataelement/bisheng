"""A Catalog action that is switched off must not break action listings.

Disabling upload_file in the Catalog made every knowledge-space detail request
return 25001, and the client reads a failed detail request as "this space is
gone" and bounces the user to the square. Listing the actions a caller holds is
a question, and "the action is off" is an answer to it: leave the action out.
Executing the action still raises - that guard is what actually stops the write.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import InvalidCatalogActionError
from bisheng.permission.application import business_authorization


def _target(resource_id: str) -> SimpleNamespace:
    return SimpleNamespace(resource_type="knowledge_space", resource_id=resource_id, tenant_id=1)


def _patches(*, batch_check):
    actor = SimpleNamespace(super_admin=False, current_tenant_id=1, tenant_admin_tenant_ids=(), user_id=7)
    registry = SimpleNamespace(resolve=AsyncMock(side_effect=lambda **kw: _target(kw["resource_id"])))
    runtime = SimpleNamespace(batch_check_actions=batch_check)
    return (
        patch.object(business_authorization, "resolve_permission_actor", AsyncMock(return_value=actor)),
        patch.object(business_authorization, "get_f048_resource_registry", AsyncMock(return_value=registry)),
        patch.object(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime)),
    )


@pytest.mark.asyncio
async def test_a_disabled_action_is_absent_instead_of_fatal():
    async def batch_check(_actor, targets, action):
        if action == "upload_file":
            raise InvalidCatalogActionError(msg="Action upload_file is unavailable for knowledge_space")
        return [True] * len(targets)

    p1, p2, p3 = _patches(batch_check=batch_check)
    with p1, p2, p3:
        result = await business_authorization.batch_check_business_actions(
            SimpleNamespace(user_id=7),
            resource_type="knowledge_space",
            resource_ids=[12, 13],
            actions=["visible", "upload_file", "edit"],
        )

    # The listing survives, and only the disabled action is missing.
    assert result["12"] == frozenset({"visible", "edit"})
    assert result["13"] == frozenset({"visible", "edit"})


@pytest.mark.asyncio
async def test_other_failures_still_propagate():
    """Only the Catalog's own "action is off" is an answer; nothing else is."""

    async def batch_check(_actor, _targets, _action):
        raise RuntimeError("openfga unreachable")

    p1, p2, p3 = _patches(batch_check=batch_check)
    with p1, p2, p3, pytest.raises(RuntimeError):
        await business_authorization.batch_check_business_actions(
            SimpleNamespace(user_id=7),
            resource_type="knowledge_space",
            resource_ids=[12],
            actions=["visible"],
        )
