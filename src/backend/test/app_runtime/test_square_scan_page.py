"""F056 T008 — the square's scan page: action switch, state narrowing, payload.

Lives in ``test/app_runtime/`` rather than ``test/workflow/`` (tasks.md's
nominal home) purely because the harness it needs — ``build_list_env``, which
stands up all three tables plus both a sync and an async session bound to one
SQLite file — is a fixture of this package's conftest, and pytest fixtures do
not cross package boundaries. Duplicating a 200-line harness to satisfy a path
would be the worse trade.

Both square entries are asserted separately on purpose. They are asymmetric:
``get_online_flows_page`` runs ``add_extra_field`` afterwards and
``get_uncategorized_flows`` does not, so anything attached in the wrong place
works on the tagged tab and silently fails on the "uncategorised" tab — which
is the one the acceptance script actually uses.
"""

from __future__ import annotations

import pytest

from bisheng.database.models.flow import FlowStatus, FlowType

from .conftest import OWNER_USER_ID, ROOT_TENANT_ID

HOSTED = FlowType.HOSTED_APP.value
WORKFLOW = FlowType.WORKFLOW.value
ASSISTANT = FlowType.ASSISTANT.value


def _payload(user_id: int = OWNER_USER_ID, tenant_id: int = ROOT_TENANT_ID):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name=f"user-{user_id}", user_role=[], tenant_id=tenant_id)


async def _tagged_tab(env, *, user=None, page=1, page_size=20, name=None):
    from bisheng.api.services.workflow import WorkFlowService

    return await WorkFlowService.get_online_flows_page(
        user or _payload(),
        name,
        FlowStatus.ONLINE.value,
        None,
        None,
        page,
        page_size,
    )


async def _uncategorized_tab(env, *, user=None, page=1, page_size=20):
    from bisheng.api.services.workflow import WorkFlowService

    return await WorkFlowService.get_uncategorized_flows(user or _payload(), page, page_size)


@pytest.fixture()
def square_env(build_list_env, monkeypatch):
    """``build_list_env`` plus the two probes these assertions need.

    The permission stub is replaced rather than reused because the harness's
    version records only *which* resources were asked about, and half of what
    F056 changed is *which actions* each bucket asks for.
    """
    from contextlib import contextmanager
    from types import SimpleNamespace

    from bisheng.database.models.app import AppDao

    build_list_env.enable_runtime_layer()

    asked_actions: dict[str, tuple[str, ...]] = {}
    granted: dict[str, set[str]] = {}
    grant_all = {"value": True}

    async def _batch_check(user, *, resource_type, resource_ids, actions):
        asked_actions[resource_type] = tuple(actions)
        result: dict[str, frozenset[str]] = {}
        for resource_id in resource_ids:
            allowed = set(actions) if grant_all["value"] else (granted.get(str(resource_id), set()) & set(actions))
            if allowed:
                result[str(resource_id)] = frozenset(allowed)
        return result

    monkeypatch.setattr("bisheng.api.services.workflow.batch_check_business_actions", _batch_check)

    def only_allow(resource_ids, actions=("use", "edit", "share")):
        grant_all["value"] = False
        granted.clear()
        for resource_id in resource_ids:
            granted[str(resource_id)] = set(actions)

    def allow(resource_ids, actions=("use", "edit", "share")):
        grant_all["value"] = False
        for resource_id in resource_ids:
            granted.setdefault(str(resource_id), set()).update(actions)

    @contextmanager
    def count_app_lookups():
        counter = SimpleNamespace(calls=0)
        original = AppDao.alist_slug_state_by_ids

        async def _counting(session, app_ids):
            counter.calls += 1
            return await original(session, app_ids)

        monkeypatch.setattr(AppDao, "alist_slug_state_by_ids", classmethod(lambda cls, s, ids: _counting(s, ids)))
        try:
            yield counter
        finally:
            monkeypatch.undo()

    return SimpleNamespace(
        seed_flow=build_list_env.seed_flow,
        seed_assistant=build_list_env.seed_assistant,
        seed_app=build_list_env.seed_app,
        seed_tag_link=build_list_env.seed_tag_link,
        asked_actions=asked_actions,
        only_allow=only_allow,
        allow=allow,
        count_app_lookups=count_app_lookups,
    )


# ---------------------------------------------------------------------------
# Layer 2 — which action decides visibility
# ---------------------------------------------------------------------------


async def test_app_bucket_requests_use_edit(square_env, tenant_scope):
    """Hosted apps are asked for ``use``/``edit``; the other two keep their trio."""
    tenant_scope(ROOT_TENANT_ID)
    square_env.seed_app(name="hosted")
    square_env.seed_flow(name="wf")
    square_env.seed_assistant(name="asst")

    await _tagged_tab(square_env)

    asked = dict(square_env.asked_actions)
    assert set(asked["app"]) == {"use", "edit"}
    assert asked["workflow"] == ("use", "edit", "share")
    assert asked["assistant"] == ("use", "edit", "share")


async def test_kept_filter_per_row_type(square_env, tenant_scope):
    """A row visible only through ``use`` survives; ``visible`` alone does not.

    This is AC-06's machine guard. The public entry decides with
    ``check_business_action("app", id, actor, "use")``; if the square kept using
    ``visible`` — a different FGA relation — a user granted ``editor`` but not
    ``use`` would see a card they cannot open.
    """
    tenant_scope(ROOT_TENANT_ID)
    app = square_env.seed_app(name="hosted")
    flow = square_env.seed_flow(name="wf")

    square_env.only_allow([app.id], actions=("use", "edit"))
    square_env.allow([flow.id], actions=("use", "edit", "share"))
    assert {row["id"] for row in await _tagged_tab(square_env)} == {app.id, flow.id}

    # Grant the hosted app everything except ``use`` — it must drop out while
    # the workflow, judged by its own action, stays.
    square_env.only_allow([app.id], actions=("edit",))
    square_env.allow([flow.id], actions=("use", "edit", "share"))
    assert {row["id"] for row in await _tagged_tab(square_env)} == {flow.id}


async def test_can_share_false_for_app(square_env, tenant_scope):
    """``can_share`` is false for hosted apps without a single change to the card."""
    tenant_scope(ROOT_TENANT_ID)
    square_env.seed_app(name="hosted")
    square_env.seed_flow(name="wf")

    by_type = {row["flow_type"]: row for row in await _tagged_tab(square_env)}

    assert by_type[HOSTED]["can_share"] is False
    assert by_type[WORKFLOW]["can_share"] is True


# ---------------------------------------------------------------------------
# Payload — slug / app_state on both entries
# ---------------------------------------------------------------------------


async def test_slug_and_app_state_batched(square_env, tenant_scope):
    """Hosted rows carry ``slug``/``app_state``; other types carry neither.

    The lookup is one statement for the whole page — a per-card query would be
    20 round-trips on a 20-card page.
    """
    tenant_scope(ROOT_TENANT_ID)
    square_env.seed_app(name="a", slug="alpha")
    square_env.seed_app(name="b", slug="beta", state="stopped")
    square_env.seed_flow(name="wf")

    with square_env.count_app_lookups() as counter:
        rows = await _tagged_tab(square_env)

    by_slug = {row.get("slug"): row for row in rows}
    assert by_slug["alpha"]["app_state"] == "online"
    assert by_slug["beta"]["app_state"] == "stopped"
    workflow_row = next(row for row in rows if row["flow_type"] == WORKFLOW)
    assert workflow_row.get("slug") is None
    assert workflow_row.get("app_state") is None
    assert counter.calls == 1


async def test_both_entries_carry_slug(square_env, tenant_scope):
    """The "uncategorised" tab is not enriched by ``add_extra_field`` — assert it too."""
    tenant_scope(ROOT_TENANT_ID)
    app = square_env.seed_app(name="hosted", slug="gamma")

    tagged = await _tagged_tab(square_env)
    uncategorized = await _uncategorized_tab(square_env)

    for rows in (tagged, uncategorized):
        row = next(item for item in rows if item["id"] == app.id)
        assert row["slug"] == "gamma"
        assert row["app_state"] == "online"


# ---------------------------------------------------------------------------
# State narrowing — pinned server-side, both entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ["tagged", "uncategorized"])
async def test_square_state_narrowing_hardcoded(square_env, tenant_scope, entry):
    """Stopped apps stay; draft / pending_capacity / deleted never appear.

    The caller is the owner here on purpose: the exclusion is a SQL predicate,
    not a permission check, so "not even for the owner" holds without any extra
    code.
    """
    tenant_scope(ROOT_TENANT_ID)
    online = square_env.seed_app(name="online", state="online")
    stopped = square_env.seed_app(name="stopped", state="stopped")
    for hidden_state in ("draft", "pending_capacity", "deleted"):
        square_env.seed_app(name=hidden_state, state=hidden_state)

    rows = await (_tagged_tab(square_env) if entry == "tagged" else _uncategorized_tab(square_env))

    assert {row["id"] for row in rows} == {online.id, stopped.id}


async def test_build_page_still_filters_by_status(square_env, tenant_scope):
    """The status exemption is the square's alone — the build page is untouched."""
    from bisheng.api.services.workflow import WorkFlowService

    tenant_scope(ROOT_TENANT_ID)
    online = square_env.seed_app(name="online", state="online")
    square_env.seed_app(name="stopped", state="stopped")

    page = await WorkFlowService.get_all_flows_envelope(
        _payload(),
        None,
        FlowStatus.ONLINE.value,
        None,
        HOSTED,
        page_size=20,
    )

    assert [row["id"] for row in page.data] == [online.id]
