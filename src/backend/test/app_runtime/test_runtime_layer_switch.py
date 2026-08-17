"""T061 — the app-factory runtime-layer switch (AC-58 … AC-62).

The switch's whole job is that a deployment which has not installed the runtime
layer is **indistinguishable from one that never heard of it**: same menus, same
permission points, same list payloads, no extra process, no extra beat task.
That is a claim about absence, and absence is what nobody notices breaking — so
each test here pins one specific thing that must *not* appear.

The two switches (``app_runtime.enabled``, F049's ``open_platform.enabled``) are
siblings by design and never merged; the boot tests below assert all four
combinations load, and that a config.yaml carrying a key the code does not know
still refuses to boot — which is why the upgrade order is "code first, key
second" (design pit 23).
"""

from __future__ import annotations

import textwrap

import pytest

from bisheng.database.models.flow import FlowType

from .conftest import ROOT_TENANT_ID

HOSTED = FlowType.HOSTED_APP.value


# ---------------------------------------------------------------------------
# AC-62 — both SPAs can read the switch, before anyone logs in
# ---------------------------------------------------------------------------


def test_env_exposes_app_runtime_enabled_anonymously(monkeypatch):
    """``GET /api/v1/env`` carries the flag and needs no session.

    Anonymous is not a convenience here: ``/apps/{slug}`` has to be able to say
    "this environment has no app factory" to a visitor who is not logged in,
    otherwise the entry degrades into an unexplained 404 (AC-30).
    """
    from types import SimpleNamespace

    from bisheng.api.v1 import endpoints as endpoints_module
    from bisheng.utils.http_middleware import TENANT_CHECK_EXEMPT_PATHS

    settings = endpoints_module.bisheng_settings
    # Patch on the class: ``ConfigService`` is a pydantic model with
    # ``validate_assignment``, so assigning a non-field on the instance raises.
    settings_cls = type(settings)
    monkeypatch.setattr(settings_cls, "get_from_db", lambda self, key: None)
    monkeypatch.setattr(
        settings_cls,
        "get_system_login_method",
        lambda self: SimpleNamespace(bisheng_pro=False, dashboard_pro=False),
    )
    monkeypatch.setattr(
        settings_cls,
        "get_knowledge",
        lambda self: SimpleNamespace(image_parser_enabled=False, version_management=None),
    )

    monkeypatch.setattr(settings.app_runtime, "enabled", True)
    assert endpoints_module.get_env().data["app_runtime_enabled"] is True

    monkeypatch.setattr(settings.app_runtime, "enabled", False)
    assert endpoints_module.get_env().data["app_runtime_enabled"] is False

    # No auth dependency, and exempt from the tenant check — otherwise the
    # anonymous read above is only true in this test.
    import inspect

    assert "login_user" not in inspect.signature(endpoints_module.get_env).parameters
    assert "/api/v1/env" in TENANT_CHECK_EXEMPT_PATHS


# ---------------------------------------------------------------------------
# AC-58 — layer absent means nothing hosted is visible
# ---------------------------------------------------------------------------


async def test_switch_off_hides_hosted_apps_from_list(build_list_env, tenant_scope):
    """With the layer off, hosted rows never leave the server.

    The SPA hides the type option, but a request for "all types" is still a
    request the backend answers; the list contract is the backend's to keep.
    """
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer(False)
    app = build_list_env.seed_app(name="hosted")
    flow = build_list_env.seed_flow(name="wf")

    from bisheng.api.services.workflow import WorkFlowService

    from .test_build_list_third_type import _payload

    all_types = await WorkFlowService.get_all_flows_envelope(_payload(), None, None, None, None, page_size=50)
    hosted_only = await WorkFlowService.get_all_flows_envelope(_payload(), None, None, None, HOSTED, page_size=50)

    ids = {row["id"] for row in all_types.data}
    assert flow.id in ids
    assert app.id not in ids
    assert hosted_only.data == []


def test_switch_off_no_new_menu_or_permission_point():
    """Zero new menu entries and zero new permission points — AC-58.

    Hosted applications live under the existing ``build`` menu and are judged by
    the existing F048 action codes. A new ``WebMenuResource`` or ``AccessType``
    member would mean every existing role silently loses access to something it
    used to reach, and every customer's role配置面 changes shape on upgrade.
    """
    from bisheng.database.models.role_access import AccessType, WebMenuResource

    assert {member.value for member in WebMenuResource} == {
        "workstation",
        "admin",
        "build",
        "create_app",
        "knowledge",
        "create_knowledge",
        "knowledge_space",
        "model",
        "tool",
        "mcp",
        "channel",
        "evaluation",
        "dataset",
        "mark_task",
        "board",
        "subscription",
        "home",
        "linsight_task_mode",
        "apps",
        "frontend",
        "backend",
        "create_dashboard",
    }
    assert {member.value for member in AccessType} == {1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 99}


@pytest.mark.parametrize("enabled", [True, False])
def test_no_ui_create_entry_in_any_state(enabled, monkeypatch):
    """No create endpoint exists in either switch state — AC-58.

    The only way a hosted application comes into being is the CLI's first
    deploy. If a POST ever appears here, the "no UI creation entry" rule has
    been broken in code, whatever the SPA renders.
    """
    from bisheng.app_runtime.api.router import router
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "enabled", enabled)

    # ``/actions/*`` are state transitions on an app that already exists, and
    # ``/internal/*`` is app-proxy's HMAC channel — neither creates anything.
    creating_routes = [
        (route.path, sorted(route.methods))
        for route in router.routes
        if "POST" in getattr(route, "methods", set())
        and "/actions/" not in route.path
        and not route.path.startswith("/internal/")
    ]
    assert creating_routes == []


def test_switch_off_no_resident_process_or_beat_task():
    """No new celery task and no new beat entry — AC-59.

    runtime-manager and app-proxy are separate deployables on purpose; if the
    feature had smuggled a resident worker into the platform image, "the layer
    is not installed" would stop being true of the backend itself.
    """
    from bisheng.common.services.config_service import settings

    beat_tasks = {entry.get("task") for entry in (settings.celery_task.beat_schedule or {}).values()}
    assert not any("app_runtime" in (task or "") for task in beat_tasks)
    assert not any("app_publish" in (task or "") for task in beat_tasks)

    import bisheng.app_runtime as app_runtime_pkg

    assert not hasattr(app_runtime_pkg, "celery"), "app_runtime must not own a celery app"


async def test_platform_regression_unchanged_when_off(build_list_env, tenant_scope):
    """Workflow / assistant payloads are byte-identical with the layer off — AC-59."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer(False)
    build_list_env.seed_flow(name="wf")
    build_list_env.seed_assistant(name="as")

    from bisheng.api.services.workflow import WorkFlowService

    from .test_build_list_third_type import _payload

    page = await WorkFlowService.get_all_flows_envelope(_payload(), None, None, None, None, page_size=50)

    assert len(page.data) == 2
    expected_keys = {
        "id",
        "name",
        "description",
        "flow_type",
        "logo",
        "user_id",
        "status",
        "create_time",
        "update_time",
        "user_name",
        "write",
        "version_list",
        "tags",
    }
    for row in page.data:
        assert set(row) == expected_keys


async def test_hosted_rows_keep_the_legacy_keys_plus_app_state(build_list_env, tenant_scope):
    """A hosted card is the legacy payload plus exactly one field — AC-51."""
    tenant_scope(ROOT_TENANT_ID)
    build_list_env.enable_runtime_layer(True)
    build_list_env.seed_app(name="hosted")

    from bisheng.api.services.workflow import WorkFlowService

    from .test_build_list_third_type import _payload

    page = await WorkFlowService.get_all_flows_envelope(_payload(), None, None, None, HOSTED, page_size=50)

    (row,) = page.data
    legacy = {
        "id",
        "name",
        "description",
        "flow_type",
        "logo",
        "user_id",
        "status",
        "create_time",
        "update_time",
        "user_name",
        "write",
        "version_list",
        "tags",
    }
    assert set(row) == legacy | {"app_state"}


# ---------------------------------------------------------------------------
# AC-60 / AC-61 — the two switches are independent, and boot order is a rule
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("app_runtime_enabled", [True, False])
@pytest.mark.parametrize("open_platform_enabled", [True, False])
def test_two_switches_orthogonal_four_combinations_boot(tmp_path, app_runtime_enabled, open_platform_enabled):
    """All four combinations load — AC-61. Sibling keys, never merged."""
    from bisheng.common.services.config_service import ConfigService

    path = _write_yaml(
        tmp_path,
        f"""
        app_runtime:
          enabled: {str(app_runtime_enabled).lower()}
        open_platform:
          enabled: {str(open_platform_enabled).lower()}
        """,
    )

    loaded = ConfigService.load_settings_from_yaml(path)

    assert loaded.app_runtime.enabled is app_runtime_enabled
    assert loaded.open_platform.enabled is open_platform_enabled


def test_unknown_yaml_key_rejects_boot(tmp_path):
    """An unknown top-level key refuses the boot — AC-60 / design pit 23.

    This is why the upgrade order is code first, key second: add ``app_runtime:``
    to a config.yaml in front of the code that declares it and the backend does
    not start at all — an outage, not a degraded feature.
    """
    from bisheng.common.services.config_service import ConfigService

    path = _write_yaml(
        tmp_path,
        """
        app_runtime_typo:
          enabled: true
        """,
    )

    with pytest.raises(KeyError):
        ConfigService.load_settings_from_yaml(path)
