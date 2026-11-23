"""Verify application-issued MinIO GET capabilities before privileged SDK reads.

Browser routes add /object (and sometimes /workspace) to a signed S3 path. Those
routing prefixes are not part of the signature; no other path, host or query
rewriting is permitted. This module performs no network or storage operation.
"""

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

from minio.credentials import Credentials
from minio.signer import presign_v4

from bisheng.core.external.safe_download import same_origin

_AUTH_FIELDS = frozenset(
    {
        "X-Amz-Algorithm",
        "X-Amz-Credential",
        "X-Amz-Date",
        "X-Amz-Expires",
        "X-Amz-SignedHeaders",
        "X-Amz-Signature",
    }
)
_EXTRA_FIELDS = frozenset(
    {
        "versionId",
        "response-cache-control",
        "response-content-disposition",
        "response-content-encoding",
        "response-content-language",
        "response-content-type",
        "response-expires",
    }
)


@dataclass(frozen=True)
class SignedObjectReference:
    bucket: str
    object_name: str
    version_id: str | None = None


def verify_signed_reference(value: str, storage, *, now: datetime | None = None) -> SignedObjectReference:
    """Accept only a live, exact GET presign made with this storage's credentials."""

    def deny():
        raise ValueError("Object download requires a valid unexpired signed reference")

    if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value) or "\\" in value:
        deny()
    parsed = urlsplit(value)
    origin = storage.get_minio_share_host()
    configured = urlsplit(origin)
    if parsed.fragment or parsed.username or parsed.password:
        deny()
    if parsed.netloc or parsed.scheme:
        if not same_origin(value, origin):
            deny()
    elif not parsed.path.startswith("/") or parsed.path.startswith("//"):
        deny()
    path = parsed.path
    if path.startswith("/workspace/"):
        path = path[len("/workspace") :]
    if path.startswith("/object/"):
        path = path[len("/object") :]
    parts = path.lstrip("/").split("/", 1)
    if len(parts) != 2 or parts[0] not in {storage.bucket, storage.tmp_bucket}:
        deny()
    bucket, encoded_key = parts
    key = unquote(encoded_key, errors="strict")
    if (
        not key
        or "\\" in key
        or any(ord(c) < 32 for c in key)
        or any(p in {"", ".", ".."} for p in key.split("/"))
        or quote(key, safe="/-_.~") != encoded_key
    ):
        deny()
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    query = dict(pairs)
    if (
        len(pairs) != len(query)
        or not _AUTH_FIELDS.issubset(query)
        or set(query) - _AUTH_FIELDS - _EXTRA_FIELDS
        or query["X-Amz-Algorithm"] != "AWS4-HMAC-SHA256"
        or query["X-Amz-SignedHeaders"] != "host"
        or not re.fullmatch(r"[0-9a-f]{64}", query["X-Amz-Signature"])
    ):
        deny()
    config = storage.minio_config
    scope = query["X-Amz-Credential"].split("/")
    if (
        len(scope) != 5
        or scope[0] != config.access_key
        or scope[3:] != ["s3", "aws4_request"]
        or not re.fullmatch(r"[a-z0-9-]{1,64}", scope[2])
    ):
        deny()
    try:
        issued = datetime.strptime(query["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        expires = int(query["X-Amz-Expires"])
    except (ValueError, TypeError):
        deny()
    current = now or datetime.now(UTC)
    age = (current - issued).total_seconds()
    if (
        scope[1] != issued.strftime("%Y%m%d")
        or str(expires) != query["X-Amz-Expires"]
        or not 1 <= expires <= 604800
        or age < -60
        or age >= expires
    ):
        deny()
    # Use the shipped SDK's SigV4 canonicalization, not a parallel crypto format.
    # Every extra query value remains signed. Host comes only from configuration.
    extras = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in pairs if k in _EXTRA_FIELDS)
    unsigned = urlsplit(urlunsplit((configured.scheme, configured.netloc, f"/{bucket}/{encoded_key}", extras, "")))
    expected = presign_v4(
        method="GET",
        url=unsigned,
        region=scope[2],
        credentials=Credentials(config.access_key, config.secret_key),
        date=issued,
        expires=expires,
    )
    expected_sig = dict(parse_qsl(expected.query))["X-Amz-Signature"]
    if not hmac.compare_digest(expected_sig, query["X-Amz-Signature"]):
        deny()
    return SignedObjectReference(bucket, key, query.get("versionId"))


def download_signed_reference(value: str, storage):
    """Read exactly the signed object; never translate a missing key to Root."""
    reference = verify_signed_reference(value, storage)
    from bisheng.core.storage.minio.minio_storage import _thaw_s3_error

    try:
        return storage.minio_client_sync.get_object(
            reference.bucket, reference.object_name, version_id=reference.version_id
        )
    except Exception as exc:
        raise _thaw_s3_error(exc)
