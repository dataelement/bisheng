"""Redis object encoding: managed authenticated envelopes or legacy pickle.

Managed mode (BS_SECRET_KEYS_FILE set) writes BSREDIS1 envelopes and never
unpickles raw cache values. Legacy mode (unset) matches feat/3.1.0-beta1:
pickle.dumps / pickle.loads for application objects.
"""

import base64
import binascii
import json
import pickle

from bisheng.core.config.secret_crypto import CredentialDecryptionError, get_keyring, is_legacy_secret_mode

_PREFIX = b"BSREDIS1:"
_DOMAIN = "bisheng.redis.object"


class RedisSerializationError(ValueError):
    """Untrusted cache input was rejected without exposing its content."""


def _key(key: str | bytes) -> str:
    if isinstance(key, bytes):
        return key.decode("utf-8")
    if not isinstance(key, str):
        raise TypeError("Redis object keys must be text or UTF-8 bytes")
    return key


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate property")
        result[name] = value
    return result


def encode_redis_value(key, value) -> bytes:
    if is_legacy_secret_mode():
        return pickle.dumps(value)
    document = {
        "domain": _DOMAIN,
        "version": 1,
        "key": _key(key),
        "payload": base64.b64encode(pickle.dumps(value)).decode("ascii"),
    }
    return _PREFIX + get_keyring().encrypt(json.dumps(document, separators=(",", ":"), ensure_ascii=True))


def decode_redis_value(key, value):
    if is_legacy_secret_mode():
        if not isinstance(value, bytes):
            raise RedisSerializationError("Redis object authentication failed")
        if value.startswith(_PREFIX):
            # Rare: managed-written value read under legacy; treat as miss upstream.
            raise RedisSerializationError("Redis object authentication failed")
        try:
            return pickle.loads(value)
        except Exception:
            raise RedisSerializationError("Redis object authentication failed") from None

    # Resolve configuration outside the untrusted-input handler: deployment errors
    # must not be mislabeled cache corruption or trigger a legacy fallback.
    ring = get_keyring()
    try:
        if not isinstance(value, bytes) or not value.startswith(_PREFIX):
            raise ValueError("unsupported envelope")
        text = ring.decrypt_primary(value[len(_PREFIX) :])
        data = json.loads(text, object_pairs_hook=_unique)
        if (
            not isinstance(data, dict)
            or set(data) != {"domain", "version", "key", "payload"}
            or data["domain"] != _DOMAIN
            or type(data["version"]) not in (int,)  # Reject bool and integer subclasses.
            or data["version"] != 1
            or data["key"] != _key(key)
            or not isinstance(data["payload"], str)
        ):
            raise ValueError("invalid binding")
        payload = base64.b64decode(data["payload"], validate=True)
    except (CredentialDecryptionError, ValueError, TypeError, UnicodeError, binascii.Error):
        raise RedisSerializationError("Redis object authentication failed") from None
    # This is deliberately the only application unpickling point, after all gates.
    return pickle.loads(payload)
