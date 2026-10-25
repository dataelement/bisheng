"""Executable snapshot of the contracts this SDK consumes.

This module is deliberately dumb. Every payload is shaped exactly like the one
the platform actually returns, **including the parts that look wrong**:

* ``/api/v1`` answers HTTP 200 with the business code inside the envelope, while
  ``/api/v2`` puts a real status on the status line *and* keeps the envelope.
* the 260-segment error payload is ``data = {"exception": <str>, **kwargs}``, so
  ``26003`` carries ``data.required`` as a **single string**, never a list.
* runtime-manager's attachment API uses a completely different envelope —
  ``{"detail": {"code": "<machine code>", "message": …}}`` — and answers
  ``200 {}`` to a successful DELETE.

"Tidying" any of these into a more sensible shape would mean the SDK is tested
against a server that does not exist. If a shape looks wrong, fix the server or
the design note, not this file.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

# Assembled rather than written out so `scripts/arch-guard.sh` RULE-7 never
# matches a long credential literal in this repo's Python (design pit 22).
FAKE_APP_TOKEN = "bs-sak-" + "a" * 24
FAKE_OBO = "eyJ" + "b" * 40
FAKE_DEV_HANDLE = "bsdev." + "c" * 24 + "." + "d" * 16
FAKE_STORAGE_TOKEN = "st-" + "e" * 30

PLATFORM_BASE = "http://platform.test"
STORAGE_ENDPOINT = "http://runtime-manager.test:8091/v1/apps/app-1/storage"

VERSIONS_PATH = "/api/v1/dev-toolkit/versions"
RETRIEVE_PATH = "/api/v2/filelib/retrieve"


def encode_header_value(value: str) -> str:
    """app-proxy's `encode_header_value`: ASCII verbatim, anything else quoted."""
    if value.isascii():
        return value
    return quote(value, safe="/")


def hosted_headers(
    *,
    user_id: str = "42",
    user_name: str = "张三",
    tenant_id: str = "1",
    dept: bool = True,
    subject_kind: str = "human",
    app_id: str = "app-1",
    token: str | None = FAKE_OBO,
    request_id: str = "req-1",
) -> list[tuple[str, str]]:
    """The ten headers app-proxy injects, in wire order.

    ``dept=False`` **omits** the three department headers rather than sending
    them empty — that is what the injector does for a subject with no
    department, and an app that cannot tell the two apart is the bug this
    fixture exists to catch.
    """
    headers: list[tuple[str, str]] = [
        ("X-BiSheng-User-Id", user_id),
        ("X-BiSheng-User-Name", encode_header_value(user_name)),
        ("X-BiSheng-Tenant-Id", tenant_id),
    ]
    if dept:
        headers += [
            ("X-BiSheng-Dept-Id", "7"),
            ("X-BiSheng-Dept-Name", encode_header_value("财务部")),
            ("X-BiSheng-Dept-Path", encode_header_value("集团/财务部")),
        ]
    headers += [
        ("X-BiSheng-Subject-Kind", subject_kind),
        ("X-BiSheng-App-Id", app_id),
    ]
    if token:
        headers.append(("X-BiSheng-Access-Token", token))
    headers.append(("X-BiSheng-Request-Id", request_id))
    return headers


def dev_headers(*, token: str | None = FAKE_DEV_HANDLE) -> list[tuple[str, str]]:
    """What `bisheng dev`'s mini-proxy injects for a service-account login."""
    return hosted_headers(
        user_id="9001",
        user_name="dev-service-account",
        dept=False,
        subject_kind="service_account",
        token=token,
    )


# --- envelopes ------------------------------------------------------------


def v1_envelope(data: Any) -> dict[str, Any]:
    return {"status_code": 200, "status_message": "SUCCESS", "data": data}


def v2_error_body(code: int, message: str, data: Any = None) -> dict[str, Any]:
    return {
        "status_code": code,
        "status_message": message,
        "data": data if data is not None else {"exception": message},
    }


def versions_payload(version: str | None = "0.1.0", min_compatible: str | None = "0.1.0") -> dict[str, Any]:
    sdk = None if version is None else {"version": version, "min_compatible": min_compatible}
    return {
        "platform": {"version": "3.0.0"},
        "cli": {"version": "3.0.0", "min_compatible": "3.0.0"},
        "sdk": sdk,
    }


def retrieve_payload(chunks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = chunks if chunks is not None else [_chunk()]
    return {"chunks": rows, "total": len(rows)}


def _chunk(content: str = "年假 5 天", knowledge_id: int = 12, document_id: int = 7) -> dict[str, Any]:
    return {
        "content": content,
        "knowledge_id": knowledge_id,
        "document_id": document_id,
        "document_name": "员工手册.pdf",
        "chunk_index": 3,
        "document_update_time": "2026-09-01 10:00:00",
    }


def storage_meta(key: str = "报告/2026.pdf", size: int = 11) -> dict[str, Any]:
    return {
        "key": key,
        "size": size,
        "content_type": "application/pdf",
        "etag": "abc123",
        "last_modified": "2026-09-16T10:00:00+00:00",
    }


def manager_error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    body = {"code": code, "message": message}
    body.update(extra)
    return {"detail": body}


# --- transports -----------------------------------------------------------


class RecordingTransport:
    """A `httpx.MockTransport` that keeps every request it answered."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.sync = httpx.MockTransport(self._record)
        self.asgi = httpx.MockTransport(self._record)

    def _record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def routes(handlers: dict[str, Callable[[httpx.Request], httpx.Response]]) -> RecordingTransport:
    """Route by URL path; an unrouted path fails loudly rather than 404-ing."""

    def handler(request: httpx.Request) -> httpx.Response:
        for path, respond in handlers.items():
            if request.url.path == path or request.url.path.startswith(path):
                return respond(request)
        raise AssertionError(f"unrouted request: {request.method} {request.url}")

    return RecordingTransport(handler)


def json_response(status: int, body: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)
