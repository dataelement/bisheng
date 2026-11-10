"""F056 T023 — the audit page's application selector.

``AppDao.asearch_for_audit`` runs against a real (aiosqlite) ``app`` table:
name / slug substring, tenant scoping written out, deleted rows **included**,
bounded by ``limit``. The service test pins the role gate and that a tenant
admin's search never leaves their tenant (AC-31).
"""

from contextlib import asynccontextmanager, nullcontext
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.app import App, AppDao
from test.audit.conftest import make_user_payload


@pytest.fixture()
async def app_engine():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=[SQLModel.metadata.tables["app"]]))
    yield engine
    await engine.dispose()


@pytest.fixture()
async def app_db(app_engine):
    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=app_engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    return _session


async def _seed(app_db):
    rows = [
        App(id="a1", slug="sales-bot", name="Sales Bot", owner_user_id=7, tenant_id=2, state="online"),
        App(id="a2", slug="hr-helper", name="HR Helper", owner_user_id=7, tenant_id=2, state="deleted"),
        App(id="a3", slug="sales-report", name="Report", owner_user_id=8, tenant_id=3, state="stopped"),
        App(id="a4", slug="misc", name="Sales Misc", owner_user_id=8, tenant_id=3, state="draft"),
    ]
    async with app_db() as session:
        session.add_all(rows)
        await session.commit()


class TestAppDaoSearch:
    async def test_matches_name_or_slug_within_tenant(self, app_db):
        await _seed(app_db)
        async with app_db() as session:
            hits = await AppDao.asearch_for_audit(session, 2, "sales", 20)
        assert [a.id for a in hits] == ["a1"]

    async def test_deleted_rows_are_included(self, app_db):
        await _seed(app_db)
        async with app_db() as session:
            hits = await AppDao.asearch_for_audit(session, 2, "hr", 20)
        assert [(a.id, a.state) for a in hits] == [("a2", "deleted")]

    async def test_no_tenant_means_every_tenant(self, app_db):
        await _seed(app_db)
        async with app_db() as session:
            hits = await AppDao.asearch_for_audit(session, None, "sales", 20)
        assert {a.id for a in hits} == {"a1", "a3", "a4"}

    async def test_empty_keyword_lists_and_limit_caps(self, app_db):
        await _seed(app_db)
        async with app_db() as session:
            hits = await AppDao.asearch_for_audit(session, None, "", 2)
        assert len(hits) == 2


class TestSearchAuditAppsService:
    @pytest.fixture()
    def bind_service(self, monkeypatch, app_db):
        monkeypatch.setattr("bisheng.api.services.audit_log.get_async_db_session", app_db)
        monkeypatch.setattr("bisheng.api.services.audit_log.bypass_tenant_filter", lambda: nullcontext())

    async def test_tenant_admin_search_stays_in_tenant(self, bind_service, app_db):
        await _seed(app_db)
        user = make_user_payload(user_id=77, is_admin=True, is_global_super=False)
        with (
            patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
            patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=3),
        ):
            hits = await AuditLogService.search_audit_apps(user, "sales", 20)
        assert {h["id"] for h in hits} == {"a3", "a4"}
        assert hits[0].keys() == {"id", "name", "slug", "state", "tenant_id"}

    async def test_global_super_search_spans_tenants(self, bind_service, app_db):
        await _seed(app_db)
        user = make_user_payload(user_id=1, is_admin=True, is_global_super=True)
        with (
            patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
            patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=1),
        ):
            hits = await AuditLogService.search_audit_apps(user, "sales", 20)
        assert {h["id"] for h in hits} == {"a1", "a3", "a4"}

    async def test_plain_user_is_rejected(self, bind_service, monkeypatch):
        user = make_user_payload(user_id=500, is_admin=False, is_global_super=False)

        async def _no_menu(_user):
            return False

        async def _no_groups(_uid):
            return []

        monkeypatch.setattr(AuditLogService, "_user_has_log_web_menu", _no_menu)
        monkeypatch.setattr("bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group", _no_groups)
        with pytest.raises(UnAuthorizedError):
            await AuditLogService.search_audit_apps(user, "sales", 20)
