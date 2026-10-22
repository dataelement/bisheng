"""Bounded, namespace-only Kubernetes REST access with conditional writes.

No exec, port-forward, cluster-scoped endpoint, or arbitrary URL is exposed.
A successful DELETE is a request acknowledgement, never a stop observation.
"""

from __future__ import annotations

import copy
import json
import re
import ssl
import time
from collections.abc import Callable, Iterator

import httpx

from runtime_manager.k8s_config import KubernetesConfig

_CORE = {"pods", "services", "persistentvolumeclaims", "secrets", "events", "endpoints"}
_DISCOVERY = {"endpointslices"}
_READ_ONLY = {"events", "endpoints", "endpointslices"}
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_TRANSIENT = {429, 500, 502, 503, 504}


class KubernetesAPIError(RuntimeError):
    """Safe classification; never includes API response or transport details."""

    def __init__(self, reason: str, status_code: int | None = None):
        super().__init__(reason)
        self.status_code = status_code


def _name(value: str) -> str:
    if not isinstance(value, str) or len(value) > 253 or not all(_LABEL.fullmatch(x) for x in value.split(".")):
        raise ValueError("k8s_name_invalid")
    return value


def _version(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or not value.isascii() or not value.isalnum():
        raise ValueError("k8s_resource_version_required")
    if value == "0":
        raise ValueError("k8s_fresh_resource_version_required")
    return value


class KubernetesClient:
    def __init__(
        self,
        config: KubernetesConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        checkpoint: Callable[[], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.checkpoint = checkpoint or (lambda: None)
        self.sleep = sleep
        self._http = httpx.Client(
            base_url=config.api_server.rstrip("/"),
            verify=ssl.create_default_context(cafile=str(config.ca_file)),
            timeout=config.request_timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _path(self, resource: str, name: str | None = None, *, write: bool = False) -> str:
        if resource in _CORE:
            root = "/api/v1"
        elif resource in _DISCOVERY:
            root = "/apis/discovery.k8s.io/v1"
        else:
            raise ValueError("k8s_resource_refused")
        if write and resource in _READ_ONLY:
            raise ValueError("k8s_resource_read_only")
        result = f"{root}/namespaces/{self.config.namespace}/{resource}"
        return result if name is None else f"{result}/{_name(name)}"

    def _request(self, method: str, path: str, *, params=None, body=None, merge_patch=False) -> httpx.Response:
        # Retrying ambiguous mutations can duplicate actions; reconcile by UID/name instead.
        attempts = self.config.retry_attempts if method == "GET" else 1
        deadline = time.monotonic() + self.config.request_timeout
        for attempt in range(attempts):
            self.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KubernetesAPIError("request_deadline_exceeded")
            headers = {"Authorization": f"Bearer {self.config.read_token()}", "Accept": "application/json"}
            if merge_patch:
                headers["Content-Type"] = "application/merge-patch+json"
            try:
                response = self._http.request(
                    method, path, params=params, json=body, headers=headers, timeout=remaining
                )
            except httpx.TransportError:
                if attempt + 1 == attempts:
                    raise KubernetesAPIError("transport_unavailable") from None
            else:
                if 200 <= response.status_code < 300:
                    self.checkpoint()
                    return response
                if response.status_code not in _TRANSIENT or attempt + 1 == attempts:
                    raise KubernetesAPIError("k8s_api_refused", response.status_code)
            self.checkpoint()
            delay = min(0.1 * 2**attempt, max(0, deadline - time.monotonic()))
            self.sleep(delay)
        raise KubernetesAPIError("transport_unavailable")

    @staticmethod
    def _object(response: httpx.Response) -> dict:
        try:
            obj = response.json()
        except (ValueError, UnicodeError):
            raise KubernetesAPIError("k8s_response_invalid") from None
        if not isinstance(obj, dict):
            raise KubernetesAPIError("k8s_response_invalid")
        return obj

    def get(self, resource: str, name: str) -> dict:
        return self._object(self._request("GET", self._path(resource, name)))

    def _scoped_body(self, payload: dict, name: str | None = None) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("k8s_body_invalid")
        body = copy.deepcopy(payload)
        meta = body.setdefault("metadata", {})
        if not isinstance(meta, dict):
            raise ValueError("k8s_metadata_invalid")
        if meta.get("namespace", self.config.namespace) != self.config.namespace:
            raise ValueError("k8s_scope_mismatch")
        if name is None:
            _name(meta.get("name", ""))
        elif meta.get("name", name) != name:
            raise ValueError("k8s_name_mismatch")
        if "generateName" in meta:
            raise ValueError("k8s_fixed_name_required")
        meta["namespace"] = self.config.namespace
        return body

    def create(self, resource: str, payload: dict) -> dict:
        path = self._path(resource, write=True)
        body = self._scoped_body(payload)
        return self._object(self._request("POST", path, body=body))

    def patch(self, resource: str, name: str, payload: dict, *, resource_version: str) -> dict:
        path = self._path(resource, name, write=True)
        body = self._scoped_body(payload, name)
        body["metadata"]["resourceVersion"] = _version(resource_version)
        return self._object(self._request("PATCH", path, body=body, merge_patch=True))

    def delete(self, resource: str, name: str, *, uid: str, resource_version: str, grace_seconds: int = 30) -> dict:
        path = self._path(resource, name, write=True)
        if not isinstance(uid, str) or not uid or len(uid) > 128 or not re.fullmatch(r"[a-zA-Z0-9-]+", uid):
            raise ValueError("k8s_uid_required")
        if type(grace_seconds) is not int or not 1 <= grace_seconds <= 120:
            raise ValueError("k8s_delete_grace_invalid")
        body = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {"uid": uid, "resourceVersion": _version(resource_version)},
            "gracePeriodSeconds": grace_seconds,
        }
        return self._object(self._request("DELETE", path, body=body))

    def list(self, resource: str, *, label_selector: str = "") -> dict:
        path = self._path(resource)
        params = {"limit": str(self.config.page_size)}
        if label_selector:
            params["labelSelector"] = label_selector
        items, version, seen = [], None, set()
        for _ in range(10000):
            page = self._object(self._request("GET", path, params=params))
            meta = page.get("metadata", {})
            rows = page.get("items")
            if not isinstance(meta, dict) or not isinstance(rows, list) or not meta.get("resourceVersion"):
                raise KubernetesAPIError("k8s_list_invalid")
            if version is not None and version != meta["resourceVersion"]:
                raise KubernetesAPIError("list_snapshot_changed")
            version = meta["resourceVersion"]
            items.extend(rows)
            continuation = meta.get("continue", "")
            if not continuation:
                return {"metadata": {"resourceVersion": version}, "items": items}
            if not isinstance(continuation, str) or continuation in seen:
                raise KubernetesAPIError("k8s_list_continuation_invalid")
            seen.add(continuation)
            params["continue"] = continuation
        raise KubernetesAPIError("k8s_list_page_limit")

    def watch(self, resource: str, *, resource_version: str, label_selector: str = "") -> Iterator[dict]:
        path = self._path(resource)
        version = _version(resource_version)
        # Finite windows only wake reconciliation. They never establish stop evidence.
        for _ in range(self.config.retry_attempts):
            params = {
                "watch": "true",
                "resourceVersion": version,
                "timeoutSeconds": str(max(1, int(self.config.request_timeout) - 1)),
                "allowWatchBookmarks": "true",
            }
            if label_selector:
                params["labelSelector"] = label_selector
            expired = False
            try:
                response = self._request("GET", path, params=params)
            except KubernetesAPIError as exc:
                if exc.status_code != 410:
                    raise
                expired = True
            else:
                for line in response.iter_lines():
                    self.checkpoint()
                    if not line:
                        continue
                    if len(line) > 4 * 1024 * 1024:
                        raise KubernetesAPIError("k8s_watch_event_too_large")
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise KubernetesAPIError("k8s_watch_invalid") from None
                    if not isinstance(event, dict) or not isinstance(event.get("object"), dict):
                        raise KubernetesAPIError("k8s_watch_invalid")
                    if event.get("type") == "ERROR":
                        if event["object"].get("code") == 410:
                            expired = True
                            break
                        raise KubernetesAPIError("k8s_watch_error")
                    if event.get("type") not in {"ADDED", "MODIFIED", "DELETED", "BOOKMARK"}:
                        raise KubernetesAPIError("k8s_watch_invalid")
                    yield event
                if not expired:
                    return
            snapshot = self.list(resource, label_selector=label_selector)
            version = _version(snapshot["metadata"]["resourceVersion"])
            yield {"type": "RESET", "object": snapshot}
        raise KubernetesAPIError("k8s_watch_relist_limit")

    def logs(
        self,
        pod_name: str,
        *,
        tail: int = 100,
        previous: bool = False,
        since_seconds: int | None = None,
        container: str = "app",
    ) -> str:
        if container not in {
            "app",
            "transfer",
            "prepare",
            "material-fetch",
            "environment",
            "data-layout",
            "data-helper",
            "maintenance",
        }:
            raise ValueError("k8s_log_container_invalid")
        path = self._path("pods", pod_name) + "/log"
        if type(tail) is not int or not 1 <= tail <= 1000:
            raise ValueError("k8s_log_tail_invalid")
        params = {
            "container": container,
            "tailLines": str(tail),
            "previous": str(bool(previous)).lower(),
            "limitBytes": "1048576",
        }
        if since_seconds is not None:
            if type(since_seconds) is not int or not 1 <= since_seconds <= 86400:
                raise ValueError("k8s_log_since_invalid")
            params["sinceSeconds"] = str(since_seconds)
        return self._request("GET", path, params=params).text[:1048576]
