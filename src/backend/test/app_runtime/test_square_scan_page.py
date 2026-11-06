"""F056 T008 — the square's scan page: action switch, state narrowing, payload.

Lives in ``test/app_runtime/`` rather than ``test/workflow/`` (tasks.md's
nominal home) purely because the harness it needs — ``build_list_env``, which
stands up all three tables plus both a sync and an async session bound to one
SQLite file — is a fixture of this package's conftest, and pytest fixtures do
not cross package boundaries. Duplicating a 200-line harness to satisfy a path
would be the worse trade.

Both square entries are asserted separately on purpose. They are asymmetric:
``get_online_flows_cursor`` runs ``add_extra_field`` afterwards and
``get_uncategorized_flows_envelope`` does not, so anything attached in the wrong
place works on the tagged tab and silently fails on the "uncategorised" tab —
which is the one the acceptance script actually uses.

Both entries are F027 cursor envelopes; these probes unwrap ``.data`` because
what they assert is the page's contents, not its pagination (that is
``test/workstation/test_f040_app_square_cursor.py``).
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


async def _tagged_tab(env, *, user=None, cursor=None, page_size=20, name=None, tag_id=None):
    from bisheng.api.services.workflow import WorkFlowService

    envelope = await WorkFlowService.get_online_flows_cursor(
        user or _payload(),
        name,
        FlowStatus.ONLINE.value,
        tag_id,
        None,
        cursor=cursor,
        page_size=page_size,
    )
    return envelope.data


async def _uncategorized_tab(env, *, user=None, cursor=None, page_size=20):
    from bisheng.api.services.workflow import WorkFlowService

    envelope = await WorkFlowService.get_uncategorized_flows_envelope(
        user or _payload(),
        cursor=cursor,
        page_size=page_size,
    )
    return envelope.data


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


async def test_square_buckets_ask_only_their_visibility_action(square_env, tenant_scope):
    """Every bucket is asked for exactly one action — ``use`` for hosted apps too.

    The square stopped asking for ``edit`` / ``share`` up front when per-card
    actions went lazy (``additional_actions=()``, beta1 ``7559c9871``): the
    answer would be discarded with the action map. The hosted-application
    override may swap *which* action decides visibility (AC-06: ``use``, the
    entry's own decision) but must not re-add extras the caller dropped.

    Both entries are asserted: the tagged tab decides with ``use`` for every
    type, the "uncategorised" tab keeps ``visible`` for workflows / assistants
    and still asks ``use`` for hosted apps.
    """
    tenant_scope(ROOT_TENANT_ID)
    square_env.seed_app(name="hosted")
    square_env.seed_flow(name="wf")
    square_env.seed_assistant(name="asst")

    await _tagged_tab(square_env)
    assert dict(square_env.asked_actions) == {"app": ("use",), "workflow": ("use",), "assistant": ("use",)}

    square_env.asked_actions.clear()
    await _uncategorized_tab(square_env)
    assert dict(square_env.asked_actions) == {"app": ("use",), "workflow": ("visible",), "assistant": ("visible",)}


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


async def test_square_page_defers_can_share(square_env, tenant_scope):
    """The square page carries no ``can_share`` for any type — the card resolves it lazily.

    beta1 ``ffa1e9266``: ``useLazyAppSharePermission`` asks
    ``checkResourceAction(..., "share")`` on first interaction, and only for
    workflows and assistants — ``getAppPermissionResourceType`` maps a hosted
    app to ``null``, so its card never asks and never shows the action (决议-6).
    Emitting the field here again would make the client trust it
    (``app.can_share ?? ...``) and quietly re-open the eager path.
    """
    tenant_scope(ROOT_TENANT_ID)
    square_env.seed_app(name="hosted")
    square_env.seed_flow(name="wf")

    rows = await _tagged_tab(square_env)

    assert {row["flow_type"] for row in rows} == {HOSTED, WORKFLOW}
    assert all("can_share" not in row for row in rows)


async def test_can_share_false_for_app(square_env, tenant_scope):
    """Wherever ``can_share`` *is* computed, a hosted app gets ``False`` without asking FGA.

    ``aenrich_apps_can_share`` is the server-side answer behind every list that
    still pre-computes the field (application centre, frequently used, the
    workbench strip). ``share`` is not a legal action for ``app``
    (``catalog_policy.py``, design K6 / 决议-6): the bucket is never asked, so
    the answer is ``False`` even when FGA would grant everything — asking would
    fabricate a capability and come back as business code 25001 besides.
    """
    from bisheng.api.services.workflow import WorkFlowService

    tenant_scope(ROOT_TENANT_ID)
    square_env.seed_app(name="hosted")
    square_env.seed_flow(name="wf")
    rows = await _tagged_tab(square_env)
    square_env.asked_actions.clear()

    enriched = {row["flow_type"]: row for row in await WorkFlowService.aenrich_apps_can_share(_payload(), rows)}

    assert enriched[HOSTED]["can_share"] is False
    assert enriched[WORKFLOW]["can_share"] is True
    assert dict(square_env.asked_actions) == {"workflow": ("share",)}, "the app bucket must never be asked for share"


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


# ---------------------------------------------------------------------------
# F056 T030 / AC-08 — the square's tag system takes the third type
# ---------------------------------------------------------------------------


async def test_tagged_hosted_app_appears_under_its_tag(square_env, tenant_scope):
    """A hosted application that already carries a tag shows up on that tab.

    The failure this guards is not an error: leave ``HOSTED_APP`` out of the
    tag prefilter and selecting a tag simply returns nothing hosted. The filter
    still "works", the list is just short, and nobody looks at the tag service.
    """
    from bisheng.database.models.group_resource import ResourceTypeEnum

    tenant_scope(ROOT_TENANT_ID)
    tagged = square_env.seed_app(name="tagged-hosted")
    other = square_env.seed_app(name="other-hosted")
    tag_id = square_env.seed_tag_link(
        tag_name="finance", resource_id=tagged.id, resource_type=ResourceTypeEnum.HOSTED_APP.value
    )

    rows = await _tagged_tab(square_env, tag_id=tag_id)

    assert [row["id"] for row in rows] == [tagged.id]
    assert other.id not in {row["id"] for row in rows}


async def test_untagged_hosted_app_stays_in_the_default_category(square_env, tenant_scope):
    """AC-08's other half: no tag is not the same as no home.

    "Uncategorised" is computed as the complement of "tagged", so a type missing
    from the complement's gather is reported as untagged even when it is
    tagged — the mirror image of the bug above, and it puts the same card on
    two tabs at once.
    """
    from bisheng.database.models.group_resource import ResourceTypeEnum

    tenant_scope(ROOT_TENANT_ID)
    tagged = square_env.seed_app(name="tagged-hosted")
    untagged = square_env.seed_app(name="untagged-hosted")
    square_env.seed_tag_link(tag_name="finance", resource_id=tagged.id, resource_type=ResourceTypeEnum.HOSTED_APP.value)

    rows = await _uncategorized_tab(square_env)

    ids = {row["id"] for row in rows}
    assert untagged.id in ids
    assert tagged.id not in ids


def test_tag_prefilter_spans_all_three_types_and_follows_the_switch(build_list_env, monkeypatch):
    """The prefilter's type list is where both tag bugs come from.

    Both symptoms above are one omission: the list of resource types the tag
    prefilter gathers. Asserting the list itself catches the omission at every
    one of its four call sites at once, which no per-entry probe does. The
    second half is AC-10 / F054 AC-58 — with the runtime layer absent the type
    must drop out, or "select a tag" would query a type this deployment does
    not have.
    """
    from bisheng.api.services.workflow import WorkFlowService
    from bisheng.database.models.group_resource import ResourceTypeEnum

    build_list_env.enable_runtime_layer()
    assert WorkFlowService._tag_resource_types() == [
        ResourceTypeEnum.WORK_FLOW,
        ResourceTypeEnum.ASSISTANT,
        ResourceTypeEnum.HOSTED_APP,
    ]

    build_list_env.enable_runtime_layer(False)
    assert WorkFlowService._tag_resource_types() == [
        ResourceTypeEnum.WORK_FLOW,
        ResourceTypeEnum.ASSISTANT,
    ]
