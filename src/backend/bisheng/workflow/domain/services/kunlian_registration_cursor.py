import base64
import binascii
import hmac
import json
import time
from dataclasses import asdict

from bisheng.common.errcode.flow import WorkflowRegistrationCursorExpired


class RegistrationCursor:
    def __init__(self, key: bytes, *, clock=time.time):
        if len(key) < 32:
            raise ValueError("cursor signing key is too short")
        self.key = key
        self.clock = clock

    @staticmethod
    def _encode(raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def issue(self, scope, kind, *, expires_at=None, **values):
        # TODO [F121][EXT-05] 正式保留时限由双方合同确定。
        if expires_at is None:
            expires_at = int(self.clock()) + (86400 if kind == "checkpoint" else 300)
        raw = json.dumps([1, asdict(scope), kind, expires_at, values], separators=(",", ":")).encode()
        body = self._encode(raw)
        signature = self._encode(hmac.digest(self.key, body.encode(), "sha256"))
        return f"{body}.{signature}"

    def read(self, scope, kind, token):
        try:
            if len(token) > 4096:
                raise ValueError
            body, signature = token.split(".", 1)
            expected = self._encode(hmac.digest(self.key, body.encode(), "sha256"))
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            version, actual_scope, actual_kind, expires, values = json.loads(
                base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            )
            if version != 1 or actual_scope != asdict(scope) or actual_kind != kind or expires <= self.clock():
                raise ValueError
            return {**values, "expires_at": expires}
        except (TypeError, ValueError, binascii.Error):
            raise WorkflowRegistrationCursorExpired() from None
