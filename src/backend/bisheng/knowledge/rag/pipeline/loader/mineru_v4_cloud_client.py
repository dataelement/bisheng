"""Client for MinerU's hosted (mineru.net) V4 parse API.

This is a **separate** transport from ``MineruV4Client``: the hosted API takes a
public file URL and hands back a zip, where a self-hosted deployment takes a
byte upload and speaks the ``/v1`` job protocol. The loader picks one by URL
shape, so neither deployment style can break the other.

Contract verified against the live service on 2026-11-13:

- ``POST {root}/extract/task`` ``{"url": <public file URL>}`` → ``data.task_id``.
  The URL must be publicly reachable: ``localhost`` is rejected with -10002
  "not a valid URL", and an unreachable host gives -60023. Uploading to the
  presigned OSS URLs from ``/file-urls/batch`` is *not* usable — the object stays
  private and the parser reports "failed to read file".
- ``GET {root}/extract/task/{task_id}`` → ``data.state`` ``pending``/``running``
  → ``done`` (with ``full_zip_url``) or ``failed`` (with ``err_msg``).
- The zip contains ``full.md``, ``*_content_list.json`` and ``layout.json`` —
  not the self-hosted ``middle_json.json``, so it has its own reader.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from loguru import logger

from bisheng.core.config.settings import MineruV4Conf
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_client import MineruV4Client, MineruV4Error

#: ``data.state`` values that end the poll.
_DONE_STATES = {"done", "completed", "success"}
_FAILED_STATES = {"failed", "error", "canceled", "cancelled"}

#: Business codes the service returns with HTTP 200. Only the ones we have seen
#: are named; anything else is surfaced verbatim.
_CODE_HINTS = {
    -10002: "the request was rejected (invalid or non-public file URL)",
    -60012: "the task was not found or has expired",
    -60023: "the service cannot reach that URL (regional restriction or private host)",
}


class MineruV4CloudError(MineruV4Error):
    """The hosted MinerU V4 API cannot be submitted, completed, or downloaded."""


class _HostedClient:
    """Shared plumbing for the two hosted MinerU V4 shapes.

    Only the endpoints and the result format differ between them, so the
    transport, credential and envelope handling live here.
    """

    def __init__(self, config: MineruV4Conf, root: str, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.root = root
        self.api_key = MineruV4Client._resolve_api_key(config)
        self.transport = transport

    def _headers(self, url: str) -> dict[str, str]:
        """The key goes to the MinerU API only — never to the result CDN."""
        if not url.startswith(self.root):
            return {}
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.config.request_timeout_seconds, connect=self.config.connect_timeout_seconds)



    @staticmethod
    def _payload(response: httpx.Response, phase: str) -> dict:
        try:
            data = response.json()
        except ValueError as exc:
            raise MineruV4CloudError(f"MinerU V4 cloud {phase} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise MineruV4CloudError(f"MinerU V4 cloud {phase} returned an unexpected structure")
        code = data.get("code", 0)
        if code not in (0, None):
            hint = _CODE_HINTS.get(code, "")
            raise MineruV4CloudError(
                f"MinerU V4 cloud {phase} failed (code {code}): {data.get('msg', '')}" + (f" — {hint}" if hint else "")
            )
        body = data.get("data")
        if not isinstance(body, dict):
            raise MineruV4CloudError(f"MinerU V4 cloud {phase} response has no data")
        return body

class MineruV4CloudClient(_HostedClient):
    """Submits a public file URL and returns the downloaded zip's local path."""

    MAX_ZIP_BYTES = 512 * 1024 * 1024

    def __init__(self, config: MineruV4Conf, transport: httpx.BaseTransport | None = None):
        task_url = config.api_url.rstrip("/")
        if not task_url.endswith("/extract/task"):
            raise MineruV4CloudError(
                f"The hosted MinerU V4 endpoint must end with /api/v4/extract/task (got {config.api_url!r})"
            )
        self.task_url = task_url
        super().__init__(config, task_url[: -len("/extract/task")], transport)

    # -- requests ---------------------------------------------------------------------

    def _submit(self, client: httpx.Client, file_url: str) -> str:
        payload = {"url": file_url, **self.config.request_kwargs}
        if self.config.cloud_model_version:
            payload.setdefault("model_version", self.config.cloud_model_version)
        response = client.post(self.task_url, headers=self._headers(self.task_url), json=payload)
        if response.is_error:
            raise MineruV4CloudError(f"MinerU V4 cloud submit returned HTTP {response.status_code}")
        task_id = self._payload(response, "submit").get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise MineruV4CloudError("MinerU V4 cloud submit returned no task_id")
        return task_id

    def _wait(self, client: httpx.Client, task_id: str, deadline: float) -> str:
        url = f"{self.task_url}/{task_id}"
        while True:
            if time.monotonic() >= deadline:
                raise MineruV4CloudError("MinerU V4 cloud parse job timed out")
            response = client.get(url, headers=self._headers(url))
            if response.is_error:
                raise MineruV4CloudError(f"MinerU V4 cloud status returned HTTP {response.status_code}")
            body = self._payload(response, "status")
            state = str(body.get("state", "")).lower()
            if state in _FAILED_STATES:
                raise MineruV4CloudError(f"MinerU V4 cloud parse failed: {body.get('err_msg') or 'no reason given'}")
            if state in _DONE_STATES:
                zip_url = body.get("full_zip_url")
                if not isinstance(zip_url, str) or not zip_url:
                    raise MineruV4CloudError("MinerU V4 cloud job finished without a result URL")
                resolved = urljoin(self.task_url, zip_url)
                if not resolved.startswith(("http://", "https://")):
                    raise MineruV4CloudError("MinerU V4 cloud returned an unusable result URL")
                return resolved
            time.sleep(min(self.config.poll_interval_seconds, max(deadline - time.monotonic(), 0)))

    def _download(self, client: httpx.Client, zip_url: str, tmp_dir: str) -> str:
        target = Path(tmp_dir) / "mineru-v4-cloud-result.zip"
        written = 0
        with client.stream("GET", zip_url, headers=self._headers(zip_url)) as response:
            if response.is_error:
                raise MineruV4CloudError(f"MinerU V4 cloud result download returned HTTP {response.status_code}")
            with target.open("wb") as output:
                for chunk in response.iter_bytes():
                    written += len(chunk)
                    if written > self.MAX_ZIP_BYTES:
                        target.unlink(missing_ok=True)
                        raise MineruV4CloudError("MinerU V4 cloud ZIP exceeds size limit")
                    output.write(chunk)
        if not written:
            target.unlink(missing_ok=True)
            raise MineruV4CloudError("MinerU V4 cloud ZIP is empty")
        return str(target)

    def parse(self, file_url: str, tmp_dir: str) -> str:
        """Submit ``file_url``, wait for the result and return the local zip path."""
        deadline = time.monotonic() + self.config.job_timeout_seconds
        try:
            with httpx.Client(transport=self.transport, timeout=self._timeout()) as client:
                task_id = self._submit(client, file_url)
                logger.info("mineru_v4 cloud: created task {}", task_id)
                zip_url = self._wait(client, task_id, deadline)
                return self._download(client, zip_url, tmp_dir)
        except httpx.HTTPError as exc:
            raise MineruV4CloudError(f"MinerU V4 cloud transport failed: {exc}") from exc


class MineruV4UploadClient(_HostedClient):
    """Upload-mode client: the document is pushed to MinerU, no public URL needed.

    Contract verified against the live service on 2026-11-14:

    - ``POST {root}/file`` ``{"file_name": "x.pdf"}`` → ``data.task_id`` and a
      presigned ``data.file_url``; state starts at ``waiting-file``.
    - ``PUT`` the raw bytes to ``file_url`` **without a Content-Type header**
      (adding one breaks the OSS signature) → state moves to ``running``.
    - ``GET {root}/{task_id}`` → ``done`` with ``data.markdown_url``.

    The result is markdown only: this endpoint returns no zip, hence no bbox
    metadata. Citation highlighting therefore has no coordinates on this path.
    """

    def __init__(self, config: MineruV4Conf, transport: httpx.BaseTransport | None = None):
        upload_url = config.api_url.rstrip("/")
        if not upload_url.endswith("/agent/parse/file"):
            raise MineruV4CloudError(
                "The upload-mode endpoint must end with /api/v1/agent/parse/file "
                f"(got {config.api_url!r})"
            )
        super().__init__(config, upload_url[: -len("/file")], transport)

    def parse_uploaded(self, file_path: str, filename: str) -> str:
        """Push the file and return the parsed markdown."""
        deadline = time.monotonic() + self.config.job_timeout_seconds
        try:
            with httpx.Client(transport=self.transport, timeout=self._timeout()) as client:
                created = client.post(
                    f"{self.root}/file", headers=self._headers(f"{self.root}/file"), json={"file_name": filename}
                )
                if created.is_error:
                    raise MineruV4CloudError(f"MinerU V4 upload register returned HTTP {created.status_code}")
                body = self._payload(created, "upload register")
                task_id = body.get("task_id")
                file_url = body.get("file_url")
                if not isinstance(task_id, str) or not task_id or not isinstance(file_url, str) or not file_url:
                    raise MineruV4CloudError("MinerU V4 upload register returned no task_id/file_url")

                with open(file_path, "rb") as source:
                    # No Content-Type on purpose: it is part of the OSS signature.
                    put = client.put(file_url, content=source.read())
                if put.is_error:
                    raise MineruV4CloudError(f"MinerU V4 file upload returned HTTP {put.status_code}")

                markdown_url = self._wait_markdown(client, task_id, deadline)
                markdown = client.get(markdown_url, headers=self._headers(markdown_url))
                if markdown.is_error:
                    raise MineruV4CloudError(f"MinerU V4 markdown download returned HTTP {markdown.status_code}")
                return markdown.text
        except httpx.HTTPError as exc:
            raise MineruV4CloudError(f"MinerU V4 upload transport failed: {exc}") from exc

    def _wait_markdown(self, client: httpx.Client, task_id: str, deadline: float) -> str:
        url = f"{self.root}/{task_id}"
        while True:
            if time.monotonic() >= deadline:
                raise MineruV4CloudError("MinerU V4 upload parse job timed out")
            response = client.get(url, headers=self._headers(url))
            if response.is_error:
                raise MineruV4CloudError(f"MinerU V4 upload status returned HTTP {response.status_code}")
            body = self._payload(response, "status")
            state = str(body.get("state", "")).lower()
            if state in _FAILED_STATES:
                raise MineruV4CloudError(f"MinerU V4 upload parse failed: {body.get('err_msg') or 'no reason given'}")
            if state in _DONE_STATES:
                markdown_url = body.get("markdown_url")
                if not isinstance(markdown_url, str) or not markdown_url:
                    raise MineruV4CloudError("MinerU V4 upload job finished without a markdown URL")
                return markdown_url
            time.sleep(min(self.config.poll_interval_seconds, max(deadline - time.monotonic(), 0)))
