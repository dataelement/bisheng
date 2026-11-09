"""T977: existing floor survives real Catalog edits; no new issuance or FGA writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.permission.application import control_state
from bisheng.permission.application.catalog_api import F048CatalogApi, SqlCatalogState
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import PermissionCatalogRelease, PermissionModel
from bisheng.permission.domain.schemas import CatalogDraftRequest, VerifiedPermissionTarget
from bisheng.permission.domain.services.catalog_service import CatalogImpactSummary, CatalogService
from bisheng.permission.domain.services.grant_service import GrantCapability, GrantService
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot, GrantSourceService
from bisheng.permission.domain.services.model_policy import CustomModelSelection, derive_permission_models
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.migration.f048_model_mapper import build_initial_action_release
from test.knowledge_unification.test_perm_catalog_integrity import release_checksum
from test.knowledge_unification.test_perm_control_snapshot import seed
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory
from test.permission.test_f048_catalog_api import _app


async def existing_catalog(factory, floor=3):
    release_id, actions, _ = await seed(factory)
    models = derive_permission_models(
        actions,
        custom_models=(
            CustomModelSelection(
                "legacy",
                "Legacy",
                ("download",),
                visibility_only_resource_types=("tool",),
                visibility_level=3,
                retired_use_level_floor=floor,
            ),
        ),
    )
    # This fixture represents an already-persisted controlled fact. The API
    # under test may carry it but cannot issue it from HTTP or infer it.
    async with factory() as session:
        row = (
            await session.execute(sa.select(PermissionModel).where(PermissionModel.model_key == "legacy"))
        ).scalar_one()
        await session.execute(
            sa.update(PermissionModel.__table__)
            .where(PermissionModel.id == row.id)
            .values(retired_use_level_floor=floor, derived_level=3 if floor else 1)
        )
        current = await session.get(PermissionCatalogRelease, release_id)
        current.checksum = release_checksum(actions, models)
        await session.commit()
    return release_id, actions, models


def api(factory):
    state = SqlCatalogState(session_factory=factory)
    state.grant_references = AsyncMock(return_value={})
    state.model_reference_summaries = AsyncMock(return_value={})
    impact = CatalogImpactSummary("b" * 64, 0, 0, 0, 0, 0)
    service = CatalogService(
        state=state, impact=SimpleNamespace(analyze_draft=AsyncMock(return_value=impact)), projector=object()
    )
    result = F048CatalogApi(state=state, service=service)
    result._impact = SimpleNamespace(describe=AsyncMock(return_value=impact))
    return result


async def mark_current_fixture(factory, old_id, new_id):
    # SQL pointer advancement only enables another native draft. It is not a
    # claim of external projection, active-marker switching or publication.
    async with factory() as session:
        old = await session.get(PermissionCatalogRelease, old_id)
        old.status = "RETIRED"
        new = await session.get(PermissionCatalogRelease, new_id)
        new.status = "CURRENT"
        await session.commit()


@pytest.mark.parametrize("floor", [None, 3])
async def test_native_load_save_reload_and_private_current_response(session_factory, monkeypatch, floor):
    ident, actions, models = await existing_catalog(session_factory, floor)
    catalog_api = api(session_factory)
    loaded = await catalog_api._state.load_snapshot(ident)
    model = next(row for row in loaded.model_release.models if row.model_key == "legacy")
    assert model.retired_use_level_floor == floor and model.derived_level == (3 if floor else 1)
    assert loaded.model_release.checksum == models.checksum
    async with session_factory() as session:
        await SqlCatalogState._replace_children(session, release_id=ident, action_release=actions, model_release=models)
        await session.commit()
    async with session_factory() as session:
        raw = (
            await session.execute(sa.select(PermissionModel).where(PermissionModel.model_key == "legacy"))
        ).scalar_one()
        assert raw.retired_use_level_floor == floor
    payload = await catalog_api.get_current()
    assert all("retired_use_level_floor" not in model for model in payload["models"])
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    current = await control_state.SqlPermissionControlState().current_catalog()
    assert next(model.snapshot.derived_level for model in current.models if model.snapshot.model_key == "legacy") == (
        3 if floor else 1
    )


async def test_existing_floor_survives_real_edit_save_reload_cycles_and_new_models_keep_none(
    session_factory, monkeypatch
):
    base, _, _ = await existing_catalog(session_factory)
    catalog_api = api(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    batches = (
        [{"type": "UPDATE_MODEL", "model_key": "legacy", "name": "Renamed", "action_codes": ["download", "rename"]}],
        [
            {"type": "UPDATE_MODEL", "model_key": "legacy", "action_codes": ["download"]},
            {"type": "CREATE_MODEL", "model_key": "ordinary", "name": "Ordinary", "action_codes": ["download"]},
        ],
        [{"type": "SET_MODEL_ACTIVE", "model_key": "legacy", "active": False}],
    )
    for index, changes in enumerate(batches):
        response = await catalog_api.create_draft(
            request=CatalogDraftRequest.model_validate(
                {"base_release_id": base, "idempotency_key": f"floor-cycle-{index}", "changes": changes}
            ),
            operator_id=7,
        )
        loaded = await catalog_api._state.load_snapshot(response["draft_id"])
        model = next(row for row in loaded.model_release.models if row.model_key == "legacy")
        assert model.retired_use_level_floor == model.derived_level == 3
        assert model.visibility_only_resource_types == ("tool",) and model.visibility_level == 3
        assert all(
            row.retired_use_level_floor is None for row in loaded.model_release.models if row.model_key != "legacy"
        )
        await mark_current_fixture(session_factory, base, response["draft_id"])
        base = response["draft_id"]
        current = await control_state.SqlPermissionControlState().current_catalog()
        assert next(row.snapshot.derived_level for row in current.models if row.snapshot.model_key == "legacy") == 3


@pytest.mark.parametrize("kind", ["CREATE_MODEL", "UPDATE_MODEL"])
async def test_real_http_validation_rejects_caller_floor_before_api(kind):
    sentinel = SimpleNamespace(create_draft=AsyncMock(side_effect=AssertionError("caller floor reached API")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(sentinel)), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/permissions/catalog/drafts",
            json={
                "base_release_id": 1,
                "idempotency_key": "forged-floor",
                "changes": [
                    {
                        "type": kind,
                        "model_key": "legacy",
                        "name": "Legacy",
                        "action_codes": ["download"],
                        "retired_use_level_floor": 3,
                    }
                ],
            },
        )
    assert response.status_code == 422
    sentinel.create_draft.assert_not_awaited()


async def test_original_reservation_and_edit_failure_order_is_preserved(session_factory):
    base, _, _ = await existing_catalog(session_factory)
    catalog_api = api(session_factory)
    request = CatalogDraftRequest.model_validate(
        {
            "base_release_id": base,
            "idempotency_key": "failed",
            "changes": [{"type": "ASSIGN_ACTION_LEVEL", "action_code": "unknown", "level": 1}],
        }
    )
    with pytest.raises(InvalidCatalogActionError):
        await catalog_api.create_draft(request=request, operator_id=7)
    catalog_api._state.reserve_draft = AsyncMock(side_effect=PermissionVersionConflictError())
    catalog_api._state.load_snapshot = AsyncMock(side_effect=AssertionError("read before failed reservation"))
    with pytest.raises(PermissionVersionConflictError):
        await catalog_api.create_draft(request=request, operator_id=7)
    catalog_api._state.load_snapshot.assert_not_awaited()


@pytest.mark.parametrize("corruption", ["remove", "mismatch", "outside", "derived", "standard"])
async def test_current_floor_tamper_is_rejected(session_factory, monkeypatch, corruption):
    await existing_catalog(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    await control_state.SqlPermissionControlState().current_catalog()
    async with session_factory() as session:
        key = "viewer" if corruption == "standard" else "legacy"
        row = (await session.execute(sa.select(PermissionModel).where(PermissionModel.model_key == key))).scalar_one()
        changes = {
            "remove": {"retired_use_level_floor": None},
            "mismatch": {"retired_use_level_floor": 2},
            "outside": {"retired_use_level_floor": 5},
            "derived": {"derived_level": 1},
            "standard": {"retired_use_level_floor": 1},
        }[corruption]
        await session.execute(
            sa.update(PermissionModel.__table__).where(PermissionModel.id == row.id).values(**changes)
        )
        await session.commit()
    with pytest.raises(PermissionPublishNotReadyError):
        await control_state.SqlPermissionControlState().current_catalog()


async def test_standalone_snapshot_does_not_silently_drop_standard_floor(session_factory):
    base, _, _ = await existing_catalog(session_factory, None)
    async with session_factory() as session:
        await session.execute(
            sa.update(PermissionModel.__table__)
            .where(PermissionModel.model_key == "viewer")
            .values(retired_use_level_floor=1)
        )
        await session.commit()
    with pytest.raises((ValueError, PermissionPublishNotReadyError)):
        await SqlCatalogState(session_factory=session_factory).load_snapshot(base)


async def test_non_admin_runtime_uses_current_floor_and_does_not_grant_it_at_level_two(session_factory, monkeypatch):
    await existing_catalog(session_factory)
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    state = control_state.SqlPermissionControlState()
    state.load_grants = AsyncMock(return_value=())
    state.load_visible_sources = AsyncMock(return_value=())
    runtime = object.__new__(F048PermissionRuntime)
    runtime._state = state
    runtime._client = SimpleNamespace(store_id="s1", model_id="m1")
    runtime._require_current_target = AsyncMock(return_value=SimpleNamespace(mode="CUSTOM"))
    runtime._grant_capabilities = AsyncMock(
        return_value=(
            GrantCapability(
                GrantModelSnapshot("effective-grant-level-2", True, ("manage_permission",), 2, True),
                "transport-level-2",
            ),
        )
    )
    runtime._grants = GrantService(source_service=GrantSourceService(), projection=object(), state=object())
    actor = PermissionActor(user_id=42, current_tenant_id=101)
    assert not actor.super_admin and not actor.tenant_admin_tenant_ids
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=101,
        resource_type="knowledge_file",
        resource_id="7",
        resource_version=1,
        context_version="native-floor",
    )
    context = await runtime.build_grant_context(actor=actor, target=target)
    assert not context.system_authorized
    assert next(model.derived_level for model in context.models if model.model_key == "legacy") == 3
    assert "legacy" not in {model.model_key for model in runtime._grants.grantable_models(context)}
    runtime._grant_capabilities.assert_awaited_once()


def test_none_model_checksum_stays_byte_identical():
    models = derive_permission_models(
        build_initial_action_release(), custom_models=(CustomModelSelection("ordinary", "Ordinary", ("download",)),)
    )
    assert models.checksum == "6c0df18f320a4ced9f6ab75d84097171891f38867bd6142cd1750b8d7092c83d"
