"""Retired control protocol cannot be selected or send old lifecycle RPCs."""

import pytest
from pydantic import ValidationError

from bisheng.core.config.app_runtime import AppRuntimeConf


def test_default_is_v2_and_explicit_legacy_or_unknown_is_refused(monkeypatch):
    monkeypatch.delenv("BISHENG_RUNTIME_PROTOCOL_VERSION", raising=False)
    assert AppRuntimeConf().runtime_protocol_version == 2
    for value in (1, 0, 3):
        with pytest.raises(ValidationError):
            AppRuntimeConf(runtime_protocol_version=value)
    monkeypatch.setenv("BISHENG_RUNTIME_PROTOCOL_VERSION", "1")
    with pytest.raises(ValidationError):
        AppRuntimeConf()


async def test_retired_control_rpc_refused_before_http(monkeypatch):
    from bisheng.app_runtime.domain.services.orchestrator_client import OrchestratorClient
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError

    client = OrchestratorClient()
    with pytest.raises(AppOrchestratorUnavailableError, match="retired"):
        await client._request("POST", "/v1/intents/deploy", json={}, op="deploy")
