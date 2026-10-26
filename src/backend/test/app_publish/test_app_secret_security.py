"""Focused secret boundaries. 覆盖 AC: AC-68, AC-78, AC-79, AC-90."""

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from bisheng.common.errcode.app_publish import AppSecretEncryptionUnavailableError, AppSecretInvalidError


def security():
    from bisheng.app_publish.domain import secret_security

    return secret_security


def test_cipher_authenticates_tenant_app_and_rejects_corruption():
    cipher = security().AppSecretCipher(Fernet.generate_key().decode())
    entries = {"API_KEY": {"value": "敏感\n q ", "updated_by": 11, "updated_at": "2026-10-24T00:00:00"}}
    sealed = cipher.encrypt(entries, tenant_id=2, app_id="a")
    assert entries["API_KEY"]["value"] not in sealed
    assert cipher.decrypt(sealed, tenant_id=2, app_id="a") == entries
    for tenant, app, value in [(3, "a", sealed), (2, "b", sealed), (2, "a", sealed[:-5] + "wrong")]:
        with pytest.raises(AppSecretEncryptionUnavailableError) as exc:
            cipher.decrypt(value, tenant_id=tenant, app_id=app)
        assert "敏感" not in str(exc.value)
    with pytest.raises(AppSecretEncryptionUnavailableError):
        security().AppSecretCipher(Fernet.generate_key().decode()).decrypt(sealed, tenant_id=2, app_id="a")


@pytest.mark.parametrize("key", ["", "invalid", None])
def test_invalid_key_fails_closed(key):
    with pytest.raises(AppSecretEncryptionUnavailableError):
        security().AppSecretCipher(key).encrypt({}, tenant_id=2, app_id="a")


@pytest.mark.parametrize(
    "name",
    [
        "",
        "a-b",
        "a.b",
        "9A",
        "中文",
        "x" * 129,
        "BISHENG_TOKEN",
        "rtm_key",
        "MINIO_URL",
        "KUBERNETES_X",
        "OPENAI_API_KEY",
        "HTTP_PROXY",
        "all_proxy",
        "PATH",
        "HOME",
        "LD_PRELOAD",
        "PYTHONPATH",
        "NODE_OPTIONS",
        "PORT",
        "HOST",
    ],
)
def test_invalid_and_reserved_names(name):
    with pytest.raises(AppSecretInvalidError):
        security().validate_name(name)


def test_values_preserve_bytes_and_enforce_environment_bounds():
    module = security()
    for value in ["", " ", "\n", "😀\n\t ' $ { } "]:
        assert module.validate_value(value) == value
    assert module.validate_value("x" * 16384) == "x" * 16384
    for value in ["x\0y", "😀" * 4097, 4, "\ud800"]:
        with pytest.raises(AppSecretInvalidError) as exc:
            module.validate_value(value)
        assert "😀" not in str(exc.value)
    with pytest.raises(AppSecretInvalidError):
        module.validate_environment({f"S{i}": "" for i in range(65)})
    with pytest.raises(AppSecretInvalidError):
        module.validate_environment({f"S{i}": "x" * 16384 for i in range(9)})


def test_difference_uses_declared_actual_values_not_revisions():
    compare = security().compare_environment
    assert compare(["A"], {"A": "before", "PRIVATE": "ignored"}, {"A": "before"}) == ("same", [])
    assert compare(["A"], {"A": "after"}, {"A": "before"}) == ("different", ["A"])
    assert compare(["A"], {"A": "before"}, {"A": "before"}) == ("same", [])
    assert compare(["A"], {}, {"A": ""}) == ("same", [])
    assert compare(["A"], {}, {}) == ("unknown", [])
    assert compare(["A"], {}, None) == ("unknown", [])
    assert compare([], {"PRIVATE": "x"}, {}) == ("same", [])


def test_request_schemas_are_strict_and_repr_hides_value():
    from bisheng.app_publish.domain.schemas.app_secrets import SecretDeleteInput, SecretRebuildInput, SecretSaveInput

    request = SecretSaveInput(value="never-print-this", expected_revision=0)
    assert "never-print-this" not in repr(request)
    assert request.value.get_secret_value() == "never-print-this"
    for body in [
        {"value": 5, "expected_revision": 0},
        {"value": "x", "expected_revision": -1},
        {"value": "x", "expected_revision": 0, "env": {}},
    ]:
        with pytest.raises(ValidationError):
            SecretSaveInput(**body)
    assert SecretDeleteInput(expected_revision=1).confirm_online_impact is False
    with pytest.raises(ValidationError):
        SecretRebuildInput(
            request_id="r",
            expected_version_id="v",
            expected_config_revision=0,
            expected_route_epoch=1,
            confirm_restart=False,
        )
