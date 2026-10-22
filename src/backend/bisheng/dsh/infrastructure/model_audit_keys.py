"""Versioned external audit keys, independent of DSH/License signing secrets."""

import base64
import json
import os


class AuditKeyRing:
    def __init__(self, keys: dict[str, bytes], *, active_id: str | None):
        self._keys = dict(keys)
        self.active_id = active_id

    def resolve(self, key_id: str | None) -> bytes:
        key = self._keys.get(key_id)
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("Audit encryption key unavailable")
        return key

    @classmethod
    def from_environment(cls, *, active_id: str | None):
        raw = os.environ.get("BS_DSH_MODEL_AUDIT_KEYS", "{}")
        try:
            if len(raw) > 65536:
                raise ValueError("Too many audit keys")
            values = json.loads(raw)
            if not isinstance(values, dict):
                raise ValueError("Invalid key mapping")
            keys = {name: base64.b64decode(value, validate=True) for name, value in values.items()}
            if any(
                not isinstance(name, str) or not 1 <= len(name) <= 64 or len(value) != 32
                for name, value in keys.items()
            ):
                raise ValueError("Invalid audit key")
        except (ValueError, TypeError):
            # Do not put secret material into a parser exception or log record.
            raise ValueError("Audit encryption key configuration invalid") from None
        return cls(keys, active_id=active_id)
