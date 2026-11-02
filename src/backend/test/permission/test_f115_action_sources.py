"""F115 AC-23/26/27/28/33/34/37/52: trusted action sources, not model names."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot


def runtime(pages):
    instance = object.__new__(F048PermissionRuntime)
    instance._state = SimpleNamespace(
        source_read_stamp=AsyncMock(return_value=(("app", "a", 3),)),
        mode_for_target=AsyncMock(
            return_value=SimpleNamespace(
                mode="CUSTOM", version=3, parent_type=None, parent_id=None, projection_state="CURRENT"
            )
        ),
        load_source_page=AsyncMock(side_effect=pages),
    )
    models = (
        SimpleNamespace(snapshot=GrantModelSnapshot("owner", True, ("edit",))),
        SimpleNamespace(snapshot=GrantModelSnapshot("custom", True, ("use",))),
    )
    instance._runtime_catalog = AsyncMock(
        return_value=SimpleNamespace(release_id=1, version=1, checksum="same", models=models)
    )
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=60, resource_type="app", resource_id="a", resource_version=3, context_version="test"
    )
    return instance, target


async def test_actions_not_model_names_and_all_pages():
    row = SimpleNamespace(source_id=7)
    service, target = runtime([((row,), True), ((), False)])
    result = await service.read_effective_action_sources(target=target, action="use")
    assert result == (row,)
    assert service._state.load_source_page.call_args.kwargs["models"][0].model_key == "custom"
    assert service._state.load_source_page.call_args.kwargs["after_id"] == 7


async def test_inactive_model_still_contributes_existing_action_sources():
    row = SimpleNamespace(source_id=7)
    service, target = runtime([((row,), False)])
    catalog = await service._runtime_catalog()
    catalog.models[1].snapshot = GrantModelSnapshot("custom", False, ("use",))
    assert await service.read_effective_action_sources(target=target, action="use") == (row,)
    assert service._state.load_source_page.call_args.kwargs["models"][0].active is False


async def test_projection_change_refuses_partial_roster():
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError

    service, target = runtime([((), False)])
    service._state.source_read_stamp.side_effect = [(1,), (2,)]
    with pytest.raises(PermissionPublishNotReadyError):
        await service.read_effective_action_sources(target=target, action="use")


async def test_nonadvancing_page_refuses_empty_owner_only():
    from bisheng.common.errcode.permission import PermissionEnumerationIncompleteError

    service, target = runtime([((), True)])
    with pytest.raises(PermissionEnumerationIncompleteError):
        await service.read_effective_action_sources(target=target, action="use")


async def test_catalog_change_refuses_old_action_meanings():
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError

    service, target = runtime([((), False)])
    catalog = await service._runtime_catalog()
    latest = SimpleNamespace(**{**vars(catalog), "checksum": "new"})
    service._runtime_catalog.side_effect = [catalog, latest]
    with pytest.raises(PermissionPublishNotReadyError):
        await service.read_effective_action_sources(target=target, action="use")


async def test_inherited_source_stamp_checks_every_ancestor(monkeypatch):
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError
    from bisheng.permission.application import control_state as module

    _service, target = runtime([])
    modes = {
        "a": SimpleNamespace(
            tenant_id=60, mode="INHERIT", version=3, parent_type="app", parent_id="parent", projection_state="CURRENT"
        ),
        "parent": SimpleNamespace(
            tenant_id=60, mode="CUSTOM", version=4, parent_type=None, parent_id=None, projection_state="CURRENT"
        ),
    }

    async def get_mode(*, resource_type, resource_id):
        return modes[resource_id]

    monkeypatch.setattr(module, "ResourcePermissionModeRepository", lambda: SimpleNamespace(aget_mode=get_mode))
    monkeypatch.setattr(
        module, "GrantRepository", lambda: SimpleNamespace(alist_resource_grants=AsyncMock(return_value=[]))
    )
    state = object.__new__(module.SqlPermissionControlState)
    stamp = await state.source_read_stamp(target=target, models=())
    assert len(stamp) == 2
    modes["parent"].projection_state = "PENDING"
    with pytest.raises(PermissionPublishNotReadyError):
        await state.source_read_stamp(target=target, models=())
