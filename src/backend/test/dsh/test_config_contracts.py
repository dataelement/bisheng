"""Capacity configuration remains finite when disabled and is shared by production factories."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from bisheng.dsh.config import DshSettings


def test_disabled_defaults_and_invalid_capacity_bounds():
    settings = DshSettings()
    assert settings.enabled is False
    assert settings.quota_memory_budget_bytes == 512 * 1024 * 1024
    assert settings.quota_memory_headroom_bytes == 64 * 1024 * 1024
    for values in (
        {"quota_memory_budget_bytes": 0},
        {"quota_memory_budget_bytes": 1024 * 1024, "quota_memory_headroom_bytes": 1024 * 1024},
        {"quota_backlog_high_watermark": 0},
        {"quota_retention_seconds": 0},
        {"quota_projection_max_batches": 101},
        {"quota_projection_max_seconds": 0.0},
    ):
        with pytest.raises(ValidationError):
            DshSettings(**values)


async def _construct_enabled_factories():
    from bisheng.dsh.operations_runtime import OperationsRuntime
    from bisheng.dsh.runtime import get_model_runtime

    settings = DshSettings(
        enabled=True,
        installation_id="config-test",
        platform_public_url="https://bisheng.example.com",
        gateway_internal_url="https://gateway.example.com",
        quota_memory_budget_bytes=256 * 1024 * 1024,
        quota_memory_headroom_bytes=32 * 1024 * 1024,
        quota_backlog_high_watermark=7654,
        backlog_stop_seconds=45,
        quota_retention_seconds=86400,
        quota_projection_max_batches=3,
        quota_projection_max_seconds=2.5,
    )
    # Construction is deliberately network-free; port 1 must never be contacted.
    worker = OperationsRuntime(settings, object())
    api = await get_model_runtime(SimpleNamespace(settings=settings))
    try:
        for quota in (worker.quota, api.quota):
            assert quota.pressure_args() == ["0", str(32 * 1024 * 1024), "7654", "45000"]
            assert not quota.topology.ready
        assert worker.projection.retention_seconds == 86400
        assert worker.projection.max_batches == 3
        assert worker.projection.max_seconds == 2.5
    finally:
        await worker.quota.redis.aclose()
        await api.quota.redis.aclose()


def test_enabled_api_and_worker_factories_use_identical_capacity(tmp_path):
    import os
    import subprocess
    import sys

    configuration = tmp_path / "config.yaml"
    configuration.write_text(
        "database_url: sqlite:///" + str(tmp_path / "config-test.db") + "\n"
        "redis_url: redis://127.0.0.1:1/0\n"
        "celery_redis_url: redis://127.0.0.1:1/0\n"
        "logger_conf:\n  log_level: ERROR\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio; from test.dsh.test_config_contracts import _construct_enabled_factories; asyncio.run(_construct_enabled_factories())",
        ],
        env={**os.environ, "config": str(configuration), "MPLCONFIGDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-5000:]


@pytest.mark.parametrize("document", ["{}", "dsh: {}", "dsh:\n  enabled: false"])
def test_application_settings_load_optional_typed_dsh(document):
    import yaml

    from bisheng.core.config.settings import Settings

    settings = Settings.model_validate(yaml.safe_load(document))
    assert isinstance(settings.dsh, DshSettings)
    assert settings.dsh.enabled is False


def test_application_settings_reject_duplicate_deployment_configuration():
    from bisheng.core.config.settings import Settings

    settings = Settings(dsh={"billing_timezone": "Asia/Shanghai"})
    assert settings.dsh.billing_timezone == "Asia/Shanghai"
    assert DshSettings().billing_timezone == "Asia/Shanghai"
    for field in (
        "verified_model_capabilities",
        "quota_redis_url",
        "outbound_hmac_secret",
        "inbound_hmac_secret",
        "access_algorithms",
        "access_issuer",
    ):
        with pytest.raises(ValidationError):
            Settings(dsh={field: "obsolete"})
    with pytest.raises(ValidationError):
        Settings(dsh={"enabled": True})


def test_application_schema_has_no_duplicate_trust_or_model_settings():
    schema = DshSettings.model_json_schema()
    assert schema["additionalProperties"] is False
    assert all(field.get("description") for field in schema["properties"].values())
    assert not any("hmac" in field or "capabilities" in field or "redis_url" in field for field in schema["properties"])


def test_settings_serialization_preserves_typed_configuration():
    from bisheng.core.config.settings import Settings

    settings = Settings(dsh={"billing_timezone": "Asia/Shanghai"})
    payload = settings.model_dump(mode="json", include={"dsh"})
    assert payload["dsh"]["billing_timezone"] == "Asia/Shanghai"
    assert Settings.model_validate(payload).dsh == settings.dsh
