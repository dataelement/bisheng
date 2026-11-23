"""T208 real worker failure/retry acceptance; opt-in and serial, never fake ready.

Requires F118's explicit private environment plus a separately authorized local
SSH-forwarded mock endpoint in F118_E2E_MOCK_CONTROL_BASE. Collection is offline.
The tests never reset shared counters, mutate leases or replace an Owner.
"""

import json
import os
from uuid import uuid4

import pytest

from test.e2e.helpers.f118_processing_recovery import (
    chunks,
    embedding_counts,
    job_view,
    partial_job,
    wait_job,
)
from test.e2e.helpers.f118_processing_recovery import recovery_target as recovery_target

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(os.environ.get("F118_E2E") != "1", reason="requires upgraded isolated F118 and explicit opt-in"),
]


async def test_ac49_ac50_real_partial_failure_retries_only_failed_item_and_replays_same_key(recovery_target):
    """AC-49/50: a real once-only embedding failure is visible, and only its failed item is retried."""
    target, control = recovery_target
    try:
        partial = await partial_job(target, control, "rules")
        sid, job_id = partial.space_id, partial.job["id"]
        success_chunks = await chunks(target, sid, partial.successful_file)
        # Names/descriptions are not a model/index revision and must not make
        # this failed job obsolete. Both names are in the cleanup allowlist.
        await target.ok(
            "PUT",
            f"/knowledge/space/{sid}",
            json={"name": target.name("versions"), "description": "F118 recovery metadata-only change"},
        )
        renamed = await target.info(sid)
        assert renamed["name"] == target.name("versions")
        assert renamed["description"] == "F118 recovery metadata-only change"
        unchanged, _ = await job_view(target, sid, job_id)
        assert unchanged["state"] == "partial_failed" and unchanged["revision"] == partial.job["revision"]
        request = {"expected_job_revision": partial.job["revision"], "idempotency_key": uuid4().hex}
        path = f"/knowledge/space/{sid}/processing-jobs/{job_id}/retry"
        accepted = await target.ok("POST", path, params={"kind": "file_resplit"}, json=request)
        assert accepted["accepted"] is True and accepted["job_id"] == job_id
        finished, items = await wait_job(target, sid, job_id, "succeeded")
        assert finished["succeeded_count"] == 2 and finished["failed_count"] == finished["pending_count"] == 0
        assert items[partial.successful_file] == partial.items[partial.successful_file]
        assert items[partial.failed_file]["id"] == partial.items[partial.failed_file]["id"]
        assert items[partial.failed_file]["attempt"] == partial.items[partial.failed_file]["attempt"] + 1
        assert items[partial.failed_file]["state"] == "succeeded" and items[partial.failed_file]["error_code"] is None
        after = embedding_counts(await control.stats(), partial.model)
        assert all(after[key] == partial.counters[key] for key in partial.successful_inputs)
        assert (await chunks(target, sid, partial.successful_file)) == success_chunks
        failed_chunks = await chunks(target, sid, partial.failed_file)
        assert failed_chunks["total"] > 0 and partial.marker in json.dumps(failed_chunks["data"], ensure_ascii=False)
        assert (await target.file(sid, partial.failed_file))["status"] == 2
        counters = await control.stats()
        replay = await target.ok("POST", path, params={"kind": "file_resplit"}, json=request)
        assert replay["job_id"] == job_id and replay["reused"] is True
        replayed, replay_items = await job_view(target, sid, job_id)
        assert replayed == finished and replay_items == items
        replay_counts = embedding_counts(await control.stats(), partial.model)
        original_counts = embedding_counts(counters, partial.model)
        assert all(replay_counts[key] == original_counts[key] for key in partial.owned_inputs)
    finally:
        await control.release_own_rule()


async def test_ac49_ac50_old_failed_job_becomes_durably_obsolete_after_actual_model_cutover(recovery_target):
    """AC-49/50: actual embedding/index cutover makes the old failed job obsolete, with old results readable."""
    target, control = recovery_target
    try:
        partial = await partial_job(target, control, "four-kinds")
        sid, job_id = partial.space_id, partial.job["id"]
        source = await target.info(sid)
        assert str(source["model"]) == str(target.embedding(0)["id"])
        await target.processing(sid, "embedding_rebuild", {"embedding_model_id": target.embedding(1)["id"]})
        cutover = await target.info(sid)
        assert cutover["id"] == sid and str(cutover["model"]) == str(target.embedding(1)["id"])
        preserved = await chunks(target, sid, partial.successful_file)
        assert preserved["total"] > 0
        before_retry = await control.stats()
        request = {"expected_job_revision": partial.job["revision"], "idempotency_key": uuid4().hex}
        path = f"/knowledge/space/{sid}/processing-jobs/{job_id}/retry"
        await target.error("POST", path, 10997, params={"kind": "file_resplit"}, json=request)
        obsolete, items = await job_view(target, sid, job_id)
        assert obsolete["state"] == "obsolete" and obsolete["retryable"] is False
        assert obsolete["error_code"] == 10997 and obsolete["obsolete_reason"] == "model_config_revision_changed"
        for file_id, previous in partial.items.items():
            assert {key: value for key, value in items[file_id].items() if key != "retryable"} == {
                key: value for key, value in previous.items() if key != "retryable"
            }
            assert items[file_id]["retryable"] is False
        assert (await chunks(target, sid, partial.successful_file)) == preserved
        await target.error("POST", path, 10997, params={"kind": "file_resplit"}, json=request)
        repeated, repeated_items = await job_view(target, sid, job_id)
        assert repeated == obsolete and repeated_items == items
        after_retry = await control.stats()
        for model in target.model_fixture["embedding_model_names"]:
            before_counts, after_counts = embedding_counts(before_retry, model), embedding_counts(after_retry, model)
            assert all(after_counts.get(key) == before_counts.get(key) for key in partial.owned_inputs)
    finally:
        await control.release_own_rule()
