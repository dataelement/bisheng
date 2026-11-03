"""MK transport. Do not log request URLs: they contain the MK access token."""

import hashlib
import json
import threading
import time
from pathlib import Path

import requests


class DocFlowError(RuntimeError):
    """An actionable, credential-free OCR stage failure."""


class SubmissionUnknown(DocFlowError):
    """Submission may have reached the remote server; do not replay it."""


class DocFlowBusy(DocFlowError):
    """No distributed execution slot is available."""


class DocFlowClient:
    _tokens: dict[str, tuple[str, float]] = {}
    _token_lock = threading.Lock()

    def __init__(self, config: dict, session=None, clock=time.monotonic):
        self.config = config
        self.clock = clock
        self.session = session or requests.Session()
        self.session.trust_env = bool(config.get("trust_env", False))
        self.session.headers.clear()
        self.session.headers.update({"User-Agent": "curl/8.4.0", "Accept": "*/*"})
        self.base = config["url"].rstrip("/")
        self.timeout = float(config.get("timeout", 120))
        self.token = ""

    def close(self):
        self.session.close()

    def _post(self, path, stage, *, payload=None, params=None, headers=None, files=None, timeout=None):
        request_headers = dict(headers or {})
        if self.config.get("host"):
            request_headers["Host"] = self.config["host"]
        kwargs = {
            "headers": request_headers,
            "params": params,
            "allow_redirects": False,
            "timeout": (min(10, timeout or self.timeout), timeout or self.timeout),
        }
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            kwargs["data"] = json.dumps(payload).encode("utf-8")
        if files is not None:
            kwargs["files"] = files
        try:
            response = self.session.post(self.base + path, **kwargs)
        except requests.RequestException as error:
            raise DocFlowError(f"DocFlow {stage}: network {type(error).__name__}") from None
        if response.status_code != 200:
            raise DocFlowError(f"DocFlow {stage}: HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise DocFlowError(f"DocFlow {stage}: expected JSON response") from None
        if not isinstance(result, dict):
            raise DocFlowError(f"DocFlow {stage}: expected JSON object")
        return result

    def authenticate(self):
        key = hashlib.sha256(
            json.dumps([self.base, self.config.get("host"), self.config["app_key"], self.config["app_secret"]]).encode()
        ).hexdigest()
        with self._token_lock:
            cached = self._tokens.get(key)
            if cached and cached[1] > self.clock():
                self.token = cached[0]
                return
            result = self._post(
                "/authapi/getToken",
                "token",
                payload={"appKey": self.config["app_key"], "appSecret": self.config["app_secret"]},
            )
            token = result.get("access_token")
            if result.get("errcode") not in (0, "0") or not isinstance(token, str) or not token:
                raise DocFlowError("DocFlow token: credentials rejected")
            self.token = token
            self._tokens[key] = (token, self.clock() + max(0, int(result.get("expires_in", 7200)) - 60))

    def upload(self, path):
        with open(path, "rb") as handle:
            result = self._post(
                "/openapi/sys-attach/fileStream/upload",
                "upload",
                headers=self.config.get("upload_headers"),
                files={"fdFile": (Path(path).name, handle)},
            )
        data = result.get("data") or {}
        attachment = data.get("fdAttachFileId") or data.get("fdId")
        if result.get("success") is not True or not attachment:
            raise DocFlowError("DocFlow upload: missing attachment ID or upload rejected")
        return str(attachment)

    def invoke(self, function, payload, timeout=None):
        self.authenticate()
        result = self._post(
            "/openapi/tic-definition/integrationInterface/call",
            "invoke",
            params={"functionCode": function, "access_token": self.token},
            payload=payload,
            headers={
                "x-ti-app-id": self.config["docflow_app_id"],
                "x-ti-secret-code": self.config["docflow_secret_code"],
            },
            timeout=timeout,
        )
        data = result.get("data") or {}
        if result.get("success") is not True or data.get("code") not in (200, "200"):
            # Only the trace ID is retained; upstream messages can echo secrets.
            trace = str(result.get("traceId", ""))
            trace = "".join(ch for ch in trace if ch.isalnum())[:100]
            raise DocFlowError(f"DocFlow invoke: rejected; trace_id={trace}")
        value = data.get("result")
        if not isinstance(value, dict):
            raise DocFlowError("DocFlow invoke: missing result object")
        return value

    def submit(self, attachment):
        try:
            result = self.invoke(
                "function_0b704f75cfc16b4a",
                {"file": {"fileId": attachment}, "workspace_id": self.config["workspace_id"]},
            )
            files = result.get("files") or []
            if not files or any(not item.get("id") for item in files):
                raise DocFlowError("DocFlow submit: missing remote file IDs")
            return {
                "files": [{"id": str(item["id"]), "task_id": str(item.get("task_id", ""))} for item in files],
                "batch_number": str(result.get("batch_number", "")),
            }
        except DocFlowError as error:
            raise SubmissionUnknown("DocFlow submission outcome unknown; reconcile remote task before retry") from error

    def fetch(self, file_id, timeout=None):
        page = 1
        found = {}
        while True:
            result = self.invoke(
                "function_b2560ffbebaee1a3",
                {
                    "workspace_id": self.config["workspace_id"],
                    "file_id": str(file_id),
                    "page": page,
                    "page_size": 1000,
                    "with_document": True,
                },
                timeout=timeout,
            )
            files = result.get("files") or []
            for item in files:
                if str(item.get("id")) == str(file_id):
                    found[str(file_id)] = item
            total = int(result.get("total", len(files)))
            if page * 1000 >= total:
                return list(found.values())
            if not files or page >= 100:
                raise DocFlowError("DocFlow query: inconsistent or excessive pagination")
            page += 1
