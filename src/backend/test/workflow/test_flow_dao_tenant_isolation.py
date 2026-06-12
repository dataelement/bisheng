"""Regression tests for FlowDao's UNION ALL tenant-isolation leak.

The four ``select(Flow) UNION ALL select(Assistant) AS sub`` queries on
``FlowDao`` (``get_all_apps`` / ``aget_all_apps`` / ``get_all_app_by_time_range_sync``
/ ``get_first_app``) historically escaped the ``do_orm_execute`` auto-filter
because the outer SELECT only exposes a Subquery — the listener never saw
the underlying tenant-aware tables and injected no WHERE clause, leaking
cross-tenant rows on the list endpoint while the per-id detail endpoint
remained correctly filtered.

These tests assert the compiled SQL of ``_build_apps_subquery`` contains the
expected ``tenant_id`` predicate on both inner SELECTs under each tenant
context shape, and that ``build_tenant_filter_clause`` matches the event
listener's bypass / visible-ids / single-tenant semantics.
"""

from sqlalchemy.sql import false as sql_false
from sqlmodel import select

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.database.models.assistant import Assistant
from bisheng.database.models.flow import Flow, FlowDao


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={'literal_binds': True}))


def _reset_tenant_context(tenant_token, visible_token):
    current_tenant_id.reset(tenant_token)
    visible_tenant_ids.reset(visible_token)


class TestBuildAppsSubquery:
    """``FlowDao._build_apps_subquery`` must inject the per-table tenant
    predicate even though the outer SELECT hides Flow/Assistant behind a
    Subquery."""

    def test_leaf_tenant_emits_in_list_on_both_inner_selects(self):
        tenant_token = set_current_tenant_id(5)
        visible_token = set_visible_tenant_ids(frozenset({5, 1}))
        try:
            sql = _compiled_sql(select(FlowDao._build_apps_subquery().c.id))
        finally:
            _reset_tenant_context(tenant_token, visible_token)

        assert 'flow.tenant_id IN (1, 5)' in sql
        assert 'assistant.tenant_id IN (1, 5)' in sql

    def test_root_tenant_with_no_visible_emits_equality(self):
        # Super admin shape: current=1, visible=None. Event listener falls
        # through to ``WHERE tenant_id = current``; the helper must mirror.
        tenant_token = set_current_tenant_id(1)
        visible_token = set_visible_tenant_ids(None)
        try:
            sql = _compiled_sql(select(FlowDao._build_apps_subquery().c.id))
        finally:
            _reset_tenant_context(tenant_token, visible_token)

        assert 'flow.tenant_id = 1' in sql
        assert 'assistant.tenant_id = 1' in sql

    def test_bypass_emits_no_tenant_predicate(self):
        tenant_token = set_current_tenant_id(1)
        visible_token = set_visible_tenant_ids(None)
        try:
            with bypass_tenant_filter():
                sql = _compiled_sql(select(FlowDao._build_apps_subquery().c.id))
        finally:
            _reset_tenant_context(tenant_token, visible_token)

        assert 'tenant_id' not in sql


class TestBuildTenantFilterClause:
    """Unit-level checks that the helper mirrors the event listener exactly
    so manual-injection sites stay in lockstep with auto-injection."""

    def test_returns_none_when_bypassed(self):
        tenant_token = set_current_tenant_id(1)
        visible_token = set_visible_tenant_ids(None)
        try:
            with bypass_tenant_filter():
                assert build_tenant_filter_clause(Flow.tenant_id) is None
        finally:
            _reset_tenant_context(tenant_token, visible_token)

    def test_empty_visible_set_emits_false(self):
        # An empty IN-list collapses to ``false()`` — matches event listener
        # behavior for the tenant_id=0 / pending-selection case.
        tenant_token = set_current_tenant_id(0)
        visible_token = set_visible_tenant_ids(frozenset())
        try:
            clause = build_tenant_filter_clause(Flow.tenant_id)
        finally:
            _reset_tenant_context(tenant_token, visible_token)

        assert str(clause) == str(sql_false())

    def test_single_visible_emits_equality(self):
        tenant_token = set_current_tenant_id(1)
        visible_token = set_visible_tenant_ids(frozenset({1}))
        try:
            clause = build_tenant_filter_clause(Assistant.tenant_id)
        finally:
            _reset_tenant_context(tenant_token, visible_token)

        sql = str(clause.compile(compile_kwargs={'literal_binds': True}))
        assert sql == 'assistant.tenant_id = 1'
