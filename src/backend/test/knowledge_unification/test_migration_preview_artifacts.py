"""Real canonical scratch pages never publish objects or outlive a dry-run."""

import asyncio
import hashlib
import json
from stat import S_IMODE
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_preview_artifacts import preview_artifact_store


def content(kind="baseline"):
    return json.dumps(
        {"schema_version": 1, "run_id": "preview", "kind": kind, "records": []},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def original_store(payload=None):
    storage = SimpleNamespace(
        bucket="artifacts",
        tmp_bucket="temporary",
        object_exists=AsyncMock(side_effect=AssertionError("preview must not probe persistent output objects")),
        put_object=AsyncMock(side_effect=AssertionError("preview must not publish persistent pages")),
        get_object=AsyncMock(return_value=payload),
    )
    return UnificationArtifactStore(storage)


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_private_preview_pages_are_verified_and_removed_on_every_exit(failure):
    original = original_store()
    try:
        with preview_artifact_store(original) as store:
            directory = store.storage.directory
            assert S_IMODE(directory.stat().st_mode) == 0o700
            descriptor = await store.aput_canonical(run_id="preview", kind="baseline", content=content())
            assert await store.aload_canonical(descriptor, run_id="preview", kind="baseline") == content()
            assert len(list(directory.iterdir())) == 1
            assert all(S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())
            if failure is not None:
                raise failure("preflight interrupted")
    except BaseException as error:
        assert failure is not None and isinstance(error, failure)
    else:
        assert failure is None
    assert not directory.exists()
    original.storage.object_exists.assert_not_awaited()
    original.storage.put_object.assert_not_awaited()
    original.storage.get_object.assert_not_awaited()


async def test_corrupt_scratch_page_still_fails_original_immutable_hash_check():
    original = original_store()
    with preview_artifact_store(original) as store:
        descriptor = await store.aput_canonical(run_id="preview", kind="baseline", content=content())
        next(store.storage.directory.iterdir()).write_bytes(b"changed")
        with pytest.raises(ReferenceCoverageNotReadyError) as caught:
            await store.aload_canonical(descriptor, run_id="preview", kind="baseline")
        assert caught.value.kwargs["reason"] == "migration_artifact_changed_or_missing"
    original.storage.put_object.assert_not_awaited()


async def test_existing_material_is_read_only_through_original_verified_adapter():
    payload = content("verification")
    digest = hashlib.sha256(payload).hexdigest()
    descriptor = {"object_key": f"f118/unification/preview/verification/{digest}.json", "sha256": digest}
    original = original_store(payload)
    with preview_artifact_store(original) as store:
        assert await store.aload_canonical(descriptor, run_id="preview", kind="verification") == payload
        assert not list(store.storage.directory.iterdir())
    original.storage.get_object.assert_awaited_once()
    original.storage.object_exists.assert_not_awaited()
    original.storage.put_object.assert_not_awaited()
