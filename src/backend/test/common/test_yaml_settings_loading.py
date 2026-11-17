"""Exercise the YAML loader with real Settings validation and no DB/cache startup."""

import ast
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from bisheng.core.config.credential_loader import config_path, load_config, validate_runtime
from bisheng.core.config.secret_crypto import CredentialConfigurationError
from bisheng.core.config.settings import Settings


@pytest.fixture
def loader():
    # Importing config_service initializes global settings and infrastructure.
    # Compile its actual loader methods against the real Settings model instead.
    path = Path(__file__).parents[2] / "bisheng/common/services/config_service.py"
    tree = ast.parse(path.read_text())
    service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConfigService")
    methods = [
        node
        for node in service.body
        if isinstance(node, ast.FunctionDef) and node.name in {"env_var_constructor", "load_settings_from_yaml"}
    ]
    namespace = {
        "Settings": Settings,
        "yaml": yaml,
        "os": os,
        "logger": Mock(),
        "__file__": str(path),
        "load_config": load_config,
        "config_path": config_path,
        "validate_runtime": validate_runtime,
    }
    isolated = ast.ClassDef(
        name="ConfigService",
        bases=[ast.Name(id="Settings", ctx=ast.Load())],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    exec(compile(ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[])), str(path), "exec"), namespace)
    return namespace["ConfigService"], namespace["logger"]


def _config(tmp_path, body: str):
    """Write a config with the explicit database_url the runtime loader requires."""
    path = tmp_path / "config.yaml"
    path.write_text(f'database_url: "sqlite:///{tmp_path}/bisheng.db"\n{body}')
    return str(path)


@pytest.mark.parametrize("key", ["workflow_conf", "unknown_setting"])
def test_unknown_top_level_keys_warn_without_blocking_startup(tmp_path, loader, key):
    service, logger = loader
    path = _config(tmp_path, f"debug: true\n{key}:\n  timeout: secret-value\n")

    loaded = service.load_settings_from_yaml(path)

    assert loaded.debug is True
    assert key not in loaded.model_dump()
    logger.warning.assert_called_once()
    warning = str(logger.warning.call_args)
    assert key in warning
    assert "secret-value" not in warning


def test_retired_workflow_field_is_no_longer_declared():
    assert "workflow_conf" not in Settings.model_fields


def test_known_fields_are_still_validated(tmp_path, loader):
    service, _ = loader
    path = _config(tmp_path, "cookie_conf:\n  jwt_token_expire_time: not-an-integer\n")

    # The runtime loader reports the failing field path, never its value.
    with pytest.raises(CredentialConfigurationError, match="cookie_conf") as error:
        service.load_settings_from_yaml(path)
    assert "not-an-integer" not in str(error.value)


def test_known_credential_fields_still_reject_plaintext(tmp_path, loader):
    service, _ = loader
    path = _config(
        tmp_path,
        "object_storage:\n  type: minio\n  minio:\n    access_key: user\n    secret_key: plain-secret\n",
    )

    with pytest.raises(CredentialConfigurationError, match="secret_key") as error:
        service.load_settings_from_yaml(path)
    assert "plain-secret" not in str(error.value)


def test_known_environment_values_still_load(tmp_path, monkeypatch, loader):
    service, logger = loader
    monkeypatch.setenv("BISHENG_TEST_CACHE", "InMemoryCache")
    path = _config(tmp_path, "cache: !env ${BISHENG_TEST_CACHE}\ndebug: true\n")

    assert service.load_settings_from_yaml(path).cache == "InMemoryCache"
    logger.warning.assert_not_called()


def test_missing_environment_variable_still_blocks_startup(tmp_path, monkeypatch, loader):
    service, _ = loader
    monkeypatch.delenv("BISHENG_TEST_MISSING_CACHE", raising=False)
    path = _config(tmp_path, "cache: !env ${BISHENG_TEST_MISSING_CACHE}\n")

    with pytest.raises(CredentialConfigurationError, match="BISHENG_TEST_MISSING_CACHE"):
        service.load_settings_from_yaml(path)


def test_invalid_yaml_still_blocks_startup(tmp_path, loader):
    service, _ = loader
    path = _config(tmp_path, "cache: [unterminated\n")

    with pytest.raises(CredentialConfigurationError, match="invalid or unreadable YAML"):
        service.load_settings_from_yaml(path)
