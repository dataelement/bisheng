"""Read explicit credential inputs as data, never shell or executable code."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from bisheng.core.config.secret_crypto import CredentialConfigurationError

COMPONENTS = ("mysql", "redis", "minio", "elasticsearch", "milvus", "telemetry_elasticsearch")
# Public defaults/known weak choices form a rejection list, never credentials.
_WEAK = {"1234", "123456", "12345678", "password", "root", "redis", "elastic", "minioadmin", "milvus", "changeme"}


def validate_password(value: str, component: str) -> str:
    if not isinstance(value, str) or not value or any(x in value for x in ("\x00", "\n", "\r")):
        raise CredentialConfigurationError(f"{component}: nonempty single-line credential required")
    if value.lower() in _WEAK or value.startswith("<") or value.startswith("${"):
        raise CredentialConfigurationError(f"{component}: default or placeholder credential rejected")
    if component == "minio" and len(value) < 8:
        raise CredentialConfigurationError("minio: credential below component minimum")
    if component in ("elasticsearch", "telemetry_elasticsearch") and len(value) < 6:
        raise CredentialConfigurationError(f"{component}: credential below component minimum")
    if component == "milvus" and len(value.encode("utf-8")) > 72:
        raise CredentialConfigurationError("milvus: credential exceeds component limit")
    return value


def is_weak(value: str, component: str | None = None) -> bool:
    if component is not None:
        try:
            validate_password(value, component)
            return False
        except CredentialConfigurationError:
            return True
    return not value or value.lower() in _WEAK


def read_secret(path: str | Path) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CredentialConfigurationError("credential_file: cannot be read") from None
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if not value or any(x in value for x in ("\n", "\r", "\x00")):
        raise CredentialConfigurationError("credential_file: nonempty single-line value required")
    return value


def read_inputs(path: str | Path | None) -> dict:
    if path is None:
        return {}
    source = Path(path).resolve()
    try:
        data = yaml.safe_load(source.read_text())
    except (OSError, UnicodeError, yaml.YAMLError):
        raise CredentialConfigurationError("inputs: invalid or unreadable document") from None
    if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1:
        raise CredentialConfigurationError("inputs: version 1 object required")
    if set(data) - {"version", *COMPONENTS}:
        raise CredentialConfigurationError("inputs: unknown component")
    result = {}
    for name in COMPONENTS:
        if name not in data:
            continue
        item = data[name]
        allowed = {
            "mysql": {"password_file"},
            "redis": {"password_file", "sentinel_password_file"},
            "minio": {"secret_key_file", "access_key_file"},
            "elasticsearch": {"username", "password_file"},
            "telemetry_elasticsearch": {"username", "password_file"},
            "milvus": {"user", "password_file", "token_file"},
        }[name]
        if not isinstance(item, dict) or set(item) - allowed:
            raise CredentialConfigurationError(f"{name}: unsupported input fields")
        loaded = {}
        for key, value in item.items():
            if not isinstance(value, str):
                raise CredentialConfigurationError(f"{name}: text input required")
            if key.endswith("_file"):
                target = Path(value)
                target = target if target.is_absolute() else source.parent / target
                loaded[key[:-5]] = read_secret(target)
            else:
                loaded[key] = value
        secret = loaded.get("secret_key" if name == "minio" else "password")
        if name == "milvus" and loaded.get("token"):
            if secret or loaded.get("user"):
                raise CredentialConfigurationError("milvus: conflicting authentication inputs")
            user, separator, secret = loaded["token"].partition(":")
            if not user or not separator:
                raise CredentialConfigurationError("milvus: username/password token required")
        if secret is None:
            raise CredentialConfigurationError(f"{name}: password file required")
        validate_password(secret, name)
        if loaded.get("sentinel_password"):
            validate_password(loaded["sentinel_password"], "redis")
        result[name] = loaded
    return result


def write_private(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
