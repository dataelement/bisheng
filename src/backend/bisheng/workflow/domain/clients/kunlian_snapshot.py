"""昆联工作流资料同步 HTTP 回调客户端（HMAC-SHA256 签名，禁止 3xx 跳转）。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

MAX_BODY_BYTES = 524288  # 512KiB
MAX_RECEIPT_BYTES = 4096

ENV_CALLBACK_URL = "KUNLIAN_SNAPSHOT_CALLBACK_URL"
ENV_KEY_ID = "KUNLIAN_CALLBACK_KEY_ID"
ENV_SECRET_HEX = "KUNLIAN_CALLBACK_SECRET_HEX"


@dataclass(frozen=True)
class SnapshotCallbackConfig:
    """昆联资料同步回调配置（来自服务端环境变量）。"""

    url: str
    key_id: str
    secret_hex: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> SnapshotCallbackConfig | None:
        source = os.environ if env is None else env
        url = (source.get(ENV_CALLBACK_URL) or "").strip()
        key_id = (source.get(ENV_KEY_ID) or "").strip()
        secret_hex = (source.get(ENV_SECRET_HEX) or "").strip()
        if not (url and key_id and secret_hex):
            return None
        return cls(url=url, key_id=key_id, secret_hex=secret_hex)

    def secret_bytes(self) -> bytes:
        try:
            secret = bytes.fromhex(self.secret_hex)
        except ValueError as exc:
            raise ValueError("Invalid signing key hex") from exc
        if len(secret) != 32:
            raise ValueError("Invalid signing key length")
        return secret


@dataclass(frozen=True)
class SnapshotDeliveryResult:
    """单次回调投递结果分类（delivered / retry / failed）。"""

    outcome: str
    status_code: int | None = None
    request_id: str | None = None
    error: str | None = None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁用 3xx 自动跳转，按接入规范将 3xx 作为错误返回。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sign_snapshot_payload(secret: bytes, timestamp: str, body_bytes: bytes) -> str:
    """生成 X-Workflow-Signature（64 位小写十六进制 HMAC-SHA256）。"""
    if len(secret) != 32:
        raise ValueError("Invalid signing key length")
    return hmac.new(secret, timestamp.encode("ascii") + b"." + body_bytes, hashlib.sha256).hexdigest()


class KunlianSnapshotCallbackClient:
    """仅依赖 Python 标准库发送工作流资料同步事件，并校验 202 回执。"""

    def __init__(
        self,
        config: SnapshotCallbackConfig,
        *,
        timeout_seconds: float = 10.0,
        clock=None,
        opener=None,
    ):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._clock = clock or time.time
        self._opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def send(self, *, event_id: str, payload_json: str) -> SnapshotDeliveryResult:
        body = payload_json.encode("utf-8")
        if len(body) > MAX_BODY_BYTES:
            return SnapshotDeliveryResult(outcome="failed", error="snapshot_exceeds_512kib")

        try:
            secret = self.config.secret_bytes()
        except ValueError:
            return SnapshotDeliveryResult(outcome="failed", error="invalid_signing_key")

        stamp = str(int(self._clock()))
        signature = sign_snapshot_payload(secret, stamp, body)
        request = urllib.request.Request(
            self.config.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Workflow-Key-Id": self.config.key_id,
                "X-Workflow-Timestamp": stamp,
                "X-Workflow-Signature": signature,
                "X-Request-ID": event_id,
            },
        )

        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                request_id = self._extract_request_id(getattr(response, "headers", None))
                raw_receipt = response.read(MAX_RECEIPT_BYTES)
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            request_id = self._extract_request_id(getattr(exc, "headers", None))
            if status_code == 429 or 500 <= status_code <= 599:
                return SnapshotDeliveryResult(
                    outcome="retry",
                    status_code=status_code,
                    request_id=request_id,
                    error=f"http_{status_code}",
                )
            return SnapshotDeliveryResult(
                outcome="failed",
                status_code=status_code,
                request_id=request_id,
                error=f"http_{status_code}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return SnapshotDeliveryResult(
                outcome="retry",
                error=f"network_error:{type(exc).__name__}",
            )

        if status_code != 202:
            outcome = "retry" if (status_code == 429 or 500 <= status_code <= 599) else "failed"
            return SnapshotDeliveryResult(
                outcome=outcome,
                status_code=status_code,
                request_id=request_id,
                error=f"unexpected_status_{status_code}",
            )

        try:
            receipt = json.loads(raw_receipt.decode("utf-8"))
        except Exception:
            return SnapshotDeliveryResult(
                outcome="retry",
                status_code=status_code,
                request_id=request_id,
                error="invalid_receipt_json",
            )

        if (
            not isinstance(receipt, dict)
            or receipt.get("event_id") != event_id
            or receipt.get("status") != "ACCEPTED"
        ):
            return SnapshotDeliveryResult(
                outcome="retry",
                status_code=status_code,
                request_id=request_id,
                error="unexpected_receipt_payload",
            )

        return SnapshotDeliveryResult(
            outcome="delivered",
            status_code=status_code,
            request_id=request_id,
        )

    @staticmethod
    def _extract_request_id(headers) -> str | None:
        if headers is None:
            return None
        try:
            value = headers.get("X-Request-ID")
        except Exception:
            return None
        return str(value).strip() if value else None
