"""T058 — the build page's third application type, end to end (AC-51, AC-57).

Why an end-to-end file rather than a unit test per gate: adding the UNION's
third leg is only the first of the gates a hosted application has to clear
before a card appears (design D8 lists six more), and **every one of them fails
as an empty list, never as an error**. A unit test on the subquery would stay
green while the build page showed nothing, and the person debugging it would
spend the afternoon on OpenFGA. So these tests drive the real pipeline —
``WorkFlowService.get_all_flows_envelope`` → ``FlowDao.aget_all_apps`` →
``filter_supported_apps`` → ``_application_action_map`` → ``add_extra_field`` —
against a real SQLite carrying all three tables, with permissions granted by
default so an empty result can only mean a broken gate.

The tenant test is the one to read first: a UNION subquery **hides its tables
from the automatic tenant filter**, so the third leg has to carry its own
``build_tenant_filter_clause``. Nothing else in the stack will catch it if it
does not, and the leak reaches all four callers of ``_build_apps_subquery`` at
once (design K5 ③).
"""

from __future__ import annotations

import pytest

from bisheng.database.models.flow import FlowType
from bisheng.database.models.group_resource import ResourceTypeEnum

from .conftest import NORMAL_USER_ID, OWNER_USER_ID, ROOT_TENANT_ID, SUB_TENANT_ID

HOSTED = FlowType.HOSTED_APP.value
WORKFLOW = FlowType.WORKFLOW.value
ASSISTANT = FlowType.ASSISTANT.value


def _payload(user_id: int = OWNER_USER_ID, tenant_id: int = ROOT_TENANT_ID):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name=f"user-{user_id}", user_role=[], tenant_id=tenant_id)


async def _list(env, *, flow_type=None, app_state=None, tag_id=None, user=None, page_size=20, cursor=None):
    from bisheng.api.services.workflow import WorkFlowService

    return await WorkFlowService.get_all_flows_envelope(
        user or _payload(),
        None,
        None,
        tag_id,
        flow_type,
        cursor=cursor,
        page_size=page_size,
        app_state=app_state,
    )


# ---------------------------------------------------------------------------
# The whole pipeline, not just the UNION
# ---------------------------------------------------------------------------


async def test_third_type_end_to_end_non_empty(build_list_env, tenant_scope):
    """A hosted app reaches the page fully enriched — AC-51."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    app = build_list_env.seed_app(name="Report Tool", state="online")

    page = await _list(build_list_env, flow_type=HOSTED)

    assert [row["id"] for row in page.data] == [app.id]
    row = page.data[0]
    # Each key below is a different gate; asserting the ids alone would pass
    # with the permission bucket and the enrichment step both broken.
    assert row["flow_type"] == HOSTED
    assert row["user_id"] == OWNER_USER_ID
    assert row["user_name"] == f"user-{OWNER_USER_ID}"
    assert row["write"] is True
    assert row["tags"] == []
    assert row["app_state"] == "online"
    assert row["status"] == 2


async def test_app_state_is_projected_not_fetched_per_card(build_list_env, tenant_scope):
    """The state badge rides the list query — the card must not need a detail call.

    A 14-card page fetching its own state is 14 requests; the ruling of
    2026-08-17 is that the value comes off the projection.
    """
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    for state in ("draft", "online", "pending_capacity", "stopped"):
        build_list_env.seed_app(name=f"app-{state}", state=state)

    page = await _list(build_list_env, flow_type=HOSTED)

    assert sorted(row["app_state"] for row in page.data) == ["draft", "online", "pending_capacity", "stopped"]


async def test_other_types_carry_no_app_state_key(build_list_env, tenant_scope):
    """Workflows and assistants keep their exact pre-F054 payload (AC-59)."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    build_list_env.seed_flow(name="wf")
    build_list_env.seed_assistant(name="as")

    page = await _list(build_list_env)

    assert page.data, "workflow/assistant rows disappeared"
    assert all("app_state" not in row for row in page.data)


async def test_type_filter_returns_only_hosted_apps(build_list_env, tenant_scope):
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    app = build_list_env.seed_app(name="hosted")
    build_list_env.seed_flow(name="wf")
    build_list_env.seed_assistant(name="as")

    hosted_page = await _list(build_list_env, flow_type=HOSTED)
    workflow_page = await _list(build_list_env, flow_type=WORKFLOW)
    assistant_page = await _list(build_list_env, flow_type=ASSISTANT)

    assert [row["id"] for row in hosted_page.data] == [app.id]
    assert [row["flow_type"] for row in workflow_page.data] == [WORKFLOW]
    assert [row["flow_type"] for row in assistant_page.data] == [ASSISTANT]


async def test_app_state_filter_covers_five_values(build_list_env, tenant_scope):
    """All five states are accepted; ``deleted`` is accepted **and empty**.

    The list excludes deleted applications by design (the row survives for
    audit), so the filter must answer "nothing" rather than fail — a stale link
    or a saved filter must not produce an error page.
    """
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    seeded = {
        state: build_list_env.seed_app(name=f"app-{state}", state=state)
        for state in ("draft", "online", "pending_capacity", "stopped", "deleted")
    }

    for state in ("draft", "online", "pending_capacity", "stopped"):
        page = await _list(build_list_env, flow_type=HOSTED, app_state=state)
        assert [row["id"] for row in page.data] == [seeded[state].id], state

    deleted_page = await _list(build_list_env, flow_type=HOSTED, app_state="deleted")
    assert deleted_page.data == []

    # And the deleted row is absent from the unfiltered list too.
    everything = await _list(build_list_env, flow_type=HOSTED)
    assert seeded["deleted"].id not in {row["id"] for row in everything.data}


async def test_app_state_filter_never_matches_other_types(build_list_env, tenant_scope):
    """``app_state`` narrows to hosted apps on its own (the other legs project NULL)."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    build_list_env.seed_flow(name="wf", status=2)
    app = build_list_env.seed_app(name="hosted", state="online")

    page = await _list(build_list_env, app_state="online")

    assert [row["id"] for row in page.data] == [app.id]


# ---------------------------------------------------------------------------
# Tenant isolation — the leg's own clause is the only thing standing here
# ---------------------------------------------------------------------------


async def test_tenant_isolation_in_union_third_branch(build_list_env, tenant_scope):
    """A child tenant never sees another tenant's hosted applications (K5 ③)."""
    tenant_scope(SUB_TENANT_ID)
    build_list_env.enable_runtime_layer()
    mine = build_list_env.seed_app(name="mine", tenant_id=SUB_TENANT_ID)
    theirs = build_list_env.seed_app(name="theirs", tenant_id=ROOT_TENANT_ID)

    page = await _list(build_list_env, flow_type=HOSTED, user=_payload(tenant_id=SUB_TENANT_ID))

    ids = {row["id"] for row in page.data}
    assert mine.id in ids
    assert theirs.id not in ids


def test_third_branch_emits_its_own_tenant_predicate():
    """Compiled-SQL guard: three legs, three tenant predicates.

    The behavioural test above only covers the shapes the harness exercises;
    this one pins the invariant itself, because the auto-filter that catches
    every other query is structurally blind to a UNION subquery.
    """
    from sqlmodel import select

    from bisheng.core.context.tenant import (
        current_tenant_id,
        set_current_tenant_id,
        set_visible_tenant_ids,
        visible_tenant_ids,
    )
    from bisheng.database.models.flow import FlowDao

    tenant_token = set_current_tenant_id(5)
    visible_token = set_visible_tenant_ids(frozenset({5, 1}))
    try:
        sql = str(select(FlowDao._build_apps_subquery().c.id).compile(compile_kwargs={"literal_binds": True}))
    finally:
        current_tenant_id.reset(tenant_token)
        visible_tenant_ids.reset(visible_token)

    assert "flow.tenant_id IN (1, 5)" in sql
    assert "assistant.tenant_id IN (1, 5)" in sql
    assert "app.tenant_id IN (1, 5)" in sql


def test_app_state_literals_match_the_enum():
    """``flow.py`` cannot import ``AppState`` (RULE-2); this keeps the copy honest."""
    from bisheng.app_runtime.domain.constants import AppState
    from bisheng.database.models.app import APP_STATE_DELETED, APP_STATE_ONLINE

    assert APP_STATE_ONLINE == AppState.ONLINE.value
    assert APP_STATE_DELETED == AppState.DELETED.value


# ---------------------------------------------------------------------------
# Scope, paging, tags, permission bucket
# ---------------------------------------------------------------------------


async def test_owner_scope_and_tenant_admin_scope(build_list_env, tenant_scope):
    """Scope is the permission map's job, and hosted apps go through it — AC-57."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    mine = build_list_env.seed_app(name="mine", owner_user_id=OWNER_USER_ID)
    other = build_list_env.seed_app(name="other", owner_user_id=NORMAL_USER_ID)

    # Tenant administrator: everything in the tenant is visible.
    admin_page = await _list(build_list_env, flow_type=HOSTED)
    assert {row["id"] for row in admin_page.data} == {mine.id, other.id}

    # Owner: only what the permission map returns for them.
    build_list_env.only_allow([mine.id])
    owner_page = await _list(build_list_env, flow_type=HOSTED)
    assert [row["id"] for row in owner_page.data] == [mine.id]


async def test_cursor_ordering_stable_across_three_branches(build_list_env, tenant_scope):
    """The three legs merge into one ``(update_time desc, id desc)`` sequence.

    Ordering — not the round trip — is what a third leg puts at risk: keyset
    paging is correct exactly when the merged result is totally ordered by the
    cursor key. The round trip itself cannot be asserted on SQLite: the cursor
    carries an ISO-8601 *string* while SQLite stores DATETIME as
    ``YYYY-MM-DD HH:MM:SS``, and ``' ' < 'T'`` makes the keyset predicate true
    for every row. MySQL and DM8 coerce the bound parameter to a real DATETIME,
    so this is a harness artefact and predates F054 — verified by reproducing it
    with the workflow and assistant legs alone. The companion test below pins
    the predicate that does the narrowing.
    """
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    expected = []
    for index in range(3):
        expected.append(build_list_env.seed_flow(name=f"wf-{index}").id)
        expected.append(build_list_env.seed_assistant(name=f"as-{index}").id)
        expected.append(build_list_env.seed_app(name=f"app-{index}").id)

    page = await _list(build_list_env, page_size=50)

    ids = [row["id"] for row in page.data]
    assert ids == list(reversed(expected)), "the three legs are not merged into one ordering"
    keys = [(row["update_time"], row["id"]) for row in page.data]
    assert keys == sorted(keys, reverse=True), "cursor key is not monotonic across the merged legs"
    assert len(ids) == len(set(ids))


async def test_cursor_keyset_predicate_spans_the_merged_subquery(build_list_env, tenant_scope):
    """The keyset predicate is bound to a subquery that carries all three legs.

    Compiled-SQL rather than a round trip, for the SQLite reason above.
    """
    from bisheng.database.models.flow import FlowDao
    from bisheng.database.utils.keyset import build_keyset_where

    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    app = build_list_env.seed_app(name="hosted")

    sub_query = FlowDao._build_apps_subquery()
    clause = build_keyset_where(
        (sub_query.c.update_time, sub_query.c.id),
        (app.update_time, app.id),
        descending=True,
    )
    predicate_sql = str(clause.compile(compile_kwargs={"literal_binds": True}))
    union_sql = str(sub_query.original.compile(compile_kwargs={"literal_binds": True}))

    assert "update_time" in predicate_sql and "id" in predicate_sql
    assert union_sql.count("UNION ALL") == 2, "the keyset predicate does not span three legs"
    assert "FROM app" in union_sql


async def test_tag_filter_and_tag_link_for_app(build_list_env, tenant_scope):
    """A tagged hosted app survives the tag prefilter — AC-51."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()
    app = build_list_env.seed_app(name="tagged")
    build_list_env.seed_app(name="untagged")
    tag_id = build_list_env.seed_tag_link(
        tag_name="finance", resource_id=app.id, resource_type=ResourceTypeEnum.HOSTED_APP.value
    )

    page = await _list(build_list_env, flow_type=HOSTED, tag_id=tag_id)

    assert [row["id"] for row in page.data] == [app.id]
    assert [tag.name for tag in page.data[0]["tags"]] == ["finance"]


def test_check_tag_link_permission_accepts_hosted_app(monkeypatch):
    """Tagging a hosted app asks F048 about ``app`` instead of answering 404.

    Without the branch the resource type falls through to ``NotFoundError``, so
    the label dropdown opens, the request 404s, and nothing points at the tag
    service.
    """
    import asyncio
    from types import SimpleNamespace

    from bisheng.api.services import tag as tag_module

    asked: list[dict] = []

    async def _fake_row(resource_id: str):
        return SimpleNamespace(id=resource_id, state="online")

    async def _record(login_user, *, resource_type, resource_id, action):
        asked.append({"resource_type": resource_type, "resource_id": resource_id, "action": action})
        return True

    monkeypatch.setattr(tag_module, "_aget_hosted_app", _fake_row)
    monkeypatch.setattr(tag_module, "require_business_action", _record)
    monkeypatch.setattr(tag_module, "run_async_safe", lambda coro, **kwargs: asyncio.run(coro))

    assert tag_module.TagService.check_tag_link_permission(None, _payload(), "app-1", ResourceTypeEnum.HOSTED_APP)
    assert asked == [{"resource_type": "app", "resource_id": "app-1", "action": "edit"}]


def test_check_tag_link_permission_rejects_missing_hosted_app(monkeypatch):
    import asyncio

    from bisheng.api.services import tag as tag_module
    from bisheng.common.errcode.http_error import NotFoundError

    async def _absent(resource_id: str):
        return None

    monkeypatch.setattr(tag_module, "_aget_hosted_app", _absent)
    monkeypatch.setattr(tag_module, "run_async_safe", lambda coro, **kwargs: asyncio.run(coro))

    with pytest.raises(NotFoundError):
        tag_module.TagService.check_tag_link_permission(None, _payload(), "gone", ResourceTypeEnum.HOSTED_APP)


async def test_permission_bucket_populated(build_list_env, tenant_scope):
    """``_application_action_map`` has an ``app`` bucket — AC-51.

    Without it hosted rows are dropped from the permission query and come back
    with no actions: the cards render and nothing on them can be clicked.
    """
    from bisheng.api.services.workflow import WorkFlowService

    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()

    result = await WorkFlowService._application_action_map(
        _payload(),
        [{"id": "app-1", "flow_type": HOSTED}],
        ("use",),
    )

    assert result == {"app-1": frozenset({"use"})}
    assert ("app", ("app-1",)) in build_list_env.asked


async def test_hosted_rows_are_not_bucketed_as_workflows(build_list_env, tenant_scope):
    """The type→resource-type map must be exact, not "anything that is not an assistant"."""
    from bisheng.api.services.workflow import WorkFlowService

    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer()

    await WorkFlowService._application_action_map(
        _payload(),
        [{"id": "app-1", "flow_type": HOSTED}, {"id": "wf-1", "flow_type": WORKFLOW}],
        ("use",),
    )

    by_type = dict(build_list_env.asked)
    assert by_type["app"] == ("app-1",)
    assert by_type["workflow"] == ("wf-1",)
