"""Knowledge-space quota schema and strict resource-tenant predicates.

F009 moved these metrics to QuotaRepository. F118 migration-origin exemptions
and department exclusions remain personal-only; unknown usage is never zero.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.tenant_quota import QuotaUsageUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.role.domain.repositories import quota_repository


def compiled(*, user_id=None):
    statement = quota_repository.usage_statement("knowledge_space", 7, user_id=user_id)
    return str(statement.compile(compile_kwargs={"literal_binds": True})).replace("\n", " ").upper()


def test_user_count_filters_spaces_and_exact_resource_tenant():
    sql = compiled(user_id=11)
    assert "KNOWLEDGE.TYPE = 3" in sql and "KNOWLEDGE.USER_ID = 11" in sql
    assert "KNOWLEDGE.TENANT_ID = 7" in sql and "TENANT_ID IN" not in sql


def test_user_count_excludes_department_spaces_and_migration_origins():
    sql = compiled(user_id=11)
    assert "DEPARTMENT_KNOWLEDGE_SPACE.SPACE_ID" in sql and "EXISTS" in sql
    assert "MIGRATION_ORIGIN" in sql


def test_tenant_count_keeps_migrated_and_department_spaces():
    sql = compiled()
    assert "KNOWLEDGE.TYPE = 3" in sql and "KNOWLEDGE.TENANT_ID = 7" in sql
    assert "MIGRATION_ORIGIN" not in sql and "DEPARTMENT_KNOWLEDGE_SPACE" not in sql


async def test_count_binds_its_resource_tenant_instead_of_callers_scope(monkeypatch):
    @asynccontextmanager
    async def sessions():
        assert get_current_tenant_id() == 7
        result = MagicMock()
        result.one.return_value = 3
        yield type("Session", (), {"exec": AsyncMock(return_value=result)})()

    monkeypatch.setattr(quota_repository, "get_async_db_session", sessions)
    with tenant_execution_scope(1):
        assert await quota_repository.QuotaRepository.count(7, "knowledge_space") == 3
        assert get_current_tenant_id() == 1


async def test_db_failure_is_unavailable_instead_of_zero(monkeypatch):
    @asynccontextmanager
    async def sessions():
        raise RuntimeError("fixture database unavailable")
        yield

    monkeypatch.setattr(quota_repository, "get_async_db_session", sessions)
    with pytest.raises(QuotaUsageUnavailableError):
        await quota_repository.QuotaRepository.count(7, "knowledge_space", user_id=11)
