"""Saved APP inspection retains frozen IDs and the actual management identity. 覆盖 AC: AC-37, AC-68, AC-79, AC-86, AC-89, AC-92."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish import composition
from bisheng.app_publish.domain.services import capability_bus_service as bus
from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.app_runtime.application import authorization
from bisheng.database.models.app import App
from bisheng.database.models.app_version import AppVersion
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_app_snapshot as fixtures

ctx = fixtures.ctx
resolving = fixtures.resolving
application = fixtures.application
writing = fixtures.writing
VERSION = fixtures.fixtures.VERSION


@pytest.fixture
async def saved(writing, monkeypatch):
    @asynccontextmanager
    async def factory():
        async with AsyncSession(writing.engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(bus, "get_async_db_session", factory)
    monkeypatch.setattr(bus, "get_model_name_resolution_port", lambda: writing.names, raising=False)
    # Metadata never creates an execution Plan or uses the cached model catalog.
    monkeypatch.setattr(writing.names, "aprepare_model_names_current", AsyncMock(side_effect=AssertionError("plan")))
    monkeypatch.setattr(bus, "model_capability_status", AsyncMock(side_effect=AssertionError("cached catalog")))
    composition.register()
    token = set_current_open_api_principal(None)
    try:
        yield writing
    finally:
        reset_current_open_api_principal(token)


async def test_saved_inspect_reports_frozen_identity_not_renamed_or_reused_name(saved):
    async with AsyncSession(saved.engine) as session, session.begin():
        await session.execute(sa.update(LLMModel).where(LLMModel.id == 11).values(model_name="renamed"))
        await session.execute(sa.update(LLMModel).where(LLMModel.id == 13).values(model_name="alpha"))
    rows = await bus.inspect_saved_capabilities("actual-app", VERSION, saved.user)
    model = next(row for row in rows if row.kind == "model")
    assert model.label == "alpha" and model.revoked
    assert model.detail["target_id"] == "11" and model.reason == "binding_identity_changed"
    assert next(row for row in rows if row.kind == "knowledge").detail["target_id"] == "7"


async def test_saved_inspect_keeps_deleted_knowledge_row_and_frozen_id(saved):
    async with AsyncSession(saved.engine) as session, session.begin():
        await session.execute(sa.delete(Knowledge).where(Knowledge.id == 7))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="knowledge_space",
                target_id="7",
                target_tenant_id=101,
                operation_id="real-delete",
                operation_type="delete",
                stage="deleted",
                actor_type="user",
                actor_id="4",
            )
        )
    rows = await bus.inspect_saved_capabilities("actual-app", VERSION, saved.user)
    knowledge = next(row for row in rows if row.kind == "knowledge")
    assert knowledge.label == "7" and knowledge.revoked
    assert knowledge.detail["target_id"] == "7" and knowledge.detail["state"] == "invalid_deleted"


async def test_name_observation_failure_keeps_all_rows_explicitly_not_ready(saved, monkeypatch):
    monkeypatch.setattr(
        saved.names, "ainspect_model_names_current", AsyncMock(side_effect=RuntimeError("catalog down")), raising=False
    )
    rows = await bus.inspect_saved_capabilities("actual-app", VERSION, saved.user)
    assert {(row.kind, row.label, row.detail["target_id"]) for row in rows} == {
        ("model", "alpha", "11"),
        ("knowledge", "7", "7"),
    }
    assert all(row.revoked and row.reason == "not_ready" for row in rows)


async def test_publish_status_forwards_actual_identity_and_exact_saved_uuid_and_crops_private_rows(saved, monkeypatch):
    async with AsyncSession(saved.engine) as session, session.begin():
        root = await session.get(App, "actual-app")
        version = await session.get(AppVersion, VERSION)
        app = SimpleNamespace(**{name: getattr(root, name) for name in App.model_fields})
        saved_version = SimpleNamespace(**{name: getattr(version, name) for name in AppVersion.model_fields})
    monkeypatch.setattr(PublishStatusService, "_load", AsyncMock(return_value=app))
    monkeypatch.setattr(PublishStatusService, "_require_viewer", AsyncMock())
    monkeypatch.setattr(PublishStatusService, "_latest_deployment", AsyncMock(return_value=None))
    monkeypatch.setattr(PublishStatusService, "_latest_instance", AsyncMock(return_value=None))
    monkeypatch.setattr(PublishStatusService, "_tier_payload", AsyncMock(return_value=None))
    monkeypatch.setattr(
        VersionService, "get_version", AsyncMock(side_effect=lambda app, key: saved_version if key else None)
    )
    actions = AsyncMock(return_value={app.id: frozenset({"edit"})})
    monkeypatch.setattr(authorization, "management_actions", actions)
    inspector = AsyncMock(
        return_value=(bus.CapabilityStatus("model", "alpha", "alpha", True, "not_ready", {"target_id": "11"}),)
    )
    monkeypatch.setattr(bus, "inspect_saved_capabilities", inspector, raising=False)
    result = await PublishStatusService.get_publish_status(app.id, actor=saved.user)
    inspector.assert_awaited_once_with(app.id, VERSION, saved.user)
    assert result["capabilities"][0]["target_id"] == "11"
    assert result["capabilities"][0]["reason"] == "not_ready"
    inspector.reset_mock()
    actions.return_value = {app.id: frozenset({"publish"})}
    assert (await PublishStatusService.get_publish_status(app.id, actor=saved.user))["capabilities"] == []
    inspector.assert_not_awaited()
