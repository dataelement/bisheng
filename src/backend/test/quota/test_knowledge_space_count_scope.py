"""Counting scope for the `knowledge_space` role quota.

The old raw-SQL template was `SELECT COUNT(*) FROM knowledge WHERE user_id=?`
with no `type` filter, so legacy document/QA knowledge bases (and the ghost
`type=2` rows the workstation still creates on file upload) counted against a
user's Knowledge Space quota. Counting moved to `_count_knowledge_space`, which
these tests pin by compiling the statement — no DB needed.
"""

import contextlib
from unittest.mock import patch


def _compiled(col: str, val) -> str:
    from bisheng.role.domain.services.quota_service import QuotaService

    stmt = QuotaService._knowledge_space_count_stmt(col, val)
    assert stmt is not None
    return str(stmt.compile(compile_kwargs={"literal_binds": True})).replace("\n", " ")


class TestCountScope:
    def test_not_registered_as_raw_template(self):
        """A template would silently lose the type filter and break DM8 quoting."""
        from bisheng.role.domain.services.quota_service import _RESOURCE_COUNT_TEMPLATES

        assert "knowledge_space" not in _RESOURCE_COUNT_TEMPLATES

    def test_dispatch_happens_before_template_lookup(self):
        """`_count_resource` must route knowledge_space to the ORM counter."""
        import inspect

        from bisheng.role.domain.services.quota_service import QuotaService

        src = inspect.getsource(QuotaService._count_resource)
        dispatch = src.index('resource_type == "knowledge_space"')
        lookup = src.index("_RESOURCE_COUNT_TEMPLATES.get")
        assert dispatch < lookup

    def test_user_count_filters_spaces_only(self):
        sql = _compiled("user_id", 11).upper()
        assert "KNOWLEDGE.TYPE = 3" in sql, sql
        assert "KNOWLEDGE.USER_ID = 11" in sql, sql

    def test_user_count_excludes_department_spaces(self):
        """Department spaces are created with the operator as user_id; counting
        them would burn an admin's personal quota (see exclude_department_spaces)."""
        sql = _compiled("user_id", 11).upper()
        assert "DEPARTMENT_KNOWLEDGE_SPACE.SPACE_ID" in sql, sql
        assert "NOT IN" in sql, sql

    def test_tenant_count_keeps_department_spaces(self):
        """They do occupy tenant capacity — excluding them would under-count."""
        sql = _compiled("tenant_id", 7).upper()
        assert "KNOWLEDGE.TYPE = 3" in sql, sql
        assert "DEPARTMENT_KNOWLEDGE_SPACE" not in sql, sql

    def test_tenant_count_uses_strict_equality(self):
        """AC-10: an IN list would double-count Root's shared rows for a Child."""
        where = _compiled("tenant_id", 7).upper().split("WHERE", 1)[-1]
        assert "TENANT_ID = 7" in where, where
        assert "TENANT_ID IN" not in where, where

    def test_unsupported_column_returns_none(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        assert QuotaService._knowledge_space_count_stmt("nope", 1) is None


class TestTenantFilterBypass:
    """The listener would silently zero out cross-tenant counts (fail-open).

    `knowledge` is a tenant-aware table and a single-table `select(func.count())`
    is matched by the listener's `get_final_froms()` path, so without the bypass
    Root aggregation over child tenants ANDs the *caller's* tenant onto the
    explicit predicate and returns 0 — quota then never fires.
    """

    async def test_count_runs_inside_bypass_tenant_filter(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        class _Result:
            def scalar(self):
                return 3

        class _Session:
            async def execute(self, _stmt):
                return _Result()

        @contextlib.asynccontextmanager
        async def _fake_session():
            yield _Session()

        with (
            patch(
                "bisheng.core.context.tenant.bypass_tenant_filter",
                return_value=contextlib.nullcontext(),
            ) as mock_bypass,
            patch("bisheng.core.database.get_async_db_session", _fake_session),
        ):
            got = await QuotaService._count_knowledge_space("tenant_id", 7)

        assert got == 3
        mock_bypass.assert_called_once()

    async def test_db_failure_is_logged_and_counted_as_zero(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        @contextlib.asynccontextmanager
        async def _boom():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        with patch("bisheng.core.database.get_async_db_session", _boom):
            assert await QuotaService._count_knowledge_space("user_id", 11) == 0
