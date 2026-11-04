"""material-v1 wire codec. Scope/ownership is checked separately before nonce use.

Kept independent in backend and execution distributions; fixed vectors and
cross-verification guard their wire compatibility. No service HMAC is shared.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import time
from dataclasses import dataclass, field
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger(__name__)
PREFIX = "/internal/app-runtime/v2/material-access"
CHUNK_LIMIT = 16 * 1024 * 1024
CONTROL_LIMIT = 64 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ROUTE = re.compile(re.escape(PREFIX) + rf"/(?:exchange|transfers/({_UUID})(?:/(content|finalize))?)")
_FIELDS = {"delegation", "key-id", "pod-uid", "timestamp", "nonce", "content-sha256", "ticket", "signature"}


class MaterialProtocolError(ValueError):
    def __init__(self, reason: str, status_code: int = 400):
        super().__init__(reason)
        self.status_code = status_code


@dataclass(frozen=True)
class MaterialProof:
    delegation_id: str
    key_id: str
    pod_uid: str
    timestamp: int
    nonce: str
    content_sha256: str
    ticket: str = field(repr=False)


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(_UUID, value) or str(UUID(value)) != value:
        raise MaterialProtocolError("material_uuid_invalid")
    return value


def unsigned_integer(value, *, maximum=2**63 - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise MaterialProtocolError("material_integer_invalid")
    return value


def _decimal(raw):
    if not re.fullmatch(r"0|[1-9][0-9]{0,18}", raw):
        raise MaterialProtocolError("material_query_integer_invalid")
    return unsigned_integer(int(raw))


def canonical_target(method: str, target: str) -> str:
    if (
        not isinstance(target, str)
        or len(target) > 1024
        or not target.isascii()
        or any(c in target for c in "%#\\\r\n\x00 ")
    ):
        raise MaterialProtocolError("material_target_invalid")
    path, _, raw = target.partition("?")
    match = _ROUTE.fullmatch(path)
    if not match:
        raise MaterialProtocolError("material_path_invalid")
    transfer_id, sub = match.groups()
    query = {}
    if raw:
        for pair in raw.split("&"):
            if pair.count("=") != 1:
                raise MaterialProtocolError("material_query_invalid")
            name, value = pair.split("=")
            if name in query:
                raise MaterialProtocolError("material_query_duplicate")
            query[name] = _decimal(value)
    if transfer_id is None:
        required, verb = set(), "POST"
    elif sub == "content":
        required = {"length", "offset"} if method == "GET" else {"offset"}
        verb = method if method in {"GET", "PUT"} else ""
    else:
        required, verb = set(), "POST" if sub == "finalize" else "GET"
    if method != verb or set(query) != required:
        raise MaterialProtocolError("material_method_or_query_invalid")
    if "length" in query and not 1 <= query["length"] <= CHUNK_LIMIT:
        raise MaterialProtocolError("material_chunk_length_invalid")
    canonical = "&".join(f"{k}={v}" for k, v in sorted(query.items()))
    return path + ("?" + canonical if canonical else "")


def _shape(method, target, body):
    if method not in {"GET", "POST", "PUT"} or canonical_target(method, target) != target:
        raise MaterialProtocolError("material_target_not_canonical")
    if not isinstance(body, bytes):
        raise MaterialProtocolError("material_body_invalid")
    if method == "GET" and body:
        raise MaterialProtocolError("material_get_body_refused")
    if len(body) > (CHUNK_LIMIT if method == "PUT" else CONTROL_LIMIT):
        raise MaterialProtocolError("material_body_limit", 413)
    if method == "PUT" and not body:
        raise MaterialProtocolError("material_empty_chunk_refused")


def _identity(delegation_id, key_id, pod_uid, timestamp, nonce, ticket):
    _uuid(delegation_id)
    _uuid(pod_uid)
    if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key_id):
        raise MaterialProtocolError("material_key_id_invalid")
    if type(timestamp) is not int or not 0 <= timestamp <= 999999999999:
        raise MaterialProtocolError("material_timestamp_invalid")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise MaterialProtocolError("material_nonce_invalid")
    if not isinstance(ticket, str) or len(ticket) > 512 or (ticket and not re.fullmatch(r"[A-Za-z0-9._~-]+", ticket)):
        raise MaterialProtocolError("material_ticket_invalid", 401)


def canonical_message(method, target, body, *, delegation_id, key_id, pod_uid, timestamp, nonce, ticket=""):
    _shape(method, target, body)
    _identity(delegation_id, key_id, pod_uid, timestamp, nonce, ticket)
    path, _, query = target.partition("?")
    if (path.endswith("/exchange") and ticket) or (not path.endswith("/exchange") and not ticket):
        raise MaterialProtocolError("material_ticket_scope_invalid", 401)
    return "\n".join(
        [
            "BISHENG-RUNTIME-MATERIAL-V1",
            delegation_id,
            key_id,
            pod_uid,
            str(timestamp),
            nonce,
            method,
            path,
            query,
            hashlib.sha256(body).hexdigest(),
            hashlib.sha256(ticket.encode()).hexdigest(),
        ]
    ).encode("utf-8")


def signed_headers(
    method, target, body, *, private_key, delegation_id, key_id, pod_uid, timestamp=None, nonce=None, ticket=""
):
    timestamp = int(time.time()) if timestamp is None else timestamp
    nonce = secrets.token_hex(16) if nonce is None else nonce
    raw = canonical_message(
        method,
        target,
        body,
        delegation_id=delegation_id,
        key_id=key_id,
        pod_uid=pod_uid,
        timestamp=timestamp,
        nonce=nonce,
        ticket=ticket,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise MaterialProtocolError("material_signer_invalid")
    result = {
        "X-Material-Delegation": delegation_id,
        "X-Material-Key-Id": key_id,
        "X-Material-Pod-Uid": pod_uid,
        "X-Material-Timestamp": str(timestamp),
        "X-Material-Nonce": nonce,
        "X-Material-Content-Sha256": hashlib.sha256(body).hexdigest(),
        "X-Material-Signature": private_key.sign(raw).hex(),
    }
    if ticket:
        result["X-Material-Ticket"] = ticket
    return result


def authentication_headers(headers):
    result = {}
    pairs = headers.raw if hasattr(headers, "raw") else (headers.items() if hasattr(headers, "items") else headers)
    try:
        for name, value in pairs:
            name = name.decode("ascii") if isinstance(name, bytes) else name
            value = value.decode("ascii") if isinstance(value, bytes) else value
            if not isinstance(name, str) or not isinstance(value, str):
                raise MaterialProtocolError("material_header_invalid")
            lower = name.lower()
            if lower.startswith("x-runtime-") or lower == "authorization":
                raise MaterialProtocolError("material_mixed_identity_refused")
            if not lower.startswith("x-material-"):
                continue
            key = lower[len("x-material-") :]
            if (
                key not in _FIELDS
                or key in result
                or not value.isascii()
                or value != value.strip()
                or any(c in value for c in "\r\n\x00")
            ):
                raise MaterialProtocolError("material_header_ambiguous")
            result[key] = value
    except (UnicodeError, TypeError, ValueError) as exc:
        if isinstance(exc, MaterialProtocolError):
            raise
        raise MaterialProtocolError("material_header_invalid") from None
    return result


def _public_key(value):
    if isinstance(value, Ed25519PublicKey):
        return value
    try:
        if isinstance(value, str):
            if not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError()
            value = bytes.fromhex(value)
        return Ed25519PublicKey.from_public_bytes(value)
    except (TypeError, ValueError):
        raise MaterialProtocolError("material_public_key_invalid", 401) from None


def verify_request(method, target, body, headers, *, public_key, now=None):
    values = authentication_headers(headers)
    required = _FIELDS - ({"ticket"} if target.partition("?")[0] == PREFIX + "/exchange" else set())
    if set(values) != required:
        raise MaterialProtocolError("material_headers_incomplete")
    timestamp = values["timestamp"]
    if not re.fullmatch(r"0|[1-9][0-9]{0,11}", timestamp):
        raise MaterialProtocolError("material_timestamp_invalid")
    proof = MaterialProof(
        values["delegation"],
        values["key-id"],
        values["pod-uid"],
        int(timestamp),
        values["nonce"],
        values["content-sha256"],
        values.get("ticket", ""),
    )
    raw = canonical_message(
        method,
        target,
        body,
        delegation_id=proof.delegation_id,
        key_id=proof.key_id,
        pod_uid=proof.pod_uid,
        timestamp=proof.timestamp,
        nonce=proof.nonce,
        ticket=proof.ticket,
    )
    if abs((time.time() if now is None else now) - proof.timestamp) >= 60:
        raise MaterialProtocolError("material_signature_expired", 401)
    if not re.fullmatch(r"[a-f0-9]{64}", proof.content_sha256) or not hmac.compare_digest(
        proof.content_sha256, hashlib.sha256(body).hexdigest()
    ):
        raise MaterialProtocolError("material_body_digest_refused", 401)
    if not re.fullmatch(r"[a-f0-9]{128}", values["signature"]):
        raise MaterialProtocolError("material_signature_invalid", 401)
    try:
        _public_key(public_key).verify(bytes.fromhex(values["signature"]), raw)
    except InvalidSignature:
        raise MaterialProtocolError("material_signature_refused", 401) from None
    return proof


def _unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise MaterialProtocolError("material_json_duplicate_field")
        result[key] = value
    return result


def _invalid_constant(_):
    raise MaterialProtocolError("material_json_number_invalid")


def _finite_float(raw):
    value = float(raw)
    if not math.isfinite(value):
        raise MaterialProtocolError("material_json_number_invalid")
    return value


def parse_control(raw: bytes, *, allowed, required=()):
    if not isinstance(raw, bytes):
        raise MaterialProtocolError("material_body_invalid")
    if len(raw) > CONTROL_LIMIT:
        raise MaterialProtocolError("material_control_limit", 413)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_invalid_constant, parse_float=_finite_float
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, MaterialProtocolError):
            raise
        raise MaterialProtocolError("material_json_invalid") from None
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise MaterialProtocolError("material_json_fields_invalid")
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in item):
            raise MaterialProtocolError("material_json_unicode_invalid")
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


async def authenticate(method, target, body, headers, *, public_key, authorize, consume_nonce, now=None):
    proof = verify_request(method, target, body, headers, public_key=public_key, now=now)
    scope = await authorize(proof)
    try:
        accepted = await consume_nonce(f"runtime:material:v1:{proof.delegation_id}:{proof.nonce}", 120)
    except Exception as exc:
        logger.warning("material nonce unavailable (%s)", type(exc).__name__)
        raise MaterialProtocolError("material_authorization_unavailable", 503) from None
    if not accepted:
        raise MaterialProtocolError("material_nonce_replayed", 409)
    return proof, scope
