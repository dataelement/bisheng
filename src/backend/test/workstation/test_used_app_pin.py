"""Persisted pin/unpin regressions using the real app and user-link DAOs."""

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.v1.schemas import UsedAppPin
from bisheng.common.errcode.workstation import UsedAppNotFoundError, UsedAppNotOnlineError
from bisheng.database.models import flow as flow_mod
from bisheng.database.models import user_link as link_mod
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow
from bisheng.workstation.api.endpoints import apps as apps_mod


@pytest.fixture
async def pin_store(tmp_path, monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    tenant_token = set_current_tenant_id(1)
    database = tmp_path / "pins.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    SQLModel.metadata.create_all(engine, tables=[Flow.__table__, Assistant.__table__, link_mod.UserLink.__table__])
    with Session(engine) as session:
        session.add(Assistant(id="asst-1", name="Assistant", tenant_id=1, status=2))
        session.add(Assistant(id="asst-offline", name="Offline", tenant_id=1, status=1))
        session.add(Assistant(id="asst-deleted", name="Deleted", tenant_id=1, status=2, is_delete=1))
        session.add(Assistant(id="asst-other-tenant", name="Other", tenant_id=2, status=2))
        session.add(Flow(id="wf-1", name="Workflow", tenant_id=1, status=2, flow_type=10))
        session.add(Flow(id="unsupported", name="Other type", tenant_id=1, status=2, flow_type=20))
        session.commit()
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{database}")

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine) as session:
            yield session

    @contextmanager
    def sync_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(flow_mod, "get_async_db_session", async_session)
    monkeypatch.setattr(link_mod, "get_sync_db_session", sync_session)
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(apps_mod, "check_business_action", check)
    monkeypatch.setattr(
        apps_mod.WorkFlowService, "filter_apps_by_action", AsyncMock(side_effect=lambda u, rows, a: rows)
    )
    monkeypatch.setattr(apps_mod.WorkFlowService, "aenrich_apps_can_share", AsyncMock(side_effect=lambda u, rows: rows))
    monkeypatch.setattr(apps_mod.WorkFlowService, "get_logo_share_link", lambda logo: logo)
    monkeypatch.setattr(apps_mod.TagDao, "get_tags_by_resource", lambda *args: {})
    now = datetime(2026, 10, 28, 12)
    monkeypatch.setattr(
        apps_mod.MessageSessionDao,
        "get_user_used_apps",
        AsyncMock(
            return_value=[
                ("wf-1", now),
                ("asst-1", now - timedelta(hours=1)),
            ]
        ),
    )
    yield SimpleNamespace(user=SimpleNamespace(user_id=7, tenant_id=1), check=check)
    await async_engine.dispose()
    engine.dispose()
    current_tenant_id.reset(tenant_token)


@pytest.mark.parametrize("app_id,resource_type", [("asst-1", "assistant"), ("wf-1", "workflow")])
async def test_pin_refresh_unpin_round_trip(pin_store, app_id, resource_type):
    user = pin_store.user
    reply = await apps_mod.pin_used_app(login_user=user, data=UsedAppPin(flow_id=app_id))
    assert reply.status_code == 200
    pin_store.check.assert_awaited_once_with(user, resource_type=resource_type, resource_id=app_id, action="use")
    # Each read opens a fresh database session, matching a page reload.
    for _ in range(2):
        page = await apps_mod.get_used_apps(login_user=user, page=1, limit=1)
        assert page.data["total"] == 2
        assert [(row["id"], row["is_pinned"]) for row in page.data["list"]] == [(app_id, True)]
    other_user = SimpleNamespace(user_id=8, tenant_id=1)
    other_page = await apps_mod.get_used_apps(login_user=other_user)
    assert all(row["is_pinned"] is False for row in other_page.data["list"])
    await apps_mod.unpin_used_app(login_user=user, flow_id=app_id)
    restored = await apps_mod.get_used_apps(login_user=user)
    assert [row["id"] for row in restored.data["list"]] == ["wf-1", "asst-1"]
    assert all(row["is_pinned"] is False for row in restored.data["list"])
    assert link_mod.UserLinkDao.get_user_link(user.user_id, [apps_mod.USED_APP_PIN_TYPE]) == []


@pytest.mark.parametrize(
    "app_id,error",
    [
        ("missing", UsedAppNotFoundError),
        ("asst-deleted", UsedAppNotFoundError),
        ("asst-other-tenant", UsedAppNotFoundError),
        ("unsupported", UsedAppNotFoundError),
        ("asst-offline", UsedAppNotOnlineError),
    ],
)
async def test_invalid_app_preserves_empty_pin_store(pin_store, app_id, error):
    with pytest.raises(error):
        await apps_mod.pin_used_app(login_user=pin_store.user, data=UsedAppPin(flow_id=app_id))
    assert pin_store.check.await_count == 0
    assert link_mod.UserLinkDao.get_user_link(pin_store.user.user_id, [apps_mod.USED_APP_PIN_TYPE]) == []


async def test_denied_assistant_preserves_empty_pin_store(pin_store):
    pin_store.check.return_value = False
    reply = await apps_mod.pin_used_app(login_user=pin_store.user, data=UsedAppPin(flow_id="asst-1"))
    assert reply.status_code == 403
    assert link_mod.UserLinkDao.get_user_link(pin_store.user.user_id, [apps_mod.USED_APP_PIN_TYPE]) == []
