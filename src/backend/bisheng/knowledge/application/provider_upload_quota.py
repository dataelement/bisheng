"""Single-pass provider upload. No native paths, temporary files or queue jobs."""

import re
from dataclasses import dataclass
from hashlib import sha256

from bisheng.knowledge.domain.repositories.provider_upload_quota_repository import ProviderUploadQuota, QuotaExceeded

__all__ = [
    "ProviderUploadQuota",
    "QuotaExceeded",
    "UploadIdentity",
    "UploadReceipt",
    "UploadResult",
    "forward_provider_stream",
]


@dataclass(frozen=True, slots=True)
class UploadIdentity:
    tenant_id: int
    user_id: int
    space_id: int
    generation: int
    instance_id: int
    remote_scope_id: str
    remote_kb_id: str
    request_key: str
    operation_id: str
    file_id: int
    document_id: int
    version_id: int
    byte_count: int
    sha256: str
    operation_epoch: int = 1

    def __post_init__(self):
        if (
            type(self.byte_count) is not int
            or not 0 <= self.byte_count < 2**63
            or not re.fullmatch("[0-9a-f]{64}", self.sha256)
        ):
            raise ValueError("invalid byte commitment")


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    """An adapter must parse provider-issued facts, not echo request fields.

    not_received is final, fenced proof for this attempt; a plain 404 or a
    duplicate-content response from an older provider is NOT such proof.
    """

    identity: UploadIdentity
    state: str
    remote_id: str | None


@dataclass(frozen=True, slots=True)
class UploadResult:
    state: str
    remote_id: str | None = None


def validate_chunking(options):
    if options is None:
        return None
    if (
        type(options) is not dict
        or options.keys() - {"chunk_size", "chunk_overlap"}
        or any(type(v) is not int for v in options.values())
    ):
        raise ValueError("unsupported chunking options")
    if (
        ("chunk_size" in options and options["chunk_size"] <= 0)
        or options.get("chunk_overlap", 0) < 0
        or ("chunk_size" in options and options.get("chunk_overlap", 0) >= options["chunk_size"])
    ):
        raise ValueError("invalid chunking limits")
    return options.copy()


def interpret_receipt(identity, receipt):
    if receipt is None:
        return UploadResult("unknown")
    if not isinstance(receipt, UploadReceipt) or receipt.identity != identity:
        return UploadResult("conflict")
    if (
        receipt.state == "accepted"
        and isinstance(receipt.remote_id, str)
        and 0 < len(receipt.remote_id.encode()) <= 255
    ):
        return UploadResult("accepted", receipt.remote_id)
    if receipt.state == "not_received" and receipt.remote_id is None:
        return UploadResult("reupload_required")
    return UploadResult("conflict")


async def reconcile_provider_stream(identity, lookup):
    try:
        receipt = await lookup(identity=identity)
    except (TimeoutError, ConnectionError):
        return UploadResult("unknown")
    return interpret_receipt(identity, receipt)


class StreamMismatch(ValueError):
    pass


async def forward_provider_stream(identity, source, chunking, send, lookup):
    options = validate_chunking(chunking)
    complete = False

    async def measured():
        nonlocal complete
        digest = sha256()
        total = 0
        async for chunk in source:
            if not isinstance(chunk, bytes) or len(chunk) > identity.byte_count - total:
                raise StreamMismatch("stream exceeds reservation")
            total += len(chunk)
            digest.update(chunk)
            yield chunk
        if total != identity.byte_count or digest.hexdigest() != identity.sha256:
            raise StreamMismatch("stream does not match commitment")
        complete = True

    try:
        receipt = await send(identity=identity, chunks=measured(), chunking=options)
    except (ConnectionError, TimeoutError, StreamMismatch):
        return await reconcile_provider_stream(identity, lookup)
    result = interpret_receipt(identity, receipt)
    if result.state == "accepted" and not complete:
        return UploadResult("conflict")
    return result
