"""AC-61, AC-62: background scopes must not inherit another request's privileges."""

import asyncio

import pytest

from bisheng.core.context import tenant


def test_nested_failure_restores_admin_visibility_and_bypass():
    bindings = (
        (tenant.current_tenant_id, 9),
        (tenant.visible_tenant_ids, frozenset({1, 9})),
        (tenant._admin_scope_tenant_id, 12),
        (tenant._bypass_tenant_filter, True),
        (tenant._is_management_api, True),
        (tenant._management_all_tenants, True),
    )
    tokens = [(variable, variable.set(value)) for variable, value in bindings]
    try:
        with tenant.tenant_execution_scope(2):
            assert tenant.get_current_tenant_id() == 2
            assert tenant.get_visible_tenant_ids() == frozenset({2})
            assert not tenant.is_tenant_filter_bypassed()
            assert not tenant.is_management_all_tenants()
            with pytest.raises(RuntimeError):
                with tenant.tenant_execution_scope(3):
                    assert tenant.get_current_tenant_id() == 3
                    raise RuntimeError("projection failed")
            assert tenant.get_current_tenant_id() == 2
        assert tenant.get_current_tenant_id() == 12
        assert tenant.current_tenant_id.get() == 9
        assert tenant.get_visible_tenant_ids() == frozenset({1, 9})
        assert tenant.is_tenant_filter_bypassed()
        assert tenant.is_management_all_tenants()
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


async def test_concurrent_background_tasks_do_not_share_scope():
    barrier = asyncio.Barrier(2)

    async def run(tenant_id):
        with tenant.tenant_execution_scope(tenant_id):
            await barrier.wait()
            assert tenant.get_current_tenant_id() == tenant_id
            assert tenant.get_visible_tenant_ids() == frozenset({tenant_id})

    token = tenant.current_tenant_id.set(None)
    try:
        await asyncio.gather(run(2), run(3))
        assert tenant.current_tenant_id.get() is None
    finally:
        tenant.current_tenant_id.reset(token)


@pytest.mark.parametrize("invalid", [0, -1, None, True, "2"])
def test_invalid_tenant_never_changes_the_callers_context(invalid):
    before = tenant.get_current_tenant_id()
    with pytest.raises(ValueError):
        with tenant.tenant_execution_scope(invalid):
            pytest.fail("invalid scope was entered")
    assert tenant.get_current_tenant_id() == before
