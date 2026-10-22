"""Saved-tool names are exact, tenant-local, active and unambiguous."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, create_engine

from bisheng.common.errcode.dsh import DshToolNotFoundError, DshToolServiceUnavailableError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    is_strict_tenant_filter,
    set_admin_scope_tenant_id,
    set_current_tenant_id,
)
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType
from bisheng.tool.domain.repositories import saved_tools
from bisheng.tool.domain.repositories.saved_tools import SavedToolRepository


def saved_tool_service():
    from bisheng.tool.domain.services.saved_tools import SavedToolService

    return SavedToolService()


NAME = "bs_web_search"
KEY = "tool_type_19_07140ad748b9c0136c5c791724416aec"


@pytest.fixture
def lookup_db(monkeypatch):
    engine = create_engine("sqlite://")
    GptsTools.__table__.create(engine)
    GptsToolsType.__table__.create(engine)
    with Session(engine) as session:

        class AsyncSession:
            async def exec(self, statement):
                assert get_current_tenant_id() == 1
                assert get_admin_scope_tenant_id() is None
                assert is_strict_tenant_filter()
                return session.exec(statement)

        @asynccontextmanager
        async def get_session():
            yield AsyncSession()

        monkeypatch.setattr(saved_tools, "get_async_db_session", get_session)
        yield session
    engine.dispose()


def add_tool(session, *, id=41, tenant=1, name=NAME, key=KEY, deleted=0):
    tool = GptsTools(id=id, name=name, tool_key=key, tenant_id=tenant, type=19, is_delete=deleted)
    session.add(tool)
    session.flush()
    return tool


def add_category(session, *, tenant=1, deleted=0):
    category = GptsToolsType(id=19, tenant_id=tenant, is_delete=deleted)
    session.add(category)
    session.flush()
    return category


async def test_name_resolves_differently_generated_key(lookup_db):
    tool = add_tool(lookup_db)
    category = add_category(lookup_db)
    assert await saved_tool_service()._load(1, NAME) == (tool, category)
    assert tool.tool_key != NAME


@pytest.mark.parametrize("name", [KEY, "missing", "bs_web", "bs_web_search%"])
async def test_missing_name_does_not_fall_back_to_key(lookup_db, name):
    add_tool(lookup_db)
    add_category(lookup_db)
    with pytest.raises(DshToolNotFoundError):
        await saved_tool_service()._load(1, name)


async def test_names_are_isolated_by_tenant(lookup_db):
    own = add_tool(lookup_db)
    add_tool(lookup_db, id=42, tenant=2)
    add_tool(lookup_db, id=43, tenant=2, key="another-key")
    add_category(lookup_db)
    tool, _ = await saved_tool_service()._load(1, NAME)
    assert tool is own


async def test_other_tenant_name_is_not_found(lookup_db):
    add_tool(lookup_db, tenant=2)
    add_category(lookup_db)
    with pytest.raises(DshToolNotFoundError):
        await saved_tool_service()._load(1, NAME)


async def test_same_tenant_active_duplicates_fail_closed(lookup_db):
    add_tool(lookup_db)
    add_tool(lookup_db, id=42, key="another-key")
    add_category(lookup_db)
    with pytest.raises(DshToolNotFoundError):
        await saved_tool_service()._load(1, NAME)


async def test_deleted_same_name_does_not_make_active_match_ambiguous(lookup_db):
    own = add_tool(lookup_db)
    add_tool(lookup_db, id=42, key="deleted-key", deleted=1)
    add_category(lookup_db)
    tool, _ = await saved_tool_service()._load(1, NAME)
    assert tool is own


async def test_deleted_only_name_is_not_found(lookup_db):
    add_tool(lookup_db, deleted=1)
    add_category(lookup_db)
    with pytest.raises(DshToolNotFoundError):
        await saved_tool_service()._load(1, NAME)


@pytest.mark.parametrize("category", ["missing", "other_tenant", "deleted"])
async def test_invalid_category_is_rejected(lookup_db, category):
    add_tool(lookup_db)
    if category != "missing":
        add_category(lookup_db, tenant=2 if category == "other_tenant" else 1, deleted=int(category == "deleted"))
    with pytest.raises(DshToolNotFoundError):
        await saved_tool_service()._load(1, NAME)


@pytest.mark.parametrize("fails", [False, True])
async def test_repository_restores_ambient_tenant_context(lookup_db, monkeypatch, fails):
    add_tool(lookup_db)
    add_category(lookup_db)
    if fails:

        @asynccontextmanager
        async def broken_session():
            raise SQLAlchemyError("database unavailable")
            yield

        monkeypatch.setattr(saved_tools, "get_async_db_session", broken_session)
    tenant_token = set_current_tenant_id(7)
    admin_token = set_admin_scope_tenant_id(8)
    try:
        if fails:
            with pytest.raises(SQLAlchemyError):
                await SavedToolRepository.load_by_name(1, NAME)
        else:
            await SavedToolRepository.load_by_name(1, NAME)
        assert get_current_tenant_id() == 8
        assert get_admin_scope_tenant_id() == 8
        assert not is_strict_tenant_filter()
    finally:
        admin_token.var.reset(admin_token)
        tenant_token.var.reset(tenant_token)


@pytest.mark.parametrize("tool_patch,category_patch", [({"tenant_id": 2}, {}), ({"is_delete": 1}, {})])
async def test_service_keeps_defensive_tool_checks(monkeypatch, tool_patch, category_patch):
    tool = SimpleNamespace(tenant_id=1, is_delete=0)
    category = SimpleNamespace(tenant_id=1, is_delete=0)
    tool.__dict__.update(tool_patch)
    category.__dict__.update(category_patch)
    monkeypatch.setattr(SavedToolRepository, "load_by_name", AsyncMock(return_value=(tool, category)))
    with pytest.raises(DshToolNotFoundError):
        await saved_tool_service()._load(1, NAME)


@pytest.mark.parametrize(
    "case,expected_id",
    [
        ("different_key", 41),
        ("other_tenant_duplicates", 41),
        ("other_tenant_only", None),
        ("same_tenant_duplicates", None),
        ("deleted_duplicate", 41),
        ("deleted_only", None),
        ("key_not_name", None),
        ("missing", None),
        ("partial", None),
    ],
)
async def test_repository_name_resolution(lookup_db, case, expected_id):
    add_tool(lookup_db, tenant=2 if case == "other_tenant_only" else 1, deleted=int(case == "deleted_only"))
    add_category(lookup_db)
    if case in {"other_tenant_duplicates", "same_tenant_duplicates", "deleted_duplicate"}:
        add_tool(
            lookup_db,
            id=42,
            key="another-key",
            tenant=2 if case == "other_tenant_duplicates" else 1,
            deleted=int(case == "deleted_duplicate"),
        )
    if case == "other_tenant_duplicates":
        add_tool(lookup_db, id=43, key="third-key", tenant=2)
    name = {"key_not_name": KEY, "missing": "missing", "partial": "bs_web"}.get(case, NAME)
    tool, category = await SavedToolRepository.load_by_name(1, name)
    assert (tool.id if tool else None) == expected_id
    assert (category.id if category else None) == (19 if expected_id else None)


async def test_service_maps_database_failure(monkeypatch):
    monkeypatch.setattr(SavedToolRepository, "load_by_name", AsyncMock(side_effect=SQLAlchemyError("unavailable")))
    with pytest.raises(DshToolServiceUnavailableError):
        await saved_tool_service()._load(1, NAME)
