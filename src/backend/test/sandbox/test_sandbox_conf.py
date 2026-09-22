"""Sandbox configuration (F068 isolation-environment substrate)."""

from __future__ import annotations

import os

import pytest

from bisheng.core.config.settings import SandboxConf, Settings

_ENV_PREFIX = "BS_SANDBOX_CONF__"


@pytest.fixture
def clean_sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIX):
            monkeypatch.delenv(key, raising=False)


def test_sandbox_conf_defaults_without_yaml_section(clean_sandbox_env: None) -> None:
    settings = Settings()
    conf = settings.sandbox_conf
    assert conf.discover_host_pattern == "code-runner-{n}"
    assert conf.discover_index_start == 1
    assert conf.discover_ttl_s == 60
    assert conf.code_node_enabled is True
    assert conf.endpoints == []


def test_sandbox_conf_env_overrides_discover_host_pattern(
    clean_sandbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{_ENV_PREFIX}DISCOVER_HOST_PATTERN", "code-runner-{n}.code-runner")
    settings = Settings()
    assert settings.sandbox_conf.discover_host_pattern == "code-runner-{n}.code-runner"


def test_sandbox_conf_has_no_orchestrator_enum(clean_sandbox_env: None) -> None:
    assert "deploy_mode" not in SandboxConf.model_fields
    assert "orchestrator" not in SandboxConf.model_fields
    settings = Settings(sandbox_conf={"deploy_mode": "k8s", "orchestrator": "compose"})
    assert not hasattr(settings.sandbox_conf, "deploy_mode")
    assert not hasattr(settings.sandbox_conf, "orchestrator")
    dumped = settings.sandbox_conf.model_dump()
    assert "deploy_mode" not in dumped
    assert "orchestrator" not in dumped


def test_sandbox_conf_endpoints_default_empty(clean_sandbox_env: None) -> None:
    settings = Settings()
    assert isinstance(settings.sandbox_conf.endpoints, list)
    assert settings.sandbox_conf.endpoints == []


def test_sandbox_conf_ignores_runner_only_knobs(clean_sandbox_env: None) -> None:
    assert "pool_lease_ttl_s" not in SandboxConf.model_fields
    assert "max_sessions_per_replica" not in SandboxConf.model_fields
    assert "enable_uid_isolation" not in SandboxConf.model_fields
    settings = Settings(
        sandbox_conf={
            "pool_lease_ttl_s": 60,
            "max_sessions_per_replica": 2,
            "enable_uid_isolation": False,
        }
    )
    dumped = settings.sandbox_conf.model_dump()
    assert "pool_lease_ttl_s" not in dumped
    assert "max_sessions_per_replica" not in dumped
    assert "enable_uid_isolation" not in dumped
