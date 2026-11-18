"""A stale id in a batch must not fail the whole batch.

The management-target proof (AC-53) runs before the super-admin shortcut. A
listing that carries one deleted or foreign id used to raise 25022 for every
id in it; the batch path now leaves such ids without any action instead, while
the single-resource path keeps raising.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.permission.application import business_authorization as business

_MANAGED_TENANT = 60
# id -> owning tenant; an id that is absent here has been deleted.
_RECORDS = {"19": _MANAGED_TENANT, "21": _MANAGED_TENANT, "77": 65}


def _install_registry(monkeypatch, *, super_admin: bool):
    async def load_permission_record(*, resource_id):
        tenant_id = _RECORDS.get(resource_id)
        return None if tenant_id is None else SimpleNamespace(tenant_id=tenant_id)

    async def resolve(*, resource_type, resource_id, actor, action):
        if _RECORDS.get(resource_id) != _MANAGED_TENANT:
            raise PermissionInvalidResourceError()
        return SimpleNamespace(resource_type=resource_type, resource_id=resource_id)

    registry = SimpleNamespace(
        port_for=lambda _: SimpleNamespace(load_permission_record=load_permission_record),
        resolve=resolve,
    )
    creation_ready = AsyncMock()
    runtime = SimpleNamespace(
        batch_check_actions=AsyncMock(side_effect=lambda actor, targets, action: [True] * len(targets))
    )
    actor = SimpleNamespace(
        super_admin=super_admin,
        data_scope=business.DATA_SCOPE_ALL if super_admin else "narrowed",
    )
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(business, "_require_creation_ready", creation_ready)
    monkeypatch.setattr(business, "resolve_permission_actor", AsyncMock(return_value=actor))
    return creation_ready, runtime


async def test_super_admin_batch_drops_deleted_id_and_keeps_the_rest(monkeypatch):
    creation_ready, _ = _install_registry(monkeypatch, super_admin=True)

    with management_tenant_scope(_MANAGED_TENANT):
        result = await business.batch_check_business_actions(
            object(),
            resource_type="knowledge_library",
            resource_ids=[19, 20, 21],
            actions=("visible",),
        )

    assert result["19"] == frozenset({"visible"})
    assert result["21"] == frozenset({"visible"})
    assert not result.get("20")
    # A deleted id must not reach the half-created-resource gate either.
    creation_ready.assert_awaited_once_with("knowledge_library", ("19", "21"))


async def test_super_admin_batch_never_grants_a_foreign_tenant_id(monkeypatch):
    _install_registry(monkeypatch, super_admin=True)

    with management_tenant_scope(_MANAGED_TENANT):
        result = await business.batch_check_business_actions(
            object(),
            resource_type="knowledge_library",
            resource_ids=[19, 77],
            actions=("visible", "use"),
        )

    assert result["19"] == frozenset({"visible", "use"})
    assert not result.get("77")


async def test_batch_with_only_stale_ids_grants_nothing(monkeypatch):
    creation_ready, _ = _install_registry(monkeypatch, super_admin=True)

    with management_tenant_scope(_MANAGED_TENANT):
        result = await business.batch_check_business_actions(
            object(),
            resource_type="knowledge_library",
            resource_ids=[20, 77],
            actions=("visible",),
        )

    assert not any(result.values())
    creation_ready.assert_not_awaited()


async def test_narrowed_actor_in_management_scope_also_keeps_the_rest(monkeypatch):
    _, runtime = _install_registry(monkeypatch, super_admin=False)

    with management_tenant_scope(_MANAGED_TENANT):
        result = await business.batch_check_business_actions(
            object(),
            resource_type="knowledge_library",
            resource_ids=[19, 20, 77],
            actions=("visible",),
        )

    assert result["19"] == frozenset({"visible"})
    assert not result.get("20")
    assert not result.get("77")
    checked = [target.resource_id for call in runtime.batch_check_actions.await_args_list for target in call.args[1]]
    assert checked == ["19"]


async def test_regular_request_without_management_target_is_unchanged(monkeypatch):
    """No admin scope: the target proof is skipped and resolution decides."""

    _, runtime = _install_registry(monkeypatch, super_admin=False)

    result = await business.batch_check_business_actions(
        object(),
        resource_type="knowledge_library",
        resource_ids=[19, 20],
        actions=("visible",),
    )

    assert result == {"19": frozenset({"visible"}), "20": frozenset()}
    assert runtime.batch_check_actions.await_count == 1


async def test_batch_still_fails_for_a_type_that_cannot_prove_its_target(monkeypatch):
    _install_registry(monkeypatch, super_admin=True)
    registry = SimpleNamespace(port_for=lambda _: SimpleNamespace())
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))

    with management_tenant_scope(_MANAGED_TENANT), pytest.raises(PermissionInvalidResourceError):
        await business.batch_check_business_actions(
            object(),
            resource_type="knowledge_library",
            resource_ids=[19],
            actions=("visible",),
        )


async def test_batch_propagates_loader_failures(monkeypatch):
    _install_registry(monkeypatch, super_admin=True)
    loader = AsyncMock(side_effect=RuntimeError("database unavailable"))
    registry = SimpleNamespace(port_for=lambda _: SimpleNamespace(load_permission_record=loader))
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))

    with management_tenant_scope(_MANAGED_TENANT), pytest.raises(RuntimeError):
        await business.batch_check_business_actions(
            object(),
            resource_type="knowledge_library",
            resource_ids=[19],
            actions=("visible",),
        )


@pytest.mark.parametrize("resource_id", ["20", "77"])
async def test_single_resource_check_still_raises_for_a_stale_id(monkeypatch, resource_id):
    _install_registry(monkeypatch, super_admin=True)

    with management_tenant_scope(_MANAGED_TENANT), pytest.raises(PermissionInvalidResourceError):
        await business.check_business_action(
            object(),
            resource_type="knowledge_library",
            resource_id=resource_id,
            action="visible",
        )
