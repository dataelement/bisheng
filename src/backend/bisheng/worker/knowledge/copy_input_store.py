"""Durable per-file recovery inputs in object storage, with bounded local cache."""

import hashlib
import json
import re
from contextlib import contextmanager
from tempfile import SpooledTemporaryFile

from bisheng.core.context.tenant import get_current_tenant_id


def input_identity(job_id, snapshot):
    if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id) is None:
        raise ValueError("invalid copy job identity")
    identity = {
        "tenant_id": get_current_tenant_id(),
        "job_id": job_id,
        "space_id": snapshot["destination"]["id"],
        "file_id": snapshot["target_file"]["id"],
        "version_id": snapshot["target_version"]["id"],
    }
    if any(
        type(identity[key]) is not int or identity[key] <= 0
        for key in ("tenant_id", "space_id", "file_id", "version_id")
    ):
        raise ValueError("copy recovery input requires a concrete tenant and target")
    return identity


def input_key(identity, digest):
    return f"knowledge/copy-inputs/{identity['tenant_id']}/{identity['space_id']}/{identity['file_id']}/{identity['job_id']}/{digest}.jsonl"


def validate_input_key(value, *, job_id, snapshot):
    identity = input_identity(job_id, snapshot)
    if not isinstance(value, dict) or set(value) != {"key", "sha256", "bytes", "count"}:
        raise ValueError("copy input descriptor is incomplete")
    if not isinstance(value["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None:
        raise ValueError("invalid copy input digest")
    if value["key"] != input_key(identity, value["sha256"]) or any(
        type(value[name]) is not int or value[name] < 0 for name in ("bytes", "count")
    ):
        raise ValueError("copy input is outside the accepted target")
    return identity


def write_line(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode() + b"\n")


def describe(stream, *, job_id, snapshot, count):
    digest = hashlib.sha256()
    stream.seek(0)
    size = 0
    while block := stream.read(1024 * 1024):
        digest.update(block)
        size += len(block)
    checksum = digest.hexdigest()
    stream.seek(0)
    return {
        "key": input_key(input_identity(job_id, snapshot), checksum),
        "sha256": checksum,
        "bytes": size,
        "count": count,
    }


@contextmanager
def read_input(storage, value, *, job_id, snapshot):
    identity = validate_input_key(value, job_id=job_id, snapshot=snapshot)
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024) as cached:
        response = None
        digest, size = hashlib.sha256(), 0
        try:
            if hasattr(storage.minio_client_sync, "get_object"):
                response = storage.minio_client_sync.get_object(storage.bucket, value["key"])
                while block := response.read(1024 * 1024):
                    cached.write(block)
                    digest.update(block)
                    size += len(block)
            else:
                # The storage facade also supports bytes (used by offline transports).
                block = storage.get_object_sync(object_name=value["key"])
                if block is None:
                    raise ValueError("copy recovery input is missing")
                cached.write(block)
                digest.update(block)
                size = len(block)
        finally:
            if response is not None:
                response.close()
                response.release_conn()
        if size != value["bytes"] or digest.hexdigest() != value["sha256"]:
            raise ValueError("copy recovery input checksum differs")
        cached.seek(0)
        header = json.loads(cached.readline())
        if header.get("identity") != identity:
            raise ValueError("copy recovery input target differs")
        yield header, cached


def input_pages(stream, *, size=200):
    page = []
    for line in stream:
        page.append(json.loads(line))
        if len(page) == size:
            yield page
            page = []
    if page:
        yield page
