"""Bounded encrypted application environments, without persistence or orchestration."""

import json
import re
from collections.abc import Mapping, Sequence

from cryptography.fernet import Fernet, InvalidToken

from bisheng.common.errcode.app_publish import AppSecretEncryptionUnavailableError, AppSecretInvalidError

MAX_NAMES = 64
MAX_VALUE_BYTES = 16 * 1024
MAX_ENVIRONMENT_BYTES = 128 * 1024
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z", re.ASCII)
_RESERVED_PREFIXES = ("BISHENG_", "RTM_", "KUBERNETES_", "MINIO_", "OPENAI_", "LD_")
_RESERVED_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "PYTHONPATH",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "PORT",
        "HOST",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "FTP_PROXY",
        "VIRTUAL_ENV",
        "PWD",
        "SHELL",
        "USER",
        "LOGNAME",
        "ENV",
        "BASH_ENV",
        "GUNICORN_CMD_ARGS",
        "UVICORN_HOST",
        "UVICORN_PORT",
        "NPM_CONFIG_PREFIX",
    }
)
_DOMAIN = "app-secret-config-v1"


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise AppSecretInvalidError(reason="invalid_name")
    upper = name.upper()
    if upper in _RESERVED_NAMES or upper.startswith(_RESERVED_PREFIXES):
        raise AppSecretInvalidError(reason="reserved_name")
    return name


def validate_value(value: str) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise AppSecretInvalidError(reason="invalid_value")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise AppSecretInvalidError(reason="invalid_encoding") from None
    if size > MAX_VALUE_BYTES:
        raise AppSecretInvalidError(reason="value_too_large")
    return value


def validate_environment(environment: Mapping[str, str]) -> None:
    if len(environment) > MAX_NAMES:
        raise AppSecretInvalidError(reason="too_many_names")
    size = 0
    for name, value in environment.items():
        validate_name(name)
        validate_value(value)
        size += len(name.encode("ascii")) + len(value.encode("utf-8")) + 2
    if size > MAX_ENVIRONMENT_BYTES:
        raise AppSecretInvalidError(reason="environment_too_large")


def compare_environment(names: Sequence[str], saved: Mapping[str, str], running: Mapping[str, str] | None):
    """Compare only approved references, against the actual frozen instance."""
    if running is None or any(name not in running for name in names):
        return "unknown", []
    changed = sorted({name for name in names if saved.get(name, "") != running[name]})
    return ("different" if changed else "same"), changed


class AppSecretCipher:
    def __init__(self, key: str | None):
        try:
            self._cipher = Fernet(key.encode())
        except (ValueError, TypeError, AttributeError):
            raise AppSecretEncryptionUnavailableError() from None

    @classmethod
    def configured(cls):
        from bisheng.common.services.config_service import settings

        return cls(settings.app_runtime.runtime_payload_key)

    def encrypt(self, entries: dict, *, tenant_id: int, app_id: str) -> str:
        validate_environment({name: entry["value"] for name, entry in entries.items()})
        envelope = {"domain": _DOMAIN, "tenant_id": tenant_id, "app_id": app_id, "entries": entries}
        return self._cipher.encrypt(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()).decode()

    def decrypt(self, ciphertext: str, *, tenant_id: int, app_id: str) -> dict:
        try:
            # Bound before parsing authenticated but possibly obsolete/malformed data.
            if not isinstance(ciphertext, str) or len(ciphertext) > 512 * 1024:
                raise ValueError
            envelope = json.loads(self._cipher.decrypt(ciphertext.encode()))
            if (envelope["domain"], envelope["tenant_id"], envelope["app_id"]) != (_DOMAIN, tenant_id, app_id):
                raise ValueError
            entries = envelope["entries"]
            if not isinstance(entries, dict):
                raise ValueError
            for entry in entries.values():
                if not isinstance(entry, dict) or set(entry) != {"value", "updated_by", "updated_at"}:
                    raise ValueError
                if type(entry["updated_by"]) is not int or not isinstance(entry["updated_at"], str):
                    raise ValueError
            validate_environment({name: entry["value"] for name, entry in entries.items()})
            return entries
        except (InvalidToken, ValueError, TypeError, KeyError, AttributeError, AppSecretInvalidError):
            raise AppSecretEncryptionUnavailableError() from None
