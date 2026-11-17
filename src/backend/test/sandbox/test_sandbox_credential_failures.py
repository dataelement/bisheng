"""Exercise real merge/probe bodies without the unrelated API import graph.

Coverage: AC-29, AC-31. Nonempty corrupt credentials cannot change identity.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet, InvalidToken

from bisheng.core.config.secret_crypto import CredentialConfigurationError, decrypt_token, encrypt_token, get_keyring
from bisheng.core.config.settings import SandboxConf

BACKEND = Path(__file__).resolve().parents[2]


def function(path, name, namespace):
    tree = ast.parse((BACKEND / path).read_text())
    node = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    path.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(path))
    get_keyring.cache_clear()
    yield
    get_keyring.cache_clear()


def namespace():
    return {
        "decrypt_token": decrypt_token,
        "InvalidToken": InvalidToken,
        "CredentialConfigurationError": CredentialConfigurationError,
        "logger": MagicMock(),
    }


def test_bad_page_token_never_falls_back():
    merge = function("bisheng/common/services/config_service.py", "_merge_sandbox_page", namespace())
    with pytest.raises(CredentialConfigurationError):
        merge(SandboxConf(token="deployment-identity"), {"token_enc": "invalid", "endpoints": []})


def test_valid_page_token_preserves_page_identity():
    merge = function("bisheng/common/services/config_service.py", "_merge_sandbox_page", namespace())
    token = encrypt_token("page-identity").decode()
    result = merge(SandboxConf(token="deployment-identity"), {"token_enc": token, "endpoints": []})
    assert result.token == "page-identity"


def test_missing_page_token_preserves_normal_deployment_source():
    merge = function("bisheng/common/services/config_service.py", "_merge_sandbox_page", namespace())
    base = SandboxConf(token="deployment-identity")
    assert merge(base, {"token_enc": "", "endpoints": []}) is base


def test_probe_mask_does_not_hide_bad_stored_token():
    scope = namespace()
    scope.update(
        {
            "SANDBOX_TOKEN_MASK": "********",
            "_read_stored_payload": lambda: {"token_enc": "invalid"},
            "settings": SimpleNamespace(sandbox_conf=SimpleNamespace(token="deployment-identity")),
        }
    )
    probe = function("bisheng/tool/domain/services/sandbox_conf_service.py", "_probe_token", scope)
    with pytest.raises(CredentialConfigurationError):
        probe("********")
