"""F118 CURRENT Catalog must match its published canonical SQL contents."""

import json
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.openfga.manager import FGAManager
from bisheng.permission.application import control_state
from bisheng.permission.application.catalog_api import SqlCatalogState
from bisheng.permission.application.process_runtime import bind_f048_process_runtime
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import (
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogRelease,
    PermissionModel,
    PermissionModelAction,
)
from bisheng.permission.domain.services.catalog_policy import derive_action_release
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from test.knowledge_unification.test_perm_control_snapshot import seed
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory


def release_checksum(actions, models):
    value = {"actions": actions.checksum, "models": models.checksum}
    return sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


async def canonical_seed(factory, *, narrow=False, disabled=False):
    release_id, actions, _ = await seed(factory)
    if narrow:
        actions = derive_action_release(
            replace(row, resource_types=frozenset({"tool"})) if row.code == "edit" else row for row in actions.actions
        )
    if disabled:
        actions = derive_action_release(replace(row, active=False) for row in actions.actions)
    models = derive_permission_models(
        actions,
        custom_models=(
            CustomModelSelection(
                "legacy",
                "Legacy",
                ("download",),
                active=not disabled,
                visibility_only_resource_types=("tool",),
                visibility_level=3,
            ),
        ),
        standard_allow_same_level={"owner": False} if disabled else {},
    )
    async with factory() as session:
        await SqlCatalogState._replace_children(
            session, release_id=release_id, action_release=actions, model_release=models
        )
        release = await session.get(PermissionCatalogRelease, release_id)
        release.checksum = release_checksum(actions, models)
        await session.commit()
    return release_id


async def corrupt_scope(factory, *, all_rows):
    async with factory() as session:
        if all_rows:
            await session.execute(delete(PermissionActionResourceScope))
        else:
            action = (
                await session.execute(select(PermissionAction).where(PermissionAction.code == "edit"))
            ).scalar_one()
            await session.execute(
                delete(PermissionActionResourceScope).where(
                    PermissionActionResourceScope.action_id == action.id,
                    PermissionActionResourceScope.resource_type == "dashboard",
                )
            )
        await session.commit()


@pytest.mark.parametrize("all_rows", [True, False])
async def test_scope_loss_with_unchanged_current_pins_is_rejected(session_factory, monkeypatch, all_rows):
    await canonical_seed(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    await control_state.SqlPermissionControlState().current_catalog()
    await corrupt_scope(session_factory, all_rows=all_rows)
    with pytest.raises(PermissionPublishNotReadyError):
        await control_state.SqlPermissionControlState().current_catalog()


@pytest.mark.parametrize("corruption", ["derived-level", "model-action", "model-row"])
async def test_stored_models_must_match_the_published_derivation(session_factory, monkeypatch, corruption):
    await canonical_seed(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    async with session_factory() as session:
        model = (
            await session.execute(select(PermissionModel).where(PermissionModel.model_key == "viewer"))
        ).scalar_one()
        if corruption == "derived-level":
            model.derived_level = 4
        elif corruption == "model-action":
            await session.execute(delete(PermissionModelAction).where(PermissionModelAction.model_id == model.id))
        else:
            await session.execute(delete(PermissionModel).where(PermissionModel.id == model.id))
        await session.commit()
    with pytest.raises(PermissionPublishNotReadyError):
        await control_state.SqlPermissionControlState().current_catalog()


async def test_valid_published_narrow_scopes_are_not_expanded(session_factory, monkeypatch):
    await canonical_seed(session_factory, narrow=True)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    current = await control_state.SqlPermissionControlState().current_catalog()
    assert dict(current.action_resource_scopes)["edit"] == ("tool",)
    editor = next(row.snapshot for row in current.models if row.snapshot.model_key == "editor")
    assert "edit" not in current.model_for_target(editor, resource_type="workflow").action_codes


async def test_valid_disabled_catalog_can_have_verified_empty_effective_scope(session_factory, monkeypatch):
    await canonical_seed(session_factory, disabled=True)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    current = await control_state.SqlPermissionControlState().current_catalog()
    assert current.action_resource_scopes == ()
    assert all(not model.snapshot.action_codes for model in current.models)


async def test_real_process_heartbeat_stops_ready_after_sql_scope_loss(session_factory, monkeypatch):
    await canonical_seed(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    service = object.__new__(F048PermissionRuntime)
    service._state = control_state.SqlPermissionControlState()
    service._client = SimpleNamespace(store_id="s1", model_id="m1")
    transport = SimpleNamespace(health=AsyncMock(return_value=True))
    heartbeat = SimpleNamespace(publish=AsyncMock(), remove=AsyncMock())
    manager = FGAManager(
        SimpleNamespace(dual_model_mode=False, legacy_model_id=None, recent_consistency_window_seconds=5),
        heartbeat_store=heartbeat,
    )
    manager._instance = transport
    manager._runtime_store_id, manager._runtime_model_id, manager._runtime_model_checksum = "s1", "m1", "a" * 64
    assert (await bind_f048_process_runtime(manager, service))["ready"]
    assert heartbeat.publish.await_count == 1
    await corrupt_scope(session_factory, all_rows=True)
    assert not await manager.heartbeat()
    assert not manager.readiness()["ready"]
    assert heartbeat.publish.await_count == 1 and heartbeat.remove.await_count == 1
