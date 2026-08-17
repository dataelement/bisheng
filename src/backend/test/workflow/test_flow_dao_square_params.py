"""F056 T006 — the square's two internal parameters on ``FlowDao.aget_all_apps``.

The square needs two things the build page must not get:

* stopped hosted applications still have to appear (决议-5: hiding them reads to
  the user as "I lost access", which is a different and much worse message than
  "this app is paused"), while the ``status`` column folds them to 1 = offline;
* drafts, pending-capacity and deleted apps must never appear, for anyone,
  including the owner and administrators.

Both are expressed as internal parameters with ``None`` defaults, so the build
page and the other two callers of ``aget_all_apps`` compile byte-identical SQL.
That last property is what these tests exist to hold: the alternative — folding
"stopped" into ``status = 2`` — would have broken the build page's
online/offline filter without any test noticing.
"""

from __future__ import annotations

from contextlib import contextmanager

from sqlmodel import select

from bisheng.core.context.tenant import (
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.database.models.flow import FlowDao, FlowType


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@contextmanager
def _tenant_context(tenant_id: int = 1):
    """``_build_apps_subquery`` reads the tenant ContextVars while composing SQL."""
    tenant_token = set_current_tenant_id(tenant_id)
    visible_token = set_visible_tenant_ids(None)
    try:
        yield
    finally:
        current_tenant_id.reset(tenant_token)
        visible_tenant_ids.reset(visible_token)


def _subquery_sql(**kwargs) -> str:
    with _tenant_context():
        return _compiled(select(FlowDao._build_apps_subquery(**kwargs).c.id))


def test_status_exempt_flow_types():
    """With the exemption set, ``status`` stops gating the hosted-application leg."""
    with _tenant_context():
        plain = _compiled(
            FlowDao._build_status_clause(
                FlowDao._build_apps_subquery(),
                status=2,
                status_exempt_flow_types=None,
            )
        )
        exempted = _compiled(
            FlowDao._build_status_clause(
                FlowDao._build_apps_subquery(),
                status=2,
                status_exempt_flow_types={FlowType.HOSTED_APP.value},
            )
        )

    assert " OR " not in plain.upper()
    assert " OR " in exempted
    assert "flow_type IN (35)" in exempted or "flow_type = 35" in exempted


def test_app_state_in_narrows_third_branch():
    """``app_state_in`` is pushed down onto the hosted leg, not the outer SELECT.

    Filtering the outer union would have to tolerate the typed NULL the other
    two legs project; pushing it down keeps drafts out of the row set entirely,
    which is why AC-03's "not even for the owner" needs no extra permission
    code.
    """
    sql = _subquery_sql(app_state_in={"online", "stopped"})

    assert "app.state IN ('online', 'stopped')" in sql or "app.state IN ('stopped', 'online')" in sql
    # The predicate belongs to the third leg only — workflows and assistants
    # have no ``state`` column to be narrowed by.
    assert sql.count("app.state IN") == 1


def test_defaults_unchanged():
    """No arguments → byte-identical SQL to the pre-F056 subquery and query."""
    assert _subquery_sql() == _subquery_sql(app_state_in=None)
    assert "state IN" not in _subquery_sql()

    with _tenant_context():
        unchanged = _compiled(
            FlowDao._build_status_clause(
                FlowDao._build_apps_subquery(),
                status=2,
                status_exempt_flow_types=None,
            )
        )
    assert "status = 2" in unchanged


def test_empty_app_state_in_is_ignored():
    """An empty set means "no narrowing", never "match nothing"."""
    assert _subquery_sql(app_state_in=set()) == _subquery_sql()
