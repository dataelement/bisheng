"""Thin synchronous client for MinerU 4.0's V1 upload and parse-job API."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from loguru import logger

from bisheng.core.config.settings import MineruV4Conf


class MineruV4Error(Exception):
    """A V1 transport or response cannot be safely consumed."""


class MineruV4Client:
    MAX_ZIP_BYTES = 512 * 1024 * 1024
    MAX_REDIRECTS = 3

    def __init__(self, config: MineruV4Conf, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.root = config.api_url.rstrip("/")
        parsed = httpx.URL(self.root) if self.root else None
        if not parsed or parsed.scheme not in {"http", "https"} or not parsed.host or parsed.query:
            raise MineruV4Error("MinerU V1 API root URL is invalid")
        self.api_key = os.getenv(config.api_key_env, "") if config.api_key_env else ""
        self.transport = transport

    def _url(self, path: str) -> str:
        return f"{self.root}{path}"

    def _same_origin(self, url: str) -> bool:
        target = httpx.URL(url)
        root = httpx.URL(self.root)
        return (target.scheme, target.host, target.port) == (root.scheme, root.host, root.port)

    def _resolved_url(self, url: str) -> str:
        resolved = urljoin(f"{self.root}/", url)
        parsed = httpx.URL(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.host or parsed.userinfo:
            raise MineruV4Error("MinerU V1 returned an invalid transfer URL")
        if not self._same_origin(resolved) and parsed.scheme != "https":
            raise MineruV4Error("MinerU V1 cross-origin transfer must use HTTPS")
        return resolved

    def _headers(self, url: str, extra: dict | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self.api_key and self._same_origin(url):
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _required_string(data: dict, key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise MineruV4Error(f"MinerU V1 response missing {key}")
        return value

    @staticmethod
    def _json(response: httpx.Response, phase: str) -> dict:
        if response.is_error:
            raise MineruV4Error(f"MinerU V1 {phase} returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise MineruV4Error(f"MinerU V1 {phase} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise MineruV4Error(f"MinerU V1 {phase} returned invalid structure")
        return data

    def _timeout(self, seconds: float) -> httpx.Timeout:
        return httpx.Timeout(seconds, connect=min(seconds, self.config.connect_timeout_seconds))

    def _phase_timeout(self, deadline: float, configured: float) -> httpx.Timeout:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MineruV4Error("MinerU V1 parse job timed out")
        return self._timeout(min(configured, remaining))

    def _upload(self, client: httpx.Client, file_path: str, filename: str, deadline: float) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                self._phase_timeout(deadline, self.config.request_timeout_seconds)
                digest.update(chunk)
        sha = digest.hexdigest()
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        api_url = self._url("/v1/uploads")
        response = client.post(
            api_url,
            headers=self._headers(api_url),
            json={
                "filename": filename,
                "bytes": os.path.getsize(file_path),
                "mime_type": mime,
                "purpose": "parse",
                "sha256sum": sha,
            },
            timeout=self._phase_timeout(deadline, self.config.request_timeout_seconds),
        )
        upload = self._json(response, "create upload")
        status = self._required_string(upload, "status")
        if status == "completed":
            file = upload.get("file")
            if not isinstance(file, dict):
                raise MineruV4Error("MinerU V1 completed upload has no file")
            return self._required_string(file, "id")
        if status != "pending":
            raise MineruV4Error(f"MinerU V1 upload reached unexpected status {status}")
        upload_id = self._required_string(upload, "id")
        upload_url = self._resolved_url(self._required_string(upload, "upload_url"))
        method = self._required_string(upload, "upload_method")
        raw_headers = upload.get("upload_headers") or {}
        if not isinstance(raw_headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in raw_headers.items()
        ):
            raise MineruV4Error("MinerU V1 upload headers are invalid")

        def chunks():
            with open(file_path, "rb") as source:
                while chunk := source.read(1024 * 1024):
                    self._phase_timeout(deadline, self.config.transfer_timeout_seconds)
                    yield chunk

        response = client.request(
            method,
            upload_url,
            headers=self._headers(upload_url, raw_headers),
            content=chunks(),
            timeout=self._phase_timeout(deadline, self.config.transfer_timeout_seconds),
        )
        if response.is_error or response.is_redirect:
            raise MineruV4Error(f"MinerU V1 byte upload returned HTTP {response.status_code}")
        complete_url = self._url(f"/v1/uploads/{upload_id}/complete")
        complete = self._json(
            client.post(
                complete_url,
                headers=self._headers(complete_url),
                json={"sha256sum": sha},
                timeout=self._phase_timeout(deadline, self.config.request_timeout_seconds),
            ),
            "complete upload",
        )
        if complete.get("status") != "completed" or not isinstance(complete.get("file"), dict):
            raise MineruV4Error("MinerU V1 upload did not complete")
        return self._required_string(complete["file"], "id")

    def _create_job(self, client: httpx.Client, file_id: str, ocr_mode: str, deadline: float) -> str:
        payload = {
            **self.config.request_kwargs,
            "files": [{"source": {"type": "file_id", "file_id": file_id}}],
            "tier": self.config.tier,
            "ocr_mode": ocr_mode,
            "output_formats": ["zip"],
        }
        api_url = self._url("/v1/parse/jobs")
        result = self._json(
            client.post(
                api_url,
                headers=self._headers(api_url),
                json=payload,
                timeout=self._phase_timeout(deadline, self.config.request_timeout_seconds),
            ),
            "create parse job",
        )
        return self._required_string(result, "job_id")

    def _wait_for_zip(self, client: httpx.Client, job_id: str, deadline: float) -> str:
        api_url = self._url(f"/v1/parse/jobs/{job_id}")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MineruV4Error("MinerU V1 parse job timed out")
            result = self._json(
                client.get(
                    api_url,
                    headers=self._headers(api_url),
                    timeout=self._phase_timeout(deadline, self.config.request_timeout_seconds),
                ),
                "poll parse job",
            )
            status = self._required_string(result, "status")
            if status == "completed":
                files = result.get("files")
                if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
                    raise MineruV4Error("MinerU V1 parse job has invalid files")
                file = files[0]
                if file.get("status") != "completed":
                    raise MineruV4Error("MinerU V1 parse file did not complete")
                outputs = file.get("output_files")
                zip_file = outputs.get("zip") if isinstance(outputs, dict) else None
                if not isinstance(zip_file, dict):
                    raise MineruV4Error("MinerU V1 parse result has no zip output")
                return self._required_string(zip_file, "file_id")
            if status in {"partial", "failed", "canceled"}:
                raise MineruV4Error(f"MinerU V1 parse job ended with {status}")
            if status not in {"queued", "running"}:
                raise MineruV4Error(f"MinerU V1 parse job has unexpected status {status}")
            time.sleep(min(self.config.poll_interval_seconds, max(0, deadline - time.monotonic())))

    def _download(self, client: httpx.Client, file_id: str, tmp_dir: str, deadline: float) -> str:
        url = self._url(f"/v1/files/{file_id}/content")
        target = Path(tmp_dir) / "mineru-v4-result.zip"
        for _ in range(self.MAX_REDIRECTS + 1):
            with client.stream(
                "GET",
                url,
                headers=self._headers(url),
                timeout=self._phase_timeout(deadline, self.config.transfer_timeout_seconds),
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise MineruV4Error("MinerU V1 download redirect has no location")
                    url = self._resolved_url(urljoin(url, location))
                    continue
                if response.is_error:
                    raise MineruV4Error(f"MinerU V1 ZIP download returned HTTP {response.status_code}")
                written = 0
                try:
                    with target.open("wb") as output:
                        for chunk in response.iter_bytes():
                            self._phase_timeout(deadline, self.config.transfer_timeout_seconds)
                            written += len(chunk)
                            if written > self.MAX_ZIP_BYTES:
                                raise MineruV4Error("MinerU V1 ZIP exceeds size limit")
                            output.write(chunk)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                if not written:
                    raise MineruV4Error("MinerU V1 ZIP is empty")
                return str(target)
        raise MineruV4Error("MinerU V1 ZIP download exceeded redirect limit")

    def parse(self, file_path: str, filename: str, ocr_mode: str, tmp_dir: str) -> str:
        deadline = time.monotonic() + self.config.job_timeout_seconds
        try:
            with httpx.Client(transport=self.transport, follow_redirects=False) as client:
                file_id = self._upload(client, file_path, filename, deadline)
                job_id = self._create_job(client, file_id, ocr_mode, deadline)
                logger.info("mineru_v4: created parse job {}", job_id)
                zip_file_id = self._wait_for_zip(client, job_id, deadline)
                return self._download(client, zip_file_id, tmp_dir, deadline)
        except httpx.HTTPError as exc:
            raise MineruV4Error("MinerU V1 transport failed") from exc
