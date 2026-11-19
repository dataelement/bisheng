"""Provider reachability/credential probes used by the admin settings form.

Deliberately separate from any single provider's client: the settings endpoints
exercise PaddleOCR, MinerU and MinerU V4, and a probe module named after one of
them misleads the next reader.

A probe never does real work — it answers only "is it reachable, and does it
accept my credential".
"""

from __future__ import annotations

import time

import httpx

#: The admin form's connection test must not hang; it is a UI action.
PROBE_TIMEOUT_SECONDS = 15


def is_http_url(url: str) -> bool:
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, ValueError):
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.host)



def probe_endpoint(
    url: str,
    token: str = "",
    transport: httpx.BaseTransport | None = None,
    token_header: str = "Authorization",
    token_prefix: str = "Bearer ",
) -> dict:
    """Reachability/auth check for a provider with no harmless probe payload.

    Any HTTP answer proves the endpoint is up; 401/403 means the credential was
    rejected. Used by the admin form for ETL4LM / MinerU / MinerU V4, which have
    no cheap "validate without doing work" request.
    """
    started = time.monotonic()

    def result(status: str, message: str) -> dict:
        return {"status": status, "message": message, "latency_ms": int((time.monotonic() - started) * 1000)}

    if not is_http_url(url or ""):
        return result("misconfigured", "The service URL is empty or not a valid http(s) URL")
    headers = {token_header: f"{token_prefix}{token}"} if token else {}
    try:
        with httpx.Client(transport=transport, timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return result("unreachable", f"Cannot reach {url}: {exc}")
    if response.status_code in (401, 403):
        return result("token_invalid", f"HTTP {response.status_code}: the credential was rejected")
    if response.status_code >= 500:
        # Up but broken; reporting this as a healthy connection would mislead.
        return result("error", f"The service answered HTTP {response.status_code}")
    return result("ok", f"Reachable (HTTP {response.status_code})")

def probe_mineru_v4(api_url: str, key: str = "", transport: httpx.BaseTransport | None = None) -> dict:
    """Probe MinerU V4 for the two shapes it is deployed in.

    - The hosted cloud API answers on ``/api/v4/extract/task``: a POST with an
      empty body is rejected for a missing field (-10002) *after* the key is
      checked, so that answer proves the credential; 401 means it was rejected.
    - A self-hosted deployment uses a base root plus the ``/v1/...`` job paths
      this codebase speaks; there a plain GET on the root proves nothing (405),
      so the probe asks for ``/v1/uploads`` instead: 404 means the URL is not
      that shape.

    A 405-only answer is reported as ``unreachable``-adjacent rather than green,
    because it proves neither the credential nor that the URL is usable.
    """
    started = time.monotonic()

    def result(status: str, message: str) -> dict:
        return {"status": status, "message": message, "latency_ms": int((time.monotonic() - started) * 1000)}

    if not is_http_url(api_url or ""):
        return result("misconfigured", "The API URL is empty or not a valid http(s) URL")
    url = api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    is_cloud_task_api = url.endswith("/extract/task")
    is_upload_api = url.endswith("/agent/parse/file")

    try:
        with httpx.Client(transport=transport, timeout=PROBE_TIMEOUT_SECONDS) as client:
            if is_cloud_task_api:
                response = client.post(url, headers=headers, json={})
            elif is_upload_api:
                # A GET on a made-up task id costs nothing and still answers
                # through the same auth layer.
                response = client.get(url[: -len("/file")] + "/00000000-0000", headers=headers)
            else:
                response = client.get(f"{url}/v1/uploads", headers=headers)
    except httpx.HTTPError as exc:
        return result("unreachable", f"Cannot reach {url}: {exc}")

    payload: dict = {}
    try:
        payload = response.json() or {}
    except ValueError:
        payload = {}
    code = payload.get("code")

    if response.status_code in (401, 403) or code in (401, 403):
        return result("token_invalid", "The service rejected the API key")
    if response.status_code == 404:
        return result(
            "misconfigured",
            "This URL is not a MinerU V4 API the parser can use: the /v1 job paths answer 404. "
            "Use a self-hosted deployment root, https://mineru.net/api/v1/agent/parse/file "
            "(upload mode), or https://mineru.net/api/v4/extract/task (public-URL mode).",
        )
    if is_upload_api:
        return result("ok", "The API key was accepted; documents are pushed to the hosted API, "
                            "so no public file URL is needed")
    if is_cloud_task_api:
        # The key is accepted, which is all this probe can verify: the hosted API
        # fetches documents itself, so whether a parse will succeed depends on the
        # MinIO share host being publicly reachable — checked at parse time.
        detail = f" (service answered code {code})" if isinstance(code, int) and code != 0 else ""
        return result(
            "ok",
            "The API key was accepted; the hosted mineru.net API will fetch documents "
            "through object_storage.minio.sharepoint, which must be publicly reachable"
            + detail,
        )
    if response.status_code < 500:
        return result("ok", f"Reachable (HTTP {response.status_code})")
    return result("error", f"Unexpected answer (HTTP {response.status_code})")
