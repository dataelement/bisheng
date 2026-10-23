"""TLS workload material transport with fresh Ed25519 signatures per request.

Tickets never authorize renewal by themselves. Local output is installed only
once the complete frozen size and digest match; an incomplete block is discarded.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import ssl
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime_manager import material_protocol as wire
from runtime_manager.platform_protocol import canonical_json


class MaterialClientError(RuntimeError):
    def __init__(self, reason, status=503):
        super().__init__(reason)
        self.status = status


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise MaterialClientError("material_identity_invalid", 400) from None
    return value


class MaterialClient:
    def __init__(
        self,
        base_url,
        *,
        delegation_id,
        key_id,
        pod_uid,
        private_key,
        deadline,
        ca_file=None,
        proxy_url=None,
        transport=None,
        clock=time.time,
        sleep=time.sleep,
        chunk_bytes=8 * 1024**2,
        max_attempts=3,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise MaterialClientError("material_https_origin_required", 400)
        _uuid(delegation_id)
        _uuid(pod_uid)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key_id) or not isinstance(private_key, Ed25519PrivateKey):
            raise MaterialClientError("material_signer_invalid", 400)
        if (
            type(deadline) not in {int, float}
            or not math.isfinite(deadline)
            or deadline <= 0
            or type(chunk_bytes) is not int
            or not 1 <= chunk_bytes <= wire.CHUNK_LIMIT
            or type(max_attempts) is not int
            or not 1 <= max_attempts <= 5
        ):
            raise MaterialClientError("material_bounds_invalid", 400)
        self.delegation_id, self.key_id, self.pod_uid = delegation_id, key_id, pod_uid
        self._key, self.deadline = private_key, deadline
        self.clock, self.sleep, self.chunk_bytes, self.max_attempts = clock, sleep, chunk_bytes, max_attempts
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            verify=ssl.create_default_context(cafile=str(ca_file) if ca_file else None),
            proxy=proxy_url,
            trust_env=False,
            follow_redirects=False,
            timeout=60,
        )

    def close(self):
        self._http.close()

    def _remaining(self, session=None):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise MaterialClientError("material_phase_expired", 403)
        if session is not None:
            remaining = min(remaining, session["expires_at"] - self.clock())
            if remaining <= 0:
                raise MaterialClientError("material_ticket_expired", 401)
        return min(60, remaining)

    def _headers(self, method, target, raw, session=None):
        self._remaining(session)
        return wire.signed_headers(
            method,
            target,
            raw,
            private_key=self._key,
            delegation_id=self.delegation_id,
            key_id=self.key_id,
            pod_uid=self.pod_uid,
            timestamp=int(self.clock()),
            ticket=session["ticket"] if session else "",
        )

    @staticmethod
    def _check(response):
        if not 200 <= response.status_code < 300:
            # Remote payloads and proxy credentials never enter an exception.
            raise MaterialClientError("material_request_refused", response.status_code)

    def _call(self, method, target, *, document=None, raw=b"", session=None):
        raw = canonical_json(document) if document is not None else raw
        headers = self._headers(method, target, raw, session)
        if document is not None:
            headers["Content-Type"] = "application/json"
        try:
            with self._http.stream(
                method, target, content=raw, headers=headers, timeout=self._remaining(session)
            ) as response:
                self._check(response)
                body = bytearray()
                for chunk in response.iter_bytes():
                    self._remaining(session)
                    if len(body) + len(chunk) > wire.CONTROL_LIMIT:
                        raise MaterialClientError("material_response_limit", 503)
                    body.extend(chunk)
            return wire.parse_control(
                bytes(body),
                allowed={
                    "transfer_id",
                    "artifact_id",
                    "action",
                    "state",
                    "offset",
                    "sha256",
                    "size_bytes",
                    "kind",
                    "platform",
                    "ticket",
                    "expires_at",
                    "confirmed_at",
                },
            )
        except httpx.HTTPError:
            raise MaterialClientError("material_transport_unavailable", 503) from None
        except wire.MaterialProtocolError:
            raise MaterialClientError("material_response_invalid", 503) from None

    def _backoff(self, attempt):
        remaining = self._remaining()
        self.sleep(min(0.2 * 2**attempt, remaining))

    def _exchange(self, declaration):
        for attempt in range(self.max_attempts):
            try:
                session = self._call("POST", wire.PREFIX + "/exchange", document=declaration)
                _uuid(session.get("transfer_id"))
                if session.get("action") != declaration["action"] or not isinstance(session.get("artifact_id"), str):
                    raise MaterialClientError("material_session_scope_invalid", 403)
                if declaration["action"] == "download" and session["artifact_id"] != declaration["artifact_id"]:
                    raise MaterialClientError("material_session_scope_invalid", 403)
                for name in ("offset", "size_bytes", "expires_at"):
                    wire.unsigned_integer(session.get(name))
                if (
                    session.get("state") not in {"open", "confirmed"}
                    or not isinstance(session.get("sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", session["sha256"])
                    or session["offset"] > session["size_bytes"]
                    or not isinstance(session.get("ticket"), str)
                    or not re.fullmatch(r"[A-Za-z0-9._~-]{1,512}", session["ticket"])
                    or not self.clock() < session["expires_at"] <= self.clock() + 360
                ):
                    raise MaterialClientError("material_session_invalid", 403)
                if declaration["action"] == "upload" and any(
                    session.get(name) != declaration.get(name, "")
                    for name in ("kind", "platform", "sha256", "size_bytes")
                ):
                    raise MaterialClientError("material_session_declaration_changed", 403)
                return session
            except wire.MaterialProtocolError:
                raise MaterialClientError("material_session_invalid", 403) from None
            except MaterialClientError as exc:
                if exc.status not in {429, 503, 409} or attempt + 1 == self.max_attempts:
                    raise
                self._backoff(attempt)

    def _renew(self, declaration, previous):
        renewed = self._exchange(declaration)
        if any(
            renewed[name] != previous[name]
            for name in ("transfer_id", "artifact_id", "action", "sha256", "size_bytes", "kind", "platform")
        ):
            raise MaterialClientError("material_session_identity_changed", 403)
        return renewed

    def describe(self, artifact_id):
        """Read the frozen artifact manifest through the authorized backend.

        Helpers receive frozen IDs from the plan, never arbitrary object paths.
        The backend validates those IDs against current delivery on each exchange.
        """
        session = self._exchange({"action": "download", "artifact_id": artifact_id})
        return {key: value for key, value in session.items() if key != "ticket"}

    def _session_call(self, declaration, session, method, suffix="", **kwargs):
        for attempt in range(self.max_attempts):
            try:
                result = self._call(
                    method, wire.PREFIX + f"/transfers/{session['transfer_id']}" + suffix, session=session, **kwargs
                )
                return result, session
            except MaterialClientError as exc:
                if exc.status == 401:
                    session = self._renew(declaration, session)
                elif method == "GET" and exc.status in {429, 503}:
                    self._backoff(attempt)
                else:
                    raise
                if attempt + 1 == self.max_attempts:
                    raise

    def _block(self, session, offset, size):
        target = wire.PREFIX + f"/transfers/{session['transfer_id']}/content?length={size}&offset={offset}"
        headers = self._headers("GET", target, b"", session)
        expected = min(size, session["size_bytes"] - offset)
        try:
            with self._http.stream("GET", target, headers=headers, timeout=self._remaining(session)) as response:
                self._check(response)
                content_range = f"bytes {offset}-{offset + expected - 1}/{session['size_bytes']}"
                if (
                    response.status_code != 206
                    or response.headers.get("Content-Range") != content_range
                    or response.headers.get("Content-Length") != str(expected)
                ):
                    raise MaterialClientError("material_range_response_invalid", 403)
                body = bytearray()
                end = min(self.deadline, self.clock() + 60)
                for chunk in response.iter_bytes():
                    self._remaining(session)
                    if self.clock() >= end or len(body) + len(chunk) > expected:
                        raise MaterialClientError("material_content_bounds_invalid", 403)
                    body.extend(chunk)
                if len(body) != expected:
                    raise MaterialClientError("material_content_truncated", 503)
                return bytes(body)
        except httpx.HTTPError:
            raise MaterialClientError("material_transport_unavailable", 503) from None

    def download(self, artifact_id, destination, *, expected_sha256, expected_size, max_bytes=10 * 1024**3):
        if (
            type(expected_size) is not int
            or not 0 <= expected_size <= max_bytes
            or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
        ):
            raise MaterialClientError("material_frozen_manifest_invalid", 403)
        declaration = {"action": "download", "artifact_id": artifact_id}
        session = self._exchange(declaration)
        if (session["sha256"], session["size_bytes"]) != (expected_sha256, expected_size):
            raise MaterialClientError("material_frozen_manifest_changed", 403)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(prefix=".material-", dir=destination.parent, delete=False) as output:
                temporary = Path(output.name)
                offset, digest = 0, hashlib.sha256()
                while offset < expected_size:
                    for attempt in range(self.max_attempts):
                        try:
                            block = self._block(session, offset, min(self.chunk_bytes, expected_size - offset))
                            break
                        except MaterialClientError as exc:
                            if exc.status == 401:
                                session = self._renew(declaration, session)
                            elif exc.status in {429, 503}:
                                self._backoff(attempt)
                            else:
                                raise
                            if attempt + 1 == self.max_attempts:
                                raise
                    output.write(block)
                    digest.update(block)
                    offset += len(block)
                output.flush()
                os.fsync(output.fileno())
            self._remaining()
            if digest.hexdigest() != expected_sha256:
                raise MaterialClientError("material_digest_mismatch", 403)
            os.replace(temporary, destination)
            return session
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def upload(self, path, *, kind, platform="", metadata=None):
        path = Path(path)
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as source:
            while chunk := source.read(1024**2):
                self._remaining()
                digest.update(chunk)
                size += len(chunk)
        declaration = {
            "action": "upload",
            "kind": kind,
            "sha256": digest.hexdigest(),
            "size_bytes": size,
            "platform": platform,
            "metadata": metadata or {},
        }
        session = self._exchange(declaration)
        offset = session["offset"]
        with path.open("rb") as source:
            while offset < size:
                source.seek(offset)
                block = source.read(min(self.chunk_bytes, size - offset))
                if not block:
                    raise MaterialClientError("material_local_content_changed", 403)
                for attempt in range(self.max_attempts):
                    try:
                        result, session = self._session_call(
                            declaration, session, "PUT", f"/content?offset={offset}", raw=block
                        )
                    except MaterialClientError as exc:
                        if exc.status not in {409, 429, 503}:
                            raise
                        result, session = self._session_call(declaration, session, "GET")
                        if result.get("offset") == offset and attempt + 1 < self.max_attempts:
                            self._backoff(attempt)
                            continue
                    if type(result.get("offset")) is not int or result["offset"] != offset + len(block):
                        raise MaterialClientError("material_offset_invalid", 409)
                    offset = result["offset"]
                    break
        expected = {"sha256": digest.hexdigest(), "size_bytes": size}
        try:
            result, session = self._session_call(declaration, session, "POST", "/finalize", document=expected)
        except MaterialClientError as exc:
            if exc.status not in {409, 429, 503}:
                raise
            result, session = self._session_call(declaration, session, "GET")
            if result.get("state") != "confirmed" or not result.get("confirmed_at"):
                result, session = self._session_call(declaration, session, "POST", "/finalize", document=expected)
            else:
                result = {**result, "state": "verified"}
        if (
            result.get("state") != "verified"
            or not result.get("confirmed_at")
            or any(result.get(key) != value for key, value in expected.items())
            or result.get("artifact_id") != session["artifact_id"]
        ):
            raise MaterialClientError("material_confirmation_invalid", 409)
        return result
