"""F133 server-owned resource defaults and formal runtime timeout wiring."""

import pytest
from pydantic import ValidationError

from bisheng.core.config.settings import WorkflowConf

DEFAULTS = {
    "queue_seconds": 120,
    "run_seconds": 300,
    "wait_seconds": 900,
    "retain_seconds": 86400,
    "max_active_per_user": 5,
    "request_limit": 120,
    "request_window_seconds": 60,
}
MAXIMUMS = {
    "queue_seconds": 86400,
    "run_seconds": 86400,
    "wait_seconds": 86400,
    "retain_seconds": 2592000,
    "max_active_per_user": 1000,
    "request_limit": 100000,
    "request_window_seconds": 86400,
}


def test_workflow_owns_kunlian_resource_defaults():
    assert WorkflowConf().kunlian_api.model_dump() == DEFAULTS


@pytest.mark.parametrize("field", DEFAULTS)
@pytest.mark.parametrize("value", [0, -1, True, "120", 1.5, None, 10**12])
def test_resource_limits_reject_unbounded_or_non_integer_values(field, value):
    with pytest.raises(ValidationError):
        WorkflowConf(kunlian_api={field: value})


def test_resource_limits_accept_explicit_upper_bounds():
    assert WorkflowConf(kunlian_api=MAXIMUMS).kunlian_api.model_dump() == MAXIMUMS
    for field, maximum in MAXIMUMS.items():
        with pytest.raises(ValidationError):
            WorkflowConf(kunlian_api={field: maximum + 1})


def test_resource_configuration_rejects_unknown_limit_names():
    with pytest.raises(ValidationError):
        WorkflowConf(kunlian_api={"run_second": 60})


@pytest.mark.parametrize(
    "configured", [None, {"queue_seconds": 11, "run_seconds": 22, "wait_seconds": 33, "retain_seconds": 44}]
)
def test_formal_factory_passes_resource_timeouts_without_io(monkeypatch, configured):
    from bisheng.common.services.config_service import settings
    from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service

    config = WorkflowConf(kunlian_api=configured or {})
    monkeypatch.setattr(type(settings), "get_workflow_conf", lambda self: config)
    service = create_kunlian_runtime_service(resolve_user=lambda subject: None, dispatch=lambda *args: None)
    expected = configured or DEFAULTS
    for field in ("queue_seconds", "run_seconds", "wait_seconds", "retain_seconds"):
        assert getattr(service.repository, field) == expected[field]
