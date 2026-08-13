from __future__ import annotations

import ast
import inspect
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import bisheng.bootstrap.approval_scenarios as bootstrap_module
from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
)
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.bootstrap.approval_scenarios import (
    ApprovalScenarioBootstrapComponents,
    bootstrap_approval_scenarios,
)

F045_SCENARIO = "resource_user_invite_confirmation"
F046_SCENARIO = "knowledge_space_file_change_request"
REQUIRED_SCENARIOS = {F045_SCENARIO, F046_SCENARIO}
REQUIRED_RESOURCE_TYPES = {"knowledge_space", "channel"}
LEGACY_SCENARIOS = {
    "menu_access_request",
    "channel_subscribe_request",
    "knowledge_space_subscribe_request",
}


class _Policy:
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE
    protocol_version = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION

    def __init__(self, scenario_code: str) -> None:
        self.scenario_code = scenario_code

    async def validate_submission(self, command) -> None:
        return None

    async def authorize_decision(self, context) -> None:
        return None


class _Subscriber:
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE
    protocol_version = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version = APPROVAL_DECISION_EVENT_VERSION

    def __init__(self, scenario_code: str) -> None:
        self.scenario_code = scenario_code
        self.subscriber_key = scenario_code

    async def accept(self, event) -> None:
        return None


class _ResourceExecutorRegistry:
    def __init__(self) -> None:
        self.executors: dict[str, object] = {}
        self.frozen = False

    def register(self, resource_type: str, executor: object) -> None:
        if self.frozen:
            raise RuntimeError("resource executor registry is frozen")
        if resource_type in self.executors:
            raise ValueError(f"resource executor already registered: {resource_type}")
        self.executors[resource_type] = executor

    def freeze(self, *, required_resource_types: set[str]) -> None:
        missing = required_resource_types - self.executors.keys()
        if missing:
            raise ValueError(f"resource executor missing: {sorted(missing)}")
        self.frozen = True


def _legacy_handlers() -> tuple[tuple[str, object], ...]:
    return tuple((scenario_code, object()) for scenario_code in sorted(LEGACY_SCENARIOS))


def _components(
    *,
    policies: tuple[object, ...] | None = None,
    subscribers: tuple[object, ...] | None = None,
    legacy_handlers: tuple[tuple[str, object], ...] | None = None,
    resource_executors: dict[str, object] | None = None,
    executor_registry: _ResourceExecutorRegistry | None = None,
) -> ApprovalScenarioBootstrapComponents:
    return ApprovalScenarioBootstrapComponents(
        policies=policies
        or (
            _Policy(F045_SCENARIO),
            _Policy(F046_SCENARIO),
        ),
        subscribers=subscribers
        or (
            _Subscriber(F045_SCENARIO),
            _Subscriber(F046_SCENARIO),
        ),
        legacy_handlers=legacy_handlers or _legacy_handlers(),
        resource_executor_registry=executor_registry or _ResourceExecutorRegistry(),
        resource_executors=resource_executors
        or {
            "knowledge_space": object(),
            "channel": object(),
        },
    )


@pytest.fixture(autouse=True)
def reset_bootstrap_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        bootstrap_module,
        "_approval_scenario_registry",
        None,
        raising=False,
    )


def test_bootstrap_is_synchronous_io_free_and_returns_the_same_frozen_registry(
    monkeypatch: pytest.MonkeyPatch,
):
    components = _components()
    component_factory = MagicMock(return_value=components)

    def fail_network(*args, **kwargs):
        raise AssertionError("approval scenario bootstrap must not perform network I/O")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    first = bootstrap_approval_scenarios(component_factory=component_factory)
    second = bootstrap_approval_scenarios(component_factory=component_factory)

    assert isinstance(first, ApprovalRegistry)
    assert not inspect.isawaitable(first)
    assert second is first
    component_factory.assert_called_once_with()
    assert components.resource_executor_registry.frozen is True
    assert set(components.resource_executor_registry.executors) == REQUIRED_RESOURCE_TYPES
    with pytest.raises(RuntimeError, match="frozen"):
        first.register_policy(_Policy("late_registration"))


async def test_bootstrap_registers_both_new_scenarios_and_three_legacy_handlers():
    components = _components()
    registry = bootstrap_approval_scenarios(component_factory=lambda: components)

    for scenario_code in REQUIRED_SCENARIOS:
        assert registry.get_policy(scenario_code).scenario_code == scenario_code
        assert registry.get_subscriber(scenario_code).scenario_code == scenario_code

    for scenario_code, handler in components.legacy_handlers:
        assert await registry.get_handler(scenario_code) is handler


@pytest.mark.parametrize("duplicate_kind", ["policy", "subscriber", "handler"])
def test_duplicate_components_fail_bootstrap(duplicate_kind: str):
    components = _components()
    if duplicate_kind == "policy":
        components = _components(
            policies=(
                _Policy(F045_SCENARIO),
                _Policy(F045_SCENARIO),
                _Policy(F046_SCENARIO),
            )
        )
    elif duplicate_kind == "subscriber":
        components = _components(
            subscribers=(
                _Subscriber(F045_SCENARIO),
                _Subscriber(F045_SCENARIO),
                _Subscriber(F046_SCENARIO),
            )
        )
    else:
        duplicate_handler = object()
        components = _components(
            legacy_handlers=(
                ("menu_access_request", duplicate_handler),
                ("menu_access_request", duplicate_handler),
                ("channel_subscribe_request", object()),
                ("knowledge_space_subscribe_request", object()),
            )
        )

    with pytest.raises(ValueError, match="already registered"):
        bootstrap_approval_scenarios(component_factory=lambda: components)


@pytest.mark.parametrize(
    "missing_kind",
    ["policy", "subscriber", "executor"],
)
def test_missing_required_component_fails_bootstrap(missing_kind: str):
    if missing_kind == "policy":
        components = _components(policies=(_Policy(F045_SCENARIO),))
    elif missing_kind == "subscriber":
        components = _components(subscribers=(_Subscriber(F045_SCENARIO),))
    else:
        components = _components(resource_executors={"knowledge_space": object()})

    with pytest.raises(ValueError, match="missing"):
        bootstrap_approval_scenarios(component_factory=lambda: components)


@pytest.mark.parametrize(
    "version_kind",
    ["policy_protocol", "subscriber_protocol", "subscriber_event", "completion_mode"],
)
def test_protocol_or_completion_version_mismatch_fails_bootstrap(
    version_kind: str,
):
    policy = _Policy(F045_SCENARIO)
    subscriber = _Subscriber(F045_SCENARIO)
    if version_kind == "policy_protocol":
        policy.protocol_version = 99
    elif version_kind == "subscriber_protocol":
        subscriber.protocol_version = 99
    elif version_kind == "subscriber_event":
        subscriber.event_version = 99
    else:
        subscriber.completion_mode = "legacy_outbox"
    components = _components(
        policies=(policy, _Policy(F046_SCENARIO)),
        subscribers=(subscriber, _Subscriber(F046_SCENARIO)),
    )

    with pytest.raises(ValueError, match="mismatch"):
        bootstrap_approval_scenarios(component_factory=lambda: components)


def test_failed_bootstrap_is_not_cached():
    with pytest.raises(ValueError, match="missing"):
        bootstrap_approval_scenarios(component_factory=lambda: _components(subscribers=(_Subscriber(F045_SCENARIO),)))

    registry = bootstrap_approval_scenarios(component_factory=lambda: _components())

    assert registry.get_subscriber(F046_SCENARIO).scenario_code == F046_SCENARIO


def test_api_create_app_calls_the_shared_bootstrap_before_return(
    monkeypatch: pytest.MonkeyPatch,
):
    import bisheng.main as api_main

    bootstrap = MagicMock(return_value=ApprovalRegistry())
    monkeypatch.setattr(
        api_main,
        "bootstrap_approval_scenarios",
        bootstrap,
        raising=False,
    )

    app = api_main.create_app()

    bootstrap.assert_called_once_with()
    assert app is not None


def _load_worker_create_celery_app_function():
    worker_main_path = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "main.py"
    tree = ast.parse(worker_main_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_celery_app"
    )
    namespace: dict[str, object] = {}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
            str(worker_main_path),
            "exec",
        ),
        namespace,
    )
    return namespace["create_celery_app"], namespace


def test_celery_create_app_calls_the_same_shared_bootstrap():
    create_celery_app, namespace = _load_worker_create_celery_app_function()
    bootstrap = MagicMock(return_value=ApprovalRegistry())
    celery_app = SimpleNamespace(config_from_object=MagicMock())
    namespace.update(
        {
            "bootstrap_approval_scenarios": bootstrap,
            "set_logger_config": MagicMock(),
            "settings": SimpleNamespace(logger_conf=object()),
            "Celery": MagicMock(return_value=celery_app),
        }
    )

    result = create_celery_app()

    bootstrap.assert_called_once_with()
    assert result is celery_app
