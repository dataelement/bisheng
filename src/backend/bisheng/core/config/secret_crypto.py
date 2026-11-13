"""Credential encryption using an explicitly supplied deployment keyring.

This module has no application imports or import-time configuration side effects.
Every process must receive BS_SECRET_KEYS_FILE before its runtime initialization.
The cached keyring is a startup snapshot: rotating files requires restarting the
process, rather than changing its encryption identity partway through a request.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_KEY_FILE_ENV = "BS_SECRET_KEYS_FILE"
_MAX_KEYRING_BYTES = 65536


class CredentialConfigurationError(ValueError):
    """A redacted, actionable configuration failure, never containing input."""


class CredentialDecryptionError(CredentialConfigurationError, InvalidToken):
    """Keep existing InvalidToken handlers compatible without exposing values."""


def _unique_properties(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate keyring property")
        result[name] = value
    return result


def _token_bytes(token: str | bytes) -> bytes:
    if isinstance(token, bytes):
        return token
    if isinstance(token, str):
        try:
            return token.encode("ascii")
        except UnicodeEncodeError:
            raise CredentialDecryptionError("credential: ciphertext cannot be decrypted") from None
    raise CredentialDecryptionError("credential: ciphertext cannot be decrypted")


@dataclass(frozen=True, repr=False)
class KeyRing:
    """Immutable cipher handles; repr never includes key material."""

    _primary: Fernet = field(repr=False)
    _readers: MultiFernet = field(repr=False)

    def encrypt(self, value: str) -> bytes:
        if not isinstance(value, str):
            raise CredentialConfigurationError("credential: encryption requires text")
        try:
            raw = value.encode("utf-8")
        except UnicodeEncodeError:
            raise CredentialConfigurationError("credential: encryption requires valid UTF-8 text") from None
        return self._primary.encrypt(raw)

    def decrypt(self, token: str | bytes) -> str:
        return self._decrypt(self._readers, token)

    def decrypt_primary(self, token: str | bytes) -> str:
        """Verify a migration without accidentally accepting a retired key."""
        return self._decrypt(self._primary, token)

    @staticmethod
    def _decrypt(cipher: Fernet | MultiFernet, token: str | bytes) -> str:
        encoded = _token_bytes(token)
        try:
            return cipher.decrypt(encoded).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            raise CredentialDecryptionError("credential: ciphertext cannot be decrypted") from None


def load_keyring(path: str | Path) -> KeyRing:
    """Read an explicit keyring, including symlink-based Kubernetes volumes.

    Permissions are checked on the opened target with fstat, not on a preceding
    path lookup. Group read is valid for fsGroup; group/world write and any world
    permission are not. This does not grant file access to a different identity.
    """
    source = Path(path)
    if not source.is_absolute():
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: absolute file path required")
    try:
        # Nonblocking open lets us reject FIFO/device paths before a read can
        # hang runtime initialization. Follow symlinks for Kubernetes volumes.
        descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: regular file required")
            if stat.S_IMODE(metadata.st_mode) & 0o027:
                raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: unsafe file permissions")
            content = stream.read(_MAX_KEYRING_BYTES + 1)
    except OSError:
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: key file cannot be read") from None
    if len(content) > _MAX_KEYRING_BYTES:
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: key file too large")
    try:
        data = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_properties)
    except (UnicodeError, ValueError):
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: invalid keyring document") from None
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "keys"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["keys"], list)
        or not data["keys"]
    ):
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: unsupported keyring structure")
    keys = data["keys"]
    if any(not isinstance(key, str) or not key for key in keys):
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: invalid Fernet key")
    if len(set(keys)) != len(keys):
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: duplicate keys")
    try:
        ciphers = [Fernet(key.encode("ascii")) for key in keys]
    except (ValueError, TypeError):
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: invalid Fernet key") from None
    return KeyRing(ciphers[0], MultiFernet(ciphers))


@lru_cache(maxsize=1)
def get_keyring() -> KeyRing:
    """Resolve this process's keyring once; there is deliberately no default."""
    path = os.environ.get(_KEY_FILE_ENV)
    if not path:
        raise CredentialConfigurationError(f"{_KEY_FILE_ENV}: external key file required")
    return load_keyring(path)


def encrypt_token(token: str) -> bytes:
    return get_keyring().encrypt(token)


def decrypt_token(token: str | bytes) -> str:
    return get_keyring().decrypt(token)
