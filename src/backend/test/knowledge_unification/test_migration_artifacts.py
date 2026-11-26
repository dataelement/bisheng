"""T688: verified immutable objects precede every SQL baseline freeze."""

import hashlib
import json

import pytest

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
)
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore


def content(*, run_id="e2e-f118-run", kind="baseline", records=None):
    return json.dumps(
        {
            "schema_version": 1,
            "run_id": run_id,
            "kind": kind,
            "records": records if records is not None else [{"id": 7, "name": "样本"}],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def descriptor(value, *, run_id="e2e-f118-run", kind="baseline"):
    digest = hashlib.sha256(value).hexdigest()
    return {"object_key": f"f118/unification/{run_id}/{kind}/{digest}.json", "sha256": digest}


class ObjectIO:
    """Replace only the existing three async MinIO transport methods."""

    bucket = "bisheng"
    tmp_bucket = "tmp-dir"

    def __init__(self):
        self.objects = {}
        self.calls = []
        self.put_error = None
        self.read_corruption = None

    async def object_exists(self, *, bucket_name, object_name):
        self.calls.append(("exists", bucket_name, object_name))
        return object_name in self.objects

    async def put_object(self, *, bucket_name, object_name, file, content_type):
        self.calls.append(("put", bucket_name, object_name, content_type))
        if self.put_error:
            raise self.put_error
        assert type(file) is bytes
        self.objects[object_name] = file
        return None  # The real MinioStorage method does not return a hash.

    async def get_object(self, *, bucket_name, object_name):
        self.calls.append(("get", bucket_name, object_name))
        if self.read_corruption is not None:
            return self.read_corruption
        return self.objects.get(object_name)


@pytest.mark.parametrize("records", [[], [{"id": 7, "name": "样本"}]])
async def test_put_reads_back_actual_canonical_utf8_bytes_before_returning_descriptor(records):
    io = ObjectIO()
    store = UnificationArtifactStore(io)
    value = content(records=records)
    result = await store.aput_canonical(run_id="e2e-f118-run", kind="baseline", content=value)
    assert result == descriptor(value)
    assert [call[0] for call in io.calls] == ["exists", "put", "get"]
    assert all(call[1] == "bisheng" for call in io.calls)
    assert io.calls[1][-1] == "application/json"
    assert await store.aload_canonical(result, run_id="e2e-f118-run", kind="baseline") == value


async def test_existing_verified_content_is_idempotent_without_overwriting_evidence():
    io = ObjectIO()
    value = content()
    ref = descriptor(value)
    io.objects[ref["object_key"]] = value
    result = await UnificationArtifactStore(io).aput_canonical(run_id="e2e-f118-run", kind="baseline", content=value)
    assert result == ref
    assert [call[0] for call in io.calls] == ["exists", "get"]


@pytest.mark.parametrize("existing", [False, True])
async def test_corrupt_readback_never_returns_a_freezable_descriptor_or_overwrites_old_object(existing):
    io = ObjectIO()
    value = content()
    ref = descriptor(value)
    if existing:
        io.objects[ref["object_key"]] = b"old damaged evidence"
    io.read_corruption = content(records=[{"id": 8}])
    with pytest.raises(ReferenceCoverageNotReadyError):
        await UnificationArtifactStore(io).aput_canonical(run_id="e2e-f118-run", kind="baseline", content=value)
    assert sum(call[0] == "put" for call in io.calls) == (0 if existing else 1)
    if existing:
        assert io.objects[ref["object_key"]] == b"old damaged evidence"


@pytest.mark.parametrize("corrupt", [None, b"", b"not JSON", content(records=[{"id": 99}])])
async def test_read_missing_or_changed_bytes_fails_closed(corrupt):
    io = ObjectIO()
    ref = descriptor(content())
    if corrupt is not None:
        io.objects[ref["object_key"]] = corrupt
    with pytest.raises(ReferenceCoverageNotReadyError):
        await UnificationArtifactStore(io).aload_canonical(ref, run_id="e2e-f118-run", kind="baseline")


@pytest.mark.parametrize(
    "ref",
    [
        {"object_key": "/tmp/baseline", "sha256": "a" * 64},
        {"object_key": "file:/tmp/baseline", "sha256": "a" * 64},
        {"object_key": "https://storage.invalid/file", "sha256": "a" * 64},
        {"object_key": "f118/unification/../baseline.json", "sha256": "a" * 64},
        {**descriptor(content()), "url": "https://signed.invalid"},
        {**descriptor(content()), "sha256": "A" * 64},
        descriptor(content(), run_id="another-run"),
        descriptor(content(), kind="plan"),
    ],
)
async def test_descriptor_is_exact_and_bound_to_original_run_kind_and_digest_before_io(ref):
    io = ObjectIO()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await UnificationArtifactStore(io).aload_canonical(ref, run_id="e2e-f118-run", kind="baseline")
    assert io.calls == []


@pytest.mark.parametrize(
    "value",
    [
        b"{}",
        b'{"schema_version":1,"schema_version":1}',
        b'{"kind":"baseline","records":[NaN],"run_id":"e2e-f118-run","schema_version":1}',
        json.dumps(json.loads(content()), ensure_ascii=False, indent=2).encode(),
        content(run_id="another-run"),
        content(kind="plan"),
        content().replace(b'"schema_version":1', b'"schema_version":true'),
        content().replace(b'"records":[', b'"raw_config":['),
        bytearray(content()),
        b"x" * (16 * 1024 * 1024 + 1),
    ],
    ids=[
        "empty",
        "duplicate",
        "nonfinite",
        "pretty",
        "other-run",
        "other-kind",
        "bool-version",
        "unexpected-field",
        "mutable",
        "oversize",
    ],
)
async def test_only_bounded_canonical_closed_envelopes_are_uploaded(value):
    io = ObjectIO()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await UnificationArtifactStore(io).aput_canonical(run_id="e2e-f118-run", kind="baseline", content=value)
    assert io.calls == []


@pytest.mark.parametrize("run_id,kind", [("../escape", "baseline"), ("a" * 65, "plan"), ("run", "unknown")])
async def test_invalid_namespace_is_rejected_before_any_io(run_id, kind):
    io = ObjectIO()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await UnificationArtifactStore(io).aput_canonical(run_id=run_id, kind=kind, content=content())
    assert io.calls == []


def test_temporary_lifecycle_bucket_cannot_store_migration_evidence():
    io = ObjectIO()
    io.bucket = io.tmp_bucket
    with pytest.raises(KnowledgeOperationPlanConflictError):
        UnificationArtifactStore(io)


async def test_upload_transport_failure_preserves_cause_without_payload_in_domain_reason():
    io = ObjectIO()
    failure = RuntimeError("transport unavailable")
    io.put_error = failure
    with pytest.raises(ReferenceCoverageNotReadyError) as caught:
        await UnificationArtifactStore(io).aput_canonical(run_id="e2e-f118-run", kind="baseline", content=content())
    assert caught.value.__cause__ is failure
    assert caught.value.kwargs["reason"] == "migration_artifact_io_failed"
    assert [call[0] for call in io.calls] == ["exists", "put"]
