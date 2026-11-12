"""Small verified MinIO objects for the offline F118 baseline and plan.

The inventory owner supplies closed, secret-free records. This adapter verifies
their canonical envelope and immutable object identity; it grants no migration
authority and never changes a SQL phase. Large inventories consist of pages.
"""

import hashlib
import json
import re
from collections.abc import Mapping

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError

_KINDS = frozenset(
    {"baseline", "plan", "permission_catalog", "permission_resources", "sources", "conversion", "verification"}
)
_MAX_BYTES = 16 * 1024 * 1024


def _reject():
    raise KnowledgeOperationPlanConflictError(reason="migration_artifact_invalid")


def _scope(run_id, kind):
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", run_id) is None
        or not isinstance(kind, str)
        or kind not in _KINDS
    ):
        _reject()


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate artifact key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite artifact value")


def _canonical(content, run_id, kind):
    if type(content) is not bytes or not content or len(content) > _MAX_BYTES:
        _reject()
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "run_id", "kind", "records"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["run_id"] != run_id
            or value["kind"] != kind
            or not isinstance(value["records"], list)
            or json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            != content
        ):
            _reject()
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise KnowledgeOperationPlanConflictError(reason="migration_artifact_invalid") from error


def _key(run_id, kind, digest):
    return f"f118/unification/{run_id}/{kind}/{digest}.json"


class UnificationArtifactStore:
    def __init__(self, storage):
        bucket = getattr(storage, "bucket", None)
        if (
            not isinstance(bucket, str)
            or not bucket
            or bucket == getattr(storage, "tmp_bucket", None)
            or any(not callable(getattr(storage, name, None)) for name in ("object_exists", "put_object", "get_object"))
        ):
            _reject()
        self.storage = storage
        self.bucket = bucket

    async def _read_verified(self, descriptor, run_id, kind):
        try:
            data = await self.storage.get_object(bucket_name=self.bucket, object_name=descriptor["object_key"])
            if type(data) is not bytes or hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
                raise ReferenceCoverageNotReadyError(reason="migration_artifact_changed_or_missing")
            try:
                _canonical(data, run_id, kind)
            except KnowledgeOperationPlanConflictError as error:
                raise ReferenceCoverageNotReadyError(reason="migration_artifact_changed_or_missing") from error
            return data
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="migration_artifact_io_failed") from error

    async def aput_canonical(self, *, run_id, kind, content: bytes) -> dict:
        _scope(run_id, kind)
        _canonical(content, run_id, kind)
        digest = hashlib.sha256(content).hexdigest()
        descriptor = {"object_key": _key(run_id, kind, digest), "sha256": digest}
        try:
            exists = await self.storage.object_exists(bucket_name=self.bucket, object_name=descriptor["object_key"])
            if type(exists) is not bool:
                raise ReferenceCoverageNotReadyError(reason="migration_artifact_io_failed")
            if not exists:
                await self.storage.put_object(
                    bucket_name=self.bucket,
                    object_name=descriptor["object_key"],
                    file=content,
                    content_type="application/json",
                )
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="migration_artifact_io_failed") from error
        await self._read_verified(descriptor, run_id, kind)
        return descriptor

    async def aload_canonical(self, descriptor, *, run_id, kind) -> bytes:
        _scope(run_id, kind)
        if (
            not isinstance(descriptor, Mapping)
            or set(descriptor) != {"object_key", "sha256"}
            or not isinstance(descriptor["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"]) is None
            or descriptor["object_key"] != _key(run_id, kind, descriptor["sha256"])
        ):
            _reject()
        return await self._read_verified(dict(descriptor), run_id, kind)
