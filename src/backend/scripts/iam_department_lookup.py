"""Read-only IAM lookup matching Gateway cofco authentication and DTO fields."""

import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from bisheng.permission.domain.services.department_recovery_plan import (
    RecoveryBlockedError,
    RecoveryRuntimeError,
    checksum,
)


class IamLookupError(RecoveryBlockedError):
    """Safe diagnostics only: never include headers, credentials or raw responses."""


class IamDepartmentNotFound(IamLookupError):
    """Exact, reviewed upstream not-found contract; other errors never mean deletion."""

    def __init__(self, external_id):
        super().__init__("IAM_DEPARTMENT_CONFIRMED_NOT_FOUND")
        self.evidence = {"id": external_id, "http_status": 200, "errcode": "1", "errmsg": "部门不存在\uff01"}


class IamDepartmentLookup:
    max_response_bytes = 16 * 1024 * 1024
    max_requests = 2000  # bounded current scan candidates and their direct parents

    def __init__(self, configuration, *, transport=None, clock=time.time):
        self.base_url = str(configuration.get("base_url", "")).rstrip("/")
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise IamLookupError("IAM_CONFIG_BASE_URL_INVALID")
        timeout = configuration.get("timeout_seconds", 15)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 60
        ):
            raise IamLookupError("IAM_CONFIG_TIMEOUT_INVALID")
        self.local_source = configuration.get("bisheng_source")
        if not isinstance(self.local_source, str) or not self.local_source.strip():
            raise IamLookupError("IAM_CONFIG_BISHENG_SOURCE_REQUIRED")
        qps = configuration.get("max_qps", 2)
        if isinstance(qps, bool) or not isinstance(qps, (int, float)) or not math.isfinite(qps) or not 0 < qps <= 5:
            raise IamLookupError("IAM_CONFIG_QPS_INVALID")
        self.interval, self._last_request = 1 / qps, None
        request_limit = configuration.get("max_requests", 2000)
        if isinstance(request_limit, bool) or not isinstance(request_limit, int) or not 1 <= request_limit <= 200000:
            raise IamLookupError("IAM_CONFIG_REQUEST_LIMIT_INVALID")
        self.max_requests = request_limit
        self.app_id = os.environ.get(configuration.get("app_id_env", "BS_DEPARTMENT_IAM_APP_ID"), "")
        self._secret = os.environ.get(configuration.get("app_secret_env", "BS_DEPARTMENT_IAM_APP_SECRET"), "")
        if not self.app_id or not self._secret:
            raise IamLookupError("IAM_CREDENTIAL_ENV_MISSING")
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.clock, self.calls, self.cache = clock, 0, {}
        self._lock = asyncio.Lock()
        self.source_fingerprint = checksum(
            {"base_url": self.base_url, "app_id": self.app_id, "bisheng_source": self.local_source}
        )

    @classmethod
    def from_file(cls, path):
        try:
            configuration = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise IamLookupError("IAM_CONFIG_UNREADABLE") from exc
        if not isinstance(configuration, dict) or set(configuration) - {
            "base_url",
            "app_id_env",
            "app_secret_env",
            "timeout_seconds",
            "bisheng_source",
            "max_qps",
            "max_requests",
        }:
            raise IamLookupError("IAM_CONFIG_UNKNOWN_FIELDS")
        if any(not isinstance(configuration.get(key, "default"), str) for key in ("app_id_env", "app_secret_env")):
            raise IamLookupError("IAM_CONFIG_ENV_NAME_INVALID")
        return cls(configuration)

    async def department(self, external_id):
        async with self._lock:
            return await self._department(external_id)

    async def refresh_department(self, external_id):
        async with self._lock:
            self.cache.pop(external_id, None)
            return await self._department(external_id)

    def cached_department(self, external_id):
        if external_id not in self.cache:
            raise IamLookupError("IAM_FACTS_NOT_PREFETCHED_BEFORE_LOCK")
        value = self.cache[external_id]
        if isinstance(value, IamLookupError):
            raise value
        return dict(value)

    async def _department(self, external_id):
        if (
            not isinstance(external_id, str)
            or not external_id.isascii()
            or not external_id.isdecimal()
            or int(external_id) <= 0
        ):
            raise IamLookupError("IAM_EXTERNAL_ID_INVALID_OR_ROOT")
        if external_id in self.cache:
            value = self.cache[external_id]
            if isinstance(value, IamLookupError):
                raise value
            return dict(value)
        try:
            value = await self._read(external_id)
        except IamLookupError as exc:
            self.cache[external_id] = exc
            raise
        self.cache[external_id] = value
        return dict(value)

    async def _read(self, external_id):
        if self.calls >= self.max_requests:
            raise RecoveryRuntimeError("IAM_SCAN_INCOMPLETE_REQUEST_LIMIT")
        self.calls += 1
        now = time.monotonic()
        if self._last_request is not None:
            await asyncio.sleep(max(0, self.interval - (now - self._last_request)))
        self._last_request = time.monotonic()
        timestamp = str(int(self.clock()))
        token = hashlib.sha256((self.app_id + self._secret + timestamp).encode()).hexdigest()
        headers = {
            "X-App-Id": self.app_id,
            "X-App-Token": token,
            "X-Timestamp": timestamp,
            "Content-Type": "application/json",
        }
        try:
            async with self.client.stream(
                "GET",
                self.base_url + "/openapi_v2/qywx_department/list",
                params={"department_id": external_id},
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    if response.status_code in {401, 403} or response.status_code >= 500:
                        raise RecoveryRuntimeError(f"IAM_SERVICE_NOT_READY_HTTP_{response.status_code}")
                    raise IamLookupError(f"IAM_HTTP_STATUS_{response.status_code}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > self.max_response_bytes:
                        raise IamLookupError("IAM_RESPONSE_TOO_LARGE")
            payload = json.loads(data)
        except httpx.HTTPError as exc:
            raise RecoveryRuntimeError("IAM_SERVICE_READ_FAILED_SCAN_INCOMPLETE") from exc
        except (ValueError, UnicodeError) as exc:
            raise IamLookupError("IAM_READ_OR_JSON_FAILED") from exc
        if (
            isinstance(payload, dict)
            and str(payload.get("errcode")) == "1"
            and payload.get("errmsg") == "部门不存在\uff01"
        ):
            raise IamDepartmentNotFound(external_id)
        if not isinstance(payload, dict) or ("errcode" in payload and str(payload["errcode"]) != "0"):
            raise IamLookupError("IAM_BUSINESS_RESPONSE_NOT_SUCCESS")
        rows = payload.get("department")
        if not isinstance(rows, list):
            raise IamLookupError("IAM_DEPARTMENT_ARRAY_MISSING")
        matches = [row for row in rows if isinstance(row, dict) and str(row.get("id")) == external_id]
        if len(matches) != 1:
            raise IamLookupError("IAM_EXACT_ID_MISSING_OR_DUPLICATE")
        row = matches[0]
        parent = row.get("parentid")
        if (
            isinstance(parent, bool)
            or not isinstance(parent, (str, int))
            or not str(parent).isascii()
            or not str(parent).isdecimal()
        ):
            raise IamLookupError("IAM_PARENT_ID_INVALID")
        enabled = row.get("enable")
        if isinstance(enabled, bool) or enabled not in (0, 1, "0", "1"):
            raise IamLookupError("IAM_ENABLE_MISSING_OR_INVALID")
        # Ignore any returned descendants and personal/unrelated source fields.
        return {"id": external_id, "parentid": str(parent), "enable": int(enabled)}

    async def close(self):
        await self.client.aclose()
