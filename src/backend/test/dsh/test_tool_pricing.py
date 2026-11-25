"""Tests for unified tool pricing conversion, repository, API permissions/optimistic lock & tenant lifecycle (AC-01, AC-03..AC-10, AC-14)."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.credit_setting import DshCreditSetting
from bisheng.dsh.domain.models.tool_pricing import DshToolPricing
from bisheng.dsh.domain.models.unified_policy import UnifiedPolicyAudit
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType


@pytest.fixture
def pricing_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tool_pricing.db'}")
    tables = [
        Tenant.__table__,
        GptsToolsType.__table__,
        GptsTools.__table__,
        DshCreditSetting.__table__,
        DshToolPricing.__table__,
        UnifiedPolicyAudit.__table__,
    ]
    SQLModel.metadata.create_all(engine, tables=tables)
    token = current_tenant_id.set(1)
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    Tenant(id=1, tenant_name="Root", tenant_code="root"),
                    Tenant(id=2, tenant_name="Sub", tenant_code="sub"),
                    GptsToolsType(id=10, name="Search Group", is_preset=1, tenant_id=1),
                    GptsTools(id=101, name="联网搜索", tool_key="web_search", type=10, is_preset=1, tenant_id=1),
                    GptsTools(id=102, name="企业股东", tool_key="tianyancha_holder", type=10, is_preset=1, tenant_id=1),
                ]
            )
        yield engine
    finally:
        current_tenant_id.reset(token)
        engine.dispose()


def test_tool_pricing_conversion_money_and_credits():
    from bisheng.dsh.domain.services.tool_pricing import compute_tool_charge

    cny_setting = CreditSettingState(currency="CNY", credit_value_micro=10_000, usd_cny_rate_micro=6_720_000)

    # ¥5 / 1000 calls, 1 credit = ¥0.01 -> ¥0.005/call = 0.5 credits (500_000 microcredits)
    res_cny = compute_tool_charge(
        pricing_mode="MONEY", currency="CNY", price_micro=5_000_000, call_count=1000, setting=cny_setting
    )
    assert res_cny.cost_micro == 5_000
    assert res_cny.billed_tokens == 500_000
    assert res_cny.currency == "CNY"

    # $1 USD / 1 call, rate 7.2 CNY/USD -> ¥7.2 = 720 credits
    usd_setting = CreditSettingState(currency="CNY", credit_value_micro=10_000, usd_cny_rate_micro=7_200_000)
    res_usd = compute_tool_charge(
        pricing_mode="MONEY", currency="USD", price_micro=1_000_000, call_count=1, setting=usd_setting
    )
    assert res_usd.cost_micro == 7_200_000
    assert res_usd.billed_tokens == 720_000_000
    assert res_usd.currency == "CNY"

    # CREDITS mode: 2 credits / 1 call stays 2 credits regardless of credit_value_micro
    res_cred = compute_tool_charge(
        pricing_mode="CREDITS", currency=None, price_micro=2_000_000, call_count=1, setting=usd_setting
    )
    assert res_cred.billed_tokens == 2_000_000
    assert res_cred.cost_micro is None
    assert res_cred.currency is None

    # CREDITS ceil_div rounding up: 1 credit / 3 calls -> 0.333334 credits
    res_ceil = compute_tool_charge(
        pricing_mode="CREDITS", currency=None, price_micro=1_000_000, call_count=3, setting=cny_setting
    )
    assert res_ceil.billed_tokens == 333_334

    # Free tool: price 0 -> 0 billed
    res_free = compute_tool_charge(
        pricing_mode="MONEY", currency="CNY", price_micro=0, call_count=100, setting=cny_setting
    )
    assert res_free.billed_tokens == 0
    assert res_free.cost_micro == 0


def test_tool_pricing_input_validation_bounds():
    from bisheng.dsh.domain.schemas.tool_pricing import ToolPricingInput

    ok_empty = ToolPricingInput(pricing_mode="MONEY", currency="CNY", price="", call_count=1, version=0)
    assert ok_empty.price_micro == 0
    assert ok_empty.call_count == 1

    ok_none = ToolPricingInput(pricing_mode="CREDITS", price=None, version=0)
    assert ok_none.price_micro == 0
    assert ok_none.call_count == 1

    for bad in (
        {"pricing_mode": "MONEY", "currency": "CNY", "price": "1", "call_count": 0, "version": 0},
        {"pricing_mode": "MONEY", "currency": "CNY", "price": "1", "call_count": 1_000_001, "version": 0},
        {"pricing_mode": "MONEY", "currency": "CNY", "price": "-1", "call_count": 1, "version": 0},
        {"pricing_mode": "MONEY", "currency": "CNY", "price": "1.1234567", "call_count": 1, "version": 0},
        {"pricing_mode": "MONEY", "currency": "CNY", "price": "1000000", "call_count": 1, "version": 0},
        {"pricing_mode": "MONEY", "currency": None, "price": "1", "call_count": 1, "version": 0},
    ):
        with pytest.raises((ValidationError, ValueError)):
            ToolPricingInput(**bad)


def test_tool_pricing_repository_optimistic_lock_and_audit(pricing_db):
    from bisheng.dsh.domain.repositories.tool_pricing import ToolPricingRepository
    from bisheng.dsh.domain.schemas.tool_pricing import ToolPricingInput

    with Session(pricing_db) as session, session.begin():
        repo = ToolPricingRepository(session)
        saved = repo.save(
            tool_id=101,
            actor=99,
            value=ToolPricingInput(pricing_mode="MONEY", currency="CNY", price="5", call_count=1000, version=0),
        )
        assert saved["version"] == 1
        assert saved["price"] == "5"
        assert saved["call_count"] == 1000

        with pytest.raises(DshOperationConflictError):
            repo.save(
                tool_id=101,
                actor=100,
                value=ToolPricingInput(pricing_mode="CREDITS", price="2", call_count=1, version=0),
            )

        updated = repo.save(
            tool_id=101,
            actor=100,
            value=ToolPricingInput(pricing_mode="CREDITS", price="2", call_count=1, version=1),
        )
        assert updated["version"] == 2
        audits = list(session.scalars(select(UnifiedPolicyAudit).where(UnifiedPolicyAudit.resource == "tool_pricing:101")))
        assert len(audits) == 2


async def test_tool_pricing_http_endpoints_permissions_and_conflict(monkeypatch, pricing_db):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode import BaseErrorCode
    from bisheng.dsh.api.endpoints import tool_pricing as ep
    from bisheng.dsh.api.endpoints.admin import get_management
    from bisheng.dsh.api.router import router
    from bisheng.main import handle_http_exception

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, exception_handlers={BaseErrorCode: handle_http_exception})
    app.include_router(router, prefix="/api/v1")

    state = SimpleNamespace(is_admin=True, allow_auth=True, tenant_id=1, user_id=7)

    async def _get_user():
        return SimpleNamespace(user_id=state.user_id, tenant_id=state.tenant_id, is_admin=lambda: state.is_admin)

    async def _get_admin_user():
        if not state.is_admin:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Forbidden")
        return await _get_user()

    class _Mgmt:
        async def authorize(self, actor_id: int, tenant_id: int | None):
            if not state.allow_auth:
                from fastapi import HTTPException

                raise HTTPException(status_code=403, detail="Forbidden")
            return actor_id, tenant_id or 1

    app.dependency_overrides[UserPayload.get_login_user] = _get_user
    app.dependency_overrides[ep.admin_user] = _get_admin_user
    app.dependency_overrides[get_management] = lambda: _Mgmt()

    def _scope():
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            with Session(pricing_db) as s, s.begin():
                yield s

        return _cm()

    monkeypatch.setattr(ep, "_sync_session_scope", _scope)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r_save = await client.put(
            "/api/v1/dsh/admin/tool-pricing/101",
            json={"pricing_mode": "MONEY", "currency": "CNY", "price": "5", "call_count": 1000, "version": 0},
        )
        assert r_save.status_code == 200
        assert r_save.json()["data"]["version"] == 1

        # Stale version returns 26130
        r_conflict = await client.put(
            "/api/v1/dsh/admin/tool-pricing/101",
            json={"pricing_mode": "CREDITS", "price": "2", "call_count": 1, "version": 0},
        )
        assert r_conflict.json()["status_code"] == 26130

        r_list = await client.get("/api/v1/dsh/admin/tool-pricing")
        assert r_list.status_code == 200
        items = r_list.json()["data"]["items"]
        assert items["101"]["price"] == "5"
        assert items["101"]["call_count"] == 1000

        # Non-admin rejected on PUT
        state.is_admin = False
        r_denied = await client.put(
            "/api/v1/dsh/admin/tool-pricing/101",
            json={"pricing_mode": "CREDITS", "price": "1", "call_count": 1, "version": 1},
        )
        assert r_denied.status_code == 403


async def test_child_tenant_copy_and_tool_delete_sync(monkeypatch, pricing_db):
    from contextlib import asynccontextmanager

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.dsh.domain.repositories.tool_pricing import ToolPricingRepository
    from bisheng.dsh.domain.schemas.tool_pricing import ToolPricingInput
    from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    # Seed root prices for built-in tool 101 & existing child tool 202
    with Session(pricing_db) as s, s.begin():
        ToolPricingRepository(s).save(
            tool_id=101,
            actor=1,
            value=ToolPricingInput(pricing_mode="CREDITS", price="3", call_count=1, version=0),
        )
        s.add(GptsToolsType(id=20, name="Search Group", is_preset=1, tenant_id=2))
        # Pre-existing child tool for tool_key='tianyancha_holder' keeps its own price (0)
        s.add(GptsTools(id=202, name="企业股东", tool_key="tianyancha_holder", type=20, is_preset=1, tenant_id=2))

    async_engine = create_async_engine(str(pricing_db.url).replace("sqlite:///", "sqlite+aiosqlite:///"))
    async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _async_scope():
        async with async_session() as s:
            yield s

    monkeypatch.setattr("bisheng.workstation.domain.services.workstation_service.get_async_db_session", _async_scope)
    monkeypatch.setattr("bisheng.tool.domain.models.gpts_tools.get_async_db_session", _async_scope)
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.openfga, "enabled", False)

    res = await WorkStationService.acopy_root_builtin_tools_to_tenant(2)
    assert res["created_tools"] == 1  # only web_search copied

    from bisheng.core.context.tenant import bypass_tenant_filter

    with bypass_tenant_filter(), Session(pricing_db) as s:
        child_tool = s.exec(select(GptsTools).where(GptsTools.tenant_id == 2, GptsTools.tool_key == "web_search")).one()
        child_price = s.exec(
            select(DshToolPricing).where(DshToolPricing.tenant_id == 2, DshToolPricing.tool_id == child_tool.id)
        ).first()
        assert child_price is not None
        assert child_price.price_micro == 3_000_000
        assert child_price.version == 1
        # Existing child tool was not overwritten
        assert (
            s.exec(select(DshToolPricing).where(DshToolPricing.tenant_id == 2, DshToolPricing.tool_id == 202)).first()
            is None
        )

    # Root update does not propagate to child
    with Session(pricing_db) as s, s.begin():
        ToolPricingRepository(s).save(
            tool_id=101,
            actor=1,
            value=ToolPricingInput(pricing_mode="CREDITS", price="9", call_count=1, version=1),
        )
    with bypass_tenant_filter(), Session(pricing_db) as s:
        child_price = s.exec(
            select(DshToolPricing).where(DshToolPricing.tenant_id == 2, DshToolPricing.tool_id == child_tool.id)
        ).one()
        assert child_price.price_micro == 3_000_000

    # Custom API group delete clears tool pricing
    with bypass_tenant_filter(), Session(pricing_db) as s, s.begin():
        api_group = GptsToolsType(id=30, name="CustomAPI", is_preset=0, tenant_id=2)
        api_tool = GptsTools(id=301, name="op1", tool_key="tool_type_30_op1", type=30, is_preset=0, tenant_id=2)
        s.add_all([api_group, api_tool])
    with Session(pricing_db) as s, s.begin():
        t_token = current_tenant_id.set(2)
        try:
            ToolPricingRepository(s).save(
                tool_id=301,
                actor=1,
                value=ToolPricingInput(pricing_mode="MONEY", currency="CNY", price="1", call_count=1, version=0),
            )
        finally:
            current_tenant_id.reset(t_token)
    await GptsToolsDao.delete_tool_type(30)
    with bypass_tenant_filter(), Session(pricing_db) as s:
        assert s.exec(select(DshToolPricing).where(DshToolPricing.tool_id == 301)).first() is None
    await async_engine.dispose()
