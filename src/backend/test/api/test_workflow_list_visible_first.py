"""F048 visible-ids-first refactor of ``/api/v1/workflow/list``.

These tests cover the three branches added to
``WorkFlowService.get_all_flows_envelope``:

  * regular user → ``_collect_visible_app_ids`` fans out
    ``list_visible_objects`` across workflow + assistant (or just one when
    ``flow_type`` is set), and the resulting union is threaded into
    ``_scan_visible_flows_cursor`` as ``flow_ids``; per-batch BatchCheck still
    runs inside the scan loop;
  * super admin / tenant admin → the F048 runtime is not called, every row
    is considered writeable, and ``write=True`` appears on every returned item;
  * empty visible set → an empty page is returned before the DB scan.

The module-level static-grep invariants (cursor context format, error routing,
``_scan_visible_flows_cursor`` delegation) are already covered by
``test_workflow_list_cursor.py``; this file only adds *behavioural* tests that
need mocking.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bisheng.api.services.workflow as wf_mod
from bisheng.api.services.workflow import WorkFlowService, _APP_VISIBLE_MAX_RESULTS
from bisheng.database.models.flow import FlowType
from bisheng.permission.domain.schemas import (
    VisibilityEnumerationStatus,
    VisibleObjectEnumerationResult,
)


class _User:
    user_id = 99
    tenant_id = 3


def _app(app_id: str, *, flow_type: int = FlowType.WORKFLOW.value, minutes: int = 0) -> dict:
    stamp = datetime(2026, 8, 13, 8, minutes)
    return {
        "id": app_id,
        "name": f"app-{app_id}",
        "description": "",
        "flow_type": flow_type,
        "logo": None,
        "user_id": _User.user_id,
        "status": 1,
        "create_time": stamp,
        "update_time": stamp,
    }


def _visible(resource_type: str, *ids: str) -> VisibleObjectEnumerationResult:
    return VisibleObjectEnumerationResult(
        resource_type=resource_type,
        object_ids=ids,
        max_results=_APP_VISIBLE_MAX_RESULTS,
        status=VisibilityEnumerationStatus.NORMAL,
    )


def _actor(*, super_admin: bool = False, tenant_admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=_User.user_id,
        current_tenant_id=_User.tenant_id,
        super_admin=super_admin,
        tenant_admin_tenant_ids=(
            frozenset({_User.tenant_id}) if tenant_admin else frozenset()
        ),
    )


def _stub_common(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub helpers that are outside the scope of these tests."""
    monkeypatch.setattr(wf_mod, "emit_metric", lambda *a, **k: None)
    monkeypatch.setattr(wf_mod.TagDao, "get_resources_by_tags_batch", lambda *a, **k: [])
    monkeypatch.setattr(
        wf_mod.UserDao, "get_user_by_ids", lambda _ids: [SimpleNamespace(user_id=_User.user_id, user_name="bob")]
    )
    monkeypatch.setattr(wf_mod.FlowVersionDao, "get_list_by_flow_ids", lambda _ids: [])
    monkeypatch.setattr(wf_mod.TagDao, "get_tags_by_resource", lambda *a, **k: {})
    monkeypatch.setattr(WorkFlowService, "get_logo_share_link", staticmethod(lambda logo: logo))


# ---------------------------------------------------------------------------
# Regular user: visible-ids-first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regular_user_collects_visible_ids_and_passes_to_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_common(monkeypatch)
    monkeypatch.setattr(wf_mod, "resolve_permission_actor", AsyncMock(return_value=_actor()))

    # Workflow + assistant visible ids (no flow_type filter → both queried).
    workflow_visible = _visible("workflow", "10", "11")
    assistant_visible = _visible("assistant", "aa1")
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(side_effect=[workflow_visible, assistant_visible])
    )
    monkeypatch.setattr(wf_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    scan_call: dict = {}

    async def _fake_scan(*, user, name, status, flow_ids, flow_type, cursor, page_size, managed,
                         search_description, required_action, admin_bypass=False,
                         # F054 forwards the hosted-application state filter through
                         # the same call; irrelevant here, but it must be accepted.
                         **_f054_kwargs):
        scan_call["flow_ids"] = flow_ids
        scan_call["admin_bypass"] = admin_bypass
        rows = [_app("10"), _app("11"), _app("aa1", flow_type=FlowType.ASSISTANT.value)]
        return rows, False, {"10", "11", "aa1"}

    monkeypatch.setattr(WorkFlowService, "_scan_visible_flows_cursor", staticmethod(_fake_scan))

    result = await WorkFlowService.get_all_flows_envelope(
        _User(), name=None, status=None, tag_id=None, flow_type=None,
        page_size=10, managed=False, action="use",
    )

    # Both resource types were queried.
    assert runtime.list_visible_objects.await_count == 2
    queried_types = {
        call.kwargs["resource_type"]
        for call in runtime.list_visible_objects.await_args_list
    }
    assert queried_types == {"workflow", "assistant"}

    # The union of visible ids was forwarded as flow_ids.
    assert set(scan_call["flow_ids"]) == {"10", "11", "aa1"}
    assert scan_call["admin_bypass"] is False

    assert len(result.data) == 3


@pytest.mark.asyncio
async def test_regular_user_empty_visible_set_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_common(monkeypatch)
    monkeypatch.setattr(wf_mod, "resolve_permission_actor", AsyncMock(return_value=_actor()))

    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(
            side_effect=[_visible("workflow"), _visible("assistant")]
        )
    )
    monkeypatch.setattr(wf_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    scan_called = []

    async def _fake_scan(**kwargs):
        scan_called.append(True)
        return [], False, set()

    monkeypatch.setattr(WorkFlowService, "_scan_visible_flows_cursor", staticmethod(_fake_scan))

    result = await WorkFlowService.get_all_flows_envelope(
        _User(), name=None, status=None, tag_id=None, flow_type=None,
        page_size=10, managed=False, action="use",
    )

    assert scan_called == [], "DB scan must not run when visible set is empty"
    assert result.data == []
    assert result.has_more is False


@pytest.mark.asyncio
async def test_regular_user_flow_type_filter_queries_single_resource_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_common(monkeypatch)
    monkeypatch.setattr(wf_mod, "resolve_permission_actor", AsyncMock(return_value=_actor()))

    workflow_visible = _visible("workflow", "20", "21")
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=workflow_visible))
    monkeypatch.setattr(wf_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    async def _fake_scan(**kwargs):
        return [_app("20"), _app("21")], False, {"20", "21"}

    monkeypatch.setattr(WorkFlowService, "_scan_visible_flows_cursor", staticmethod(_fake_scan))

    await WorkFlowService.get_all_flows_envelope(
        _User(), name=None, status=None, tag_id=None,
        flow_type=FlowType.WORKFLOW.value,
        page_size=10, managed=False, action="use",
    )

    # Only the workflow resource type is queried when flow_type=WORKFLOW.
    assert runtime.list_visible_objects.await_count == 1
    assert runtime.list_visible_objects.await_args.kwargs["resource_type"] == "workflow"


# ---------------------------------------------------------------------------
# Admin bypass: super admin and tenant admin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("identity_kind", ["super_admin", "tenant_admin"])
@pytest.mark.asyncio
async def test_admin_bypass_skips_f048_runtime_and_marks_all_writeable(
    monkeypatch: pytest.MonkeyPatch,
    identity_kind: str,
) -> None:
    _stub_common(monkeypatch)
    monkeypatch.setattr(
        wf_mod,
        "resolve_permission_actor",
        AsyncMock(
            return_value=_actor(
                super_admin=(identity_kind == "super_admin"),
                tenant_admin=(identity_kind == "tenant_admin"),
            )
        ),
    )

    runtime = SimpleNamespace(list_visible_objects=AsyncMock())
    monkeypatch.setattr(wf_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    scan_call: dict = {}

    async def _fake_scan(*, flow_ids, admin_bypass=False, **kwargs):
        scan_call["flow_ids"] = flow_ids
        scan_call["admin_bypass"] = admin_bypass
        rows = [_app("30"), _app("31")]
        writeable = {str(r["id"]) for r in rows}
        return rows, False, writeable

    monkeypatch.setattr(WorkFlowService, "_scan_visible_flows_cursor", staticmethod(_fake_scan))

    result = await WorkFlowService.get_all_flows_envelope(
        _User(), name=None, status=None, tag_id=None, flow_type=None,
        page_size=10, managed=False, action="use",
    )

    # The F048 runtime is never touched for admins.
    runtime.list_visible_objects.assert_not_awaited()

    # admin_bypass is forwarded to the scan loop.
    assert scan_call["admin_bypass"] is True

    # Every row is marked as writeable.
    for row in result.data:
        assert row["write"] is True


# ---------------------------------------------------------------------------
# Scan loop: admin_bypass skips BatchCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_loop_admin_bypass_skips_batch_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct test of ``_scan_visible_flows_cursor`` with ``admin_bypass=True``."""
    rows = [_app("40"), _app("41"), _app("42")]

    async def _fake_aget_all_apps(*args, **kwargs):
        return rows, False

    monkeypatch.setattr(wf_mod.FlowDao, "aget_all_apps", _fake_aget_all_apps)

    action_map_calls: list[tuple] = []

    async def _fake_action_map(user, batch, actions):
        action_map_calls.append(actions)
        return {}

    monkeypatch.setattr(WorkFlowService, "_application_action_map", staticmethod(_fake_action_map))

    visible, has_more, writeable_ids = await WorkFlowService._scan_visible_flows_cursor(
        user=_User(),
        name=None,
        status=None,
        flow_ids=[],
        flow_type=None,
        cursor=None,
        page_size=10,
        managed=False,
        search_description=False,
        required_action="use",
        admin_bypass=True,
    )

    # No BatchCheck when admin_bypass=True.
    assert action_map_calls == []
    # All rows are kept.
    assert len(visible) == 3
    # All are in writeable_ids.
    assert writeable_ids == {"40", "41", "42"}


@pytest.mark.asyncio
async def test_scan_loop_regular_user_runs_batch_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_scan_visible_flows_cursor`` with ``admin_bypass=False`` still calls BatchCheck."""
    rows = [_app("50"), _app("51")]

    async def _fake_aget_all_apps(*args, **kwargs):
        return rows, False

    monkeypatch.setattr(wf_mod.FlowDao, "aget_all_apps", _fake_aget_all_apps)

    action_map_calls: list[tuple] = []

    async def _fake_action_map(user, batch, actions):
        action_map_calls.append(actions)
        # Both rows have "use"; only "50" has "edit".
        return {"50": frozenset({"use", "edit"}), "51": frozenset({"use"})}

    monkeypatch.setattr(WorkFlowService, "_application_action_map", staticmethod(_fake_action_map))

    visible, has_more, writeable_ids = await WorkFlowService._scan_visible_flows_cursor(
        user=_User(),
        name=None,
        status=None,
        flow_ids=[],
        flow_type=None,
        cursor=None,
        page_size=10,
        managed=False,
        search_description=False,
        required_action="use",
        admin_bypass=False,
    )

    assert action_map_calls, "BatchCheck must run for non-admin users"
    assert len(visible) == 2  # both have "use"
    assert writeable_ids == {"50"}  # only "50" has "edit"


# ---------------------------------------------------------------------------
# F054: the enumerated resource types follow enabled_app_types()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hosted_apps_are_enumerated_when_the_runtime_layer_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The visible-ids pre-filter must span every type the list can return.

    A type missing from the enumeration does not raise — it silently removes
    every row of that type from the list, for non-admins only. Hosted
    applications were exactly that case: the pre-filter asked OpenFGA about
    workflow and assistant alone, so an app the user could plainly use never
    reached the DB scan.
    """
    monkeypatch.setattr(wf_mod.settings.app_runtime, "enabled", True)
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(
            side_effect=lambda _actor, *, resource_type, max_results: _visible(resource_type, "x1")
        )
    )
    monkeypatch.setattr(wf_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    await WorkFlowService._collect_visible_app_ids(_actor(), None)

    queried = {call.kwargs["resource_type"] for call in runtime.list_visible_objects.await_args_list}
    assert queried == {"workflow", "assistant", "app"}

    # A single type still narrows to exactly that type.
    runtime.list_visible_objects.reset_mock()
    await WorkFlowService._collect_visible_app_ids(_actor(), FlowType.HOSTED_APP.value)
    assert {call.kwargs["resource_type"] for call in runtime.list_visible_objects.await_args_list} == {"app"}


@pytest.mark.asyncio
async def test_hosted_apps_are_not_enumerated_when_the_layer_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the layer off the type is not listed at all, so asking for it is empty."""
    monkeypatch.setattr(wf_mod.settings.app_runtime, "enabled", False)
    runtime = SimpleNamespace(
        list_visible_objects=AsyncMock(
            side_effect=lambda _actor, *, resource_type, max_results: _visible(resource_type, "x1")
        )
    )
    monkeypatch.setattr(wf_mod, "get_f048_runtime", AsyncMock(return_value=runtime))

    await WorkFlowService._collect_visible_app_ids(_actor(), None)
    queried = {call.kwargs["resource_type"] for call in runtime.list_visible_objects.await_args_list}
    assert queried == {"workflow", "assistant"}

    runtime.list_visible_objects.reset_mock()
    assert await WorkFlowService._collect_visible_app_ids(_actor(), FlowType.HOSTED_APP.value) == []
    assert runtime.list_visible_objects.await_count == 0
