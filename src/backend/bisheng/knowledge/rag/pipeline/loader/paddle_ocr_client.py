"""Client for PaddleOCR's hosted jobs API.

The AIStudio-hosted ``/api/v2/ocr/jobs`` service is a three-step job API, unlike
the self-hosted PP-StructureV3 ``/layout-parsing`` service that
``PaddleOcrLoader`` calls directly. This contract was verified against the live
service on 2026-11-12:

1. ``POST {jobs_url}`` as **multipart/form-data** with ``file`` and ``model``
   → ``{"code": 0, "data": {"jobId": "..."}}``. A JSON body is rejected with
   HTTP 500; a missing ``model`` gives business code 10007.
2. ``GET {jobs_url}/{jobId}`` → ``data.state`` moves ``pending`` → ``done``, and
   ``done`` carries ``data.resultUrl.jsonUrl``, a presigned object-store URL.
3. ``GET`` that URL **without** the auth header → ``{"errorCode": 0, "result":
   {...}}`` — the same envelope the sync service returns inline, so the loader's
   downstream parsing is reused unchanged.

The token comes from the environment (``api_key_env``), never from the config
file, so it does not land in git, in a database dump, or in the YAML editor's
payload.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import time
from urllib.parse import urljoin

import httpx
from loguru import logger

from bisheng.core.config.settings import PaddleOcrConf, decrypt_token
from bisheng.knowledge.rag.pipeline.loader.provider_probe import PROBE_TIMEOUT_SECONDS, is_http_url
from bisheng.utils.exceptions import EtlException

#: ``data.state`` values that end the poll successfully.
SUCCESS_STATES = {"done", "completed", "success"}
#: ``data.state`` values that end the poll with a provider-side failure.
FAILURE_STATES = {"failed", "error", "canceled", "cancelled"}

#: Business codes worth another attempt: the service is busy, the job is not lost.
RETRYABLE_CODES = {10010, 12002}
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class PaddleOcrJobsError(EtlException):
    """A PaddleOCR jobs request cannot be submitted, completed, or consumed.

    Subclasses ``EtlException`` on purpose: ``api/services/knowledge_imp.py``
    only recognizes that type when it marks a file ``parse_failed`` and writes
    the failure remark. Any other exception class escapes that handler and the
    file is left in a half-updated state.
    """




# --------------------------------------------------------------------------------------
# Response parsing — pure, shared by the sync and async paths.
# --------------------------------------------------------------------------------------


def parse_envelope(data: dict, phase: str) -> dict:
    """Unwrap the jobs ``{code, msg, data}`` envelope, raising on a business error."""
    code = data.get("code", 0)
    if code not in (0, None):
        raise PaddleOcrJobsError(f"PaddleOCR {phase} error (code={code}): {data.get('msg', 'Unknown error')}")
    body = data.get("data")
    if not isinstance(body, dict):
        raise PaddleOcrJobsError(f"PaddleOCR {phase} response has no data")
    return body


def parse_job_id(data: dict, phase: str = "job submission") -> str:
    body = parse_envelope(data, phase)
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id:
        raise PaddleOcrJobsError("PaddleOCR job submission returned no jobId")
    return job_id


def parse_result_url(data: dict, jobs_url: str, phase: str = "job status") -> str | None:
    """Presigned result URL when the job is done, else ``None`` meaning keep polling."""
    body = parse_envelope(data, phase)
    state = str(body.get("state", "")).lower()
    if state in FAILURE_STATES:
        raise PaddleOcrJobsError(f"PaddleOCR job failed: {body.get('errorMsg') or 'no reason given'}")
    if state not in SUCCESS_STATES:
        return None
    result_url = body.get("resultUrl")
    if isinstance(result_url, dict):
        url = result_url.get("jsonUrl")
    elif isinstance(result_url, str):
        url = result_url
    else:
        url = None
    if not isinstance(url, str) or not url:
        raise PaddleOcrJobsError("PaddleOCR job completed without a result URL")
    # The service returns an absolute URL; urljoin leaves that unchanged and
    # resolves anything a future response might hand back relative.
    url = urljoin(jobs_url, url)
    if not is_http_url(url):
        raise PaddleOcrJobsError("PaddleOCR returned an unusable result URL")
    return url


def parse_inline_result(data: dict) -> dict:
    """The ``{errorCode, errorMsg, result}`` envelope shared by both service shapes."""
    if data.get("errorCode", 0) != 0:
        raise PaddleOcrJobsError(f"PaddleOCR API error: {data.get('errorMsg', 'Unknown error')}")
    result = data.get("result")
    return result if isinstance(result, dict) else {}


def response_json(response: httpx.Response, phase: str) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise PaddleOcrJobsError(f"PaddleOCR {phase} returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise PaddleOcrJobsError(f"PaddleOCR {phase} returned an unexpected structure")
    return data


def is_retryable(status_code: int, data: dict | None) -> bool:
    return status_code in RETRYABLE_STATUS_CODES or (data or {}).get("code") in RETRYABLE_CODES


def resolve_token(config: PaddleOcrConf) -> str:
    """Token for the jobs API: the token saved from the admin form, then the environment.

    The stored value wins on purpose. An operator who types a token in the form
    expects it to be used; letting a leftover environment variable override it
    would make the form silently do nothing. Deployments that rotate through the
    environment clear or re-save the stored token from the same page.
    A ciphertext that cannot be decrypted raises rather than degrading to an
    empty token, which would surface later as a bare 401.
    """
    if config.auth_token_enc:
        try:
            return decrypt_token(config.auth_token_enc)
        except Exception as exc:
            raise PaddleOcrJobsError(
                "The stored PaddleOCR token cannot be decrypted; save it again in the document-parse "
                "settings (the encryption key may have changed)"
            ) from exc
    return os.getenv(config.api_key_env, "") if config.api_key_env else ""






def probe_connection(
    config: PaddleOcrConf,
    transport: httpx.BaseTransport | None = None,
    token: str | None = None,
) -> dict:
    """Cheap liveness/credential check for the admin form. Creates no parse job.

    The jobs API needs a file to do anything, but it validates the token and the
    model *before* looking at the payload: submitting with no file returns business
    code 10001 (empty file) when both are accepted, and 401 when the token is bad.
    That distinguishes "wrong token" from "service down" in about half a second,
    without consuming a real parse job.

    Returns ``{"status": ..., "message": ..., "latency_ms": ...}`` where status is
    one of ``ok`` / ``token_missing`` / ``token_invalid`` / ``model_invalid`` /
    ``unreachable`` / ``misconfigured`` / ``error``.
    """
    started = time.monotonic()

    def result(status: str, message: str) -> dict:
        return {"status": status, "message": message, "latency_ms": int((time.monotonic() - started) * 1000)}

    url = config.url.rstrip("/")
    if not is_http_url(url):
        return result("misconfigured", "The service URL is empty or not a valid http(s) URL")

    if token is None:
        try:
            token = resolve_token(config)
        except PaddleOcrJobsError as exc:
            return result("token_invalid", str(exc))

    if config.resolved_service_mode != "jobs":
        # Sync services have no harmless probe payload; any HTTP answer proves the
        # endpoint is reachable, and 401/403 still means the token was rejected.
        try:
            with httpx.Client(transport=transport, timeout=PROBE_TIMEOUT_SECONDS) as client:
                sync_token = token or config.auth_token
                response = client.get(url, headers={"Authorization": f"token {sync_token}"})
        except httpx.HTTPError as exc:
            return result("unreachable", f"Cannot reach {url}: {exc}")
        if response.status_code in (401, 403):
            return result("token_invalid", f"HTTP {response.status_code}: the token was rejected")
        return result("ok", f"Reachable (HTTP {response.status_code})")

    if not config.model:
        return result("misconfigured", "The model name is required by the jobs API")
    if not token:
        return result("token_missing", "No token saved and the configured variable is not set")

    try:
        with httpx.Client(transport=transport, timeout=PROBE_TIMEOUT_SECONDS) as client:
            response = client.post(
                url,
                headers={"Authorization": f"token {token}"},
                # No file on purpose: the service validates the token and model
                # before the payload. A plain urlencoded body is rejected with
                # HTTP 500, so the field has to travel as multipart form data.
                files={"model": (None, config.model)},
            )
    except httpx.HTTPError as exc:
        return result("unreachable", f"Cannot reach {url}: {exc}")

    payload = response_json(response, "connection test") if response.content else {}
    code = payload.get("code")
    if response.status_code in (401, 403) or code in (401, 403):
        return result("token_invalid", "The service rejected the token")
    if code in (10001, 10002) or (code in (0, None) and response.status_code < 500):
        # An empty-file rejection is the expected answer for a valid token+model.
        return result("ok", "The token and model were accepted")
    if code == 10007:
        return result("model_invalid", f"The service rejected the model name: {payload.get('msg', '')}")
    return result("error", f"Unexpected answer (HTTP {response.status_code}): {str(payload)[:200]}")


# --------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------


class PaddleOcrJobsClient:
    """Submits a document to the jobs API and returns the parsed ``result`` dict.

    ``transport`` is injected by tests; it is passed straight to ``httpx.Client``.
    """

    def __init__(self, config: PaddleOcrConf, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.jobs_url = config.url.rstrip("/")
        if not is_http_url(self.jobs_url):
            raise PaddleOcrJobsError("PaddleOCR jobs URL is invalid")
        if not config.model:
            raise PaddleOcrJobsError("PaddleOCR jobs API requires knowledge.paddle_ocr.model (e.g. PaddleOCR-VL-1.6)")
        self.api_key = resolve_token(config)
        if not self.api_key:
            raise PaddleOcrJobsError(
                "PaddleOCR jobs token is missing: save it in the document-parse settings form, "
                f"or export the variable named by knowledge.paddle_ocr.api_key_env (currently {config.api_key_env!r})"
            )
        self.transport = transport

    # -- request plumbing -------------------------------------------------------------

    def _status_url(self, job_id: str) -> str:
        return f"{self.jobs_url}/{job_id}"

    def _same_origin(self, url: str) -> bool:
        target, root = httpx.URL(url), httpx.URL(self.jobs_url)
        return (target.scheme, target.host, target.port) == (root.scheme, root.host, root.port)

    def _headers(self, url: str) -> dict[str, str]:
        """Auth and custom headers go to the jobs host only.

        The presigned ``jsonUrl`` is a different host: sending the token there
        would hand a third-party object store a credential it never asked for, so
        cross-origin requests carry none.
        """
        if not self._same_origin(url):
            return {}
        headers = {"Authorization": f"token {self.api_key}"}
        headers.update(self.config.headers or {})
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.config.timeout, connect=min(self.config.timeout, 30))

    def _delay(self, attempt: int) -> float:
        return self.config.retry_backoff * (2**attempt)

    def _file_parts(self, file_path: str) -> tuple[str, bytes, str]:
        name = os.path.basename(file_path)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(file_path, "rb") as handle:
            return name, handle.read(), mime

    def _log_retry(self, status_code: int, data: dict | None, attempt: int, delay: float) -> None:
        logger.warning(
            "PaddleOCR job submission temporarily unavailable (status={}, code={}); retry {}/{} in {}s",
            status_code,
            (data or {}).get("code"),
            attempt + 1,
            self.config.max_retries,
            delay,
        )

    # -- public API ------------------------------------------------------------------

    def parse(self, file_path: str) -> dict:
        """Submit, poll and fetch ``file_path``; returns the ``result`` dict."""
        deadline = time.monotonic() + self.config.job_timeout_seconds
        try:
            with httpx.Client(transport=self.transport, timeout=self._timeout()) as client:
                return self._run(client, file_path, deadline)
        except httpx.HTTPError as exc:
            raise PaddleOcrJobsError(f"PaddleOCR jobs transport failed: {exc}") from exc

    async def parse_async(self, file_path: str) -> dict:
        """Asynchronous counterpart of :meth:`parse`, for ``PaddleOcrLoader.aload``."""
        deadline = time.monotonic() + self.config.job_timeout_seconds
        try:
            # httpx.MockTransport serves both paths, so the injected transport
            # must reach the async client too — leaving it out would make the
            # async branch untestable and silently ignore a caller's transport.
            async with httpx.AsyncClient(transport=self.transport, timeout=self._timeout()) as client:
                return await self._run_async(client, file_path, deadline)
        except httpx.HTTPError as exc:
            raise PaddleOcrJobsError(f"PaddleOCR jobs transport failed: {exc}") from exc

    # -- sync ------------------------------------------------------------------------

    def _run(self, client: httpx.Client, file_path: str, deadline: float) -> dict:
        name, content, mime = self._file_parts(file_path)
        job_id = self._submit(client, name, content, mime)
        logger.info("PaddleOCR jobs: created parse job {}", job_id)
        result_url = self._wait(client, job_id, deadline)
        # A presigned URL authenticates through its query string; _headers returns
        # {} for it because the object store is not the jobs origin.
        response = client.get(result_url, headers=self._headers(result_url), timeout=self._timeout())
        if response.is_error:
            raise PaddleOcrJobsError(f"PaddleOCR result download failed: status={response.status_code}")
        return parse_inline_result(response_json(response, "result download"))

    def _submit(self, client: httpx.Client, name: str, content: bytes, mime: str) -> str:
        for attempt in range(self.config.max_retries + 1):
            response = client.post(
                self.jobs_url,
                headers=self._headers(self.jobs_url),
                files={"file": (name, content, mime)},
                data=self._form_fields(),
            )
            data = response_json(response, "job submission")
            if is_retryable(response.status_code, data) and attempt < self.config.max_retries:
                delay = self._delay(attempt)
                self._log_retry(response.status_code, data, attempt, delay)
                time.sleep(delay)
                continue
            if response.status_code != 200:
                raise PaddleOcrJobsError(f"PaddleOCR API error: status={response.status_code}, resp={response.text}")
            return parse_job_id(data)
        raise PaddleOcrJobsError(f"PaddleOCR job submission failed after {self.config.max_retries} retries")

    def _form_fields(self) -> dict[str, str]:
        """``model`` plus any extra operator-supplied options, all as form fields."""
        return {"model": self.config.model, **self.config.request_kwargs}

    def _wait(self, client: httpx.Client, job_id: str, deadline: float) -> str:
        url = self._status_url(job_id)
        headers = self._headers(url)
        transient_errors = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PaddleOcrJobsError("PaddleOCR parse job timed out")
            response = client.get(url, headers=headers, timeout=self._timeout())
            if response.is_error:
                transient_errors += 1
                if transient_errors > self.config.max_retries:
                    raise PaddleOcrJobsError(f"PaddleOCR job status failed: status={response.status_code}")
            else:
                transient_errors = 0
                result_url = parse_result_url(response_json(response, "job status"), self.jobs_url)
                if result_url:
                    return result_url
            time.sleep(min(self.config.poll_interval_seconds, max(deadline - time.monotonic(), 0)))

    # -- async -----------------------------------------------------------------------

    async def _run_async(self, client, file_path: str, deadline: float) -> dict:
        name, content, mime = self._file_parts(file_path)
        job_id = await self._submit_async(client, name, content, mime)
        logger.info("PaddleOCR jobs: created parse job {}", job_id)
        result_url = await self._wait_async(client, job_id, deadline)
        response = await client.get(result_url, headers=self._headers(result_url))
        if response.is_error:
            raise PaddleOcrJobsError(f"PaddleOCR result download failed: status={response.status_code}")
        return parse_inline_result(response_json(response, "result download"))

    async def _submit_async(self, client, name: str, content: bytes, mime: str) -> str:
        for attempt in range(self.config.max_retries + 1):
            response = await client.post(
                self.jobs_url,
                headers=self._headers(self.jobs_url),
                files={"file": (name, content, mime)},
                data=self._form_fields(),
            )
            data = response_json(response, "job submission")
            if is_retryable(response.status_code, data) and attempt < self.config.max_retries:
                delay = self._delay(attempt)
                self._log_retry(response.status_code, data, attempt, delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code != 200:
                raise PaddleOcrJobsError(f"PaddleOCR API error: status={response.status_code}, resp={response.text}")
            return parse_job_id(data)
        raise PaddleOcrJobsError(f"PaddleOCR job submission failed after {self.config.max_retries} retries")

    async def _wait_async(self, client, job_id: str, deadline: float) -> str:
        url = self._status_url(job_id)
        headers = self._headers(url)
        transient_errors = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PaddleOcrJobsError("PaddleOCR parse job timed out")
            response = await client.get(url, headers=headers)
            if response.is_error:
                transient_errors += 1
                if transient_errors > self.config.max_retries:
                    raise PaddleOcrJobsError(f"PaddleOCR job status failed: status={response.status_code}")
            else:
                transient_errors = 0
                result_url = parse_result_url(response_json(response, "job status"), self.jobs_url)
                if result_url:
                    return result_url
            await asyncio.sleep(min(self.config.poll_interval_seconds, max(deadline - time.monotonic(), 0)))
