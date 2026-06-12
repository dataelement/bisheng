"""Tests for F012 ContextVar extensions in bisheng.core.context.tenant.

Validates:
- v2.5.0 public signatures still work (get_current_tenant_id,
  set_current_tenant_id, bypass_tenant_filter, is_tenant_filter_bypassed).
- The 4 new ContextVars (visible_tenant_ids, _strict_tenant_filter,
  _admin_scope_tenant_id, _is_management_api) default to None/False.
- ``strict_tenant_filter()`` context manager enters/exits correctly.
- ``get_current_tenant_id()`` priority: admin_scope beats current_tenant_id
  when set, otherwise falls through to the v2.5.0 behaviour.

Pure ContextVar test — no DB, no Redis, no imports from the deep chain.
"""

import pytest

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id as _current_var,
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    get_is_management_api,
    get_visible_tenant_ids,
    is_strict_tenant_filter,
    is_tenant_filter_bypassed,
    set_admin_scope_tenant_id,
    set_current_tenant_id,
    set_is_management_api,
    set_visible_tenant_ids,
    strict_tenant_filter,
)


# -------------------------------------------------------------------------
# v2.5.0 signatures still intact
# -------------------------------------------------------------------------

class TestV25Signatures:

    def test_set_get_current_tenant_id(self):
        token = set_current_tenant_id(42)
        try:
            assert get_current_tenant_id() == 42
        finally:
            _current_var.reset(token)

    def test_bypass_tenant_filter_cm(self):
        assert is_tenant_filter_bypassed() is False
        with bypass_tenant_filter():
            assert is_tenant_filter_bypassed() is True
        assert is_tenant_filter_bypassed() is False

    def test_default_current_tenant_id_none(self):
        # Fresh context — no prior set_current_tenant_id.
        assert get_current_tenant_id() is None


# -------------------------------------------------------------------------
# New ContextVars default to None/False
# -------------------------------------------------------------------------

class TestDefaults:

    def test_visible_tenant_ids_default_none(self):
        assert get_visible_tenant_ids() is None

    def test_admin_scope_default_none(self):
        assert get_admin_scope_tenant_id() is None

    def test_is_management_api_default_false(self):
        assert get_is_management_api() is False

    def test_strict_filter_default_false(self):
        assert is_strict_tenant_filter() is False


# -------------------------------------------------------------------------
# visible_tenant_ids set/reset
# -------------------------------------------------------------------------

class TestVisibleTenantIds:

    def test_set_frozenset(self):
        token = set_visible_tenant_ids(frozenset({5, 1}))
        try:
            assert get_visible_tenant_ids() == frozenset({5, 1})
        finally:
            from bisheng.core.context.tenant import visible_tenant_ids as v
            v.reset(token)

    def test_set_none_allowed(self):
        """None is a meaningful value (no IN-list filter for super admins)."""
        from bisheng.core.context.tenant import visible_tenant_ids as v
        t1 = set_visible_tenant_ids(frozenset({2}))
        t2 = set_visible_tenant_ids(None)
        try:
            assert get_visible_tenant_ids() is None
        finally:
            v.reset(t2)
            v.reset(t1)


# -------------------------------------------------------------------------
# strict_tenant_filter context manager
# -------------------------------------------------------------------------

class TestStrictFilterCM:

    def test_enter_exit(self):
        assert is_strict_tenant_filter() is False
        with strict_tenant_filter():
            assert is_strict_tenant_filter() is True
        assert is_strict_tenant_filter() is False

    def test_nested_usage(self):
        with strict_tenant_filter():
            with strict_tenant_filter():
                assert is_strict_tenant_filter() is True
            assert is_strict_tenant_filter() is True
        assert is_strict_tenant_filter() is False

    def test_exception_resets(self):
        try:
            with strict_tenant_filter():
                assert is_strict_tenant_filter() is True
                raise RuntimeError('boom')
        except RuntimeError:
            pass
        assert is_strict_tenant_filter() is False


# -------------------------------------------------------------------------
# get_current_tenant_id priority rule (AC for F019 pre-wiring)
# -------------------------------------------------------------------------

class TestGetCurrentPriority:

    def test_admin_scope_overrides_current(self):
        from bisheng.core.context.tenant import (
            _admin_scope_tenant_id as scope_var,
            current_tenant_id as cur_var,
        )
        t1 = set_current_tenant_id(5)
        t2 = set_admin_scope_tenant_id(7)
        try:
            assert get_current_tenant_id() == 7
        finally:
            scope_var.reset(t2)
            cur_var.reset(t1)

    def test_admin_scope_none_falls_through(self):
        from bisheng.core.context.tenant import current_tenant_id as cur_var
        t1 = set_current_tenant_id(5)
        try:
            # admin_scope defaults to None → fall through to current.
            assert get_current_tenant_id() == 5
        finally:
            cur_var.reset(t1)

    def test_both_unset_returns_none(self):
        assert get_current_tenant_id() is None


# -------------------------------------------------------------------------
# is_management_api flag
# -------------------------------------------------------------------------

class TestIsManagementApi:

    def test_set_and_read(self):
        from bisheng.core.context.tenant import _is_management_api as var
        token = set_is_management_api(True)
        try:
            assert get_is_management_api() is True
        finally:
            var.reset(token)
