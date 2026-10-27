"""Public-key-only authorization of one owner action on one observed Pod UID."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"BISHENG-RUNTIME-DATA-V1\n"
ACTIONS = frozenset({"tables", "schema", "rows", "update", "export", "result"})
CLAIMS = frozenset(
    {
        "version",
        "operation_id",
        "request_id",
        "app_id",
        "exec_ref",
        "pod_uid",
        "actor_ref",
        "action",
        "parameters_sha256",
        "nonce",
        "issued_at",
        "not_after",
        "deadline",
    }
)


class DataGrantError(ValueError):
    """A safe machine reason, without ticket, key, or database contents."""


def canonical_json(document):
    try:
        return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, RecursionError):
        raise DataGrantError("data_document_invalid") from None


def parameters_digest(parameters):
    if not isinstance(parameters, dict):
        raise DataGrantError("data_parameters_invalid")
    raw = canonical_json(parameters)
    if len(raw) > 1024 * 1024:
        raise DataGrantError("data_parameters_size_limit")
    return hashlib.sha256(raw).hexdigest()


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise DataGrantError("data_identity_invalid") from None


def verify_grant(ticket, parameters, public_keys, *, app_id, exec_ref, pod_uid, now):
    if not isinstance(ticket, dict) or set(ticket) != {"key_id", "claims", "signature"}:
        raise DataGrantError("data_grant_fields_invalid")
    key_id, claims = ticket["key_id"], ticket["claims"]
    if not isinstance(key_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key_id) or key_id not in public_keys:
        raise DataGrantError("data_grant_key_unknown")
    if not isinstance(claims, dict) or set(claims) != CLAIMS:
        raise DataGrantError("data_grant_claims_invalid")
    try:
        signature = ticket["signature"]
        if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{128}", signature):
            raise ValueError()
        key = public_keys[key_id]
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError()
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(
            bytes.fromhex(signature), DOMAIN + canonical_json({"key_id": key_id, "claims": claims})
        )
    except (ValueError, TypeError, InvalidSignature):
        raise DataGrantError("data_grant_signature_invalid") from None
    if (
        type(claims["version"]) is not int
        or claims["version"] != 1
        or not isinstance(claims["action"], str)
        or claims["action"] not in ACTIONS
    ):
        raise DataGrantError("data_grant_action_refused")
    for key in ("request_id", "exec_ref", "pod_uid", "nonce"):
        _uuid(claims[key])
    for key in ("operation_id", "app_id", "actor_ref"):
        if (
            not isinstance(claims[key], str)
            or not 1 <= len(claims[key]) <= 80
            or any(c in claims[key] for c in "\r\n\x00")
        ):
            raise DataGrantError("data_grant_identity_invalid")
    if (claims["app_id"], claims["exec_ref"], claims["pod_uid"]) != (app_id, exec_ref, pod_uid):
        raise DataGrantError("data_grant_scope_refused")
    if claims["parameters_sha256"] != parameters_digest(parameters):
        raise DataGrantError("data_grant_parameters_changed")
    issued, expiry, deadline = (claims[key] for key in ("issued_at", "not_after", "deadline"))
    if any(type(value) is not int for value in (issued, expiry, deadline)) or not (
        0 <= issued <= now < expiry <= issued + 5 and now < deadline <= issued + 60 and expiry <= deadline
    ):
        raise DataGrantError("data_grant_expired_or_deadline_invalid")
    return dict(claims)
