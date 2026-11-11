"""Real F118 worker recovery fixtures and scoped, loopback-only mock control.

No reset endpoint is called. A pending rule is consumed during cleanup only
when its complete value equals the unique rule armed by this fixture.
"""

import asyncio
import ipaddress
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest_asyncio

from test.e2e.helpers.f118_unification import F118Environment, required


class RecoveryEnvironment(F118Environment):
    @property
    def prefix(self):
        return super().prefix + "recovery-"


class MockControl:
    def __init__(self, client):
        base = required("F118_E2E_MOCK_CONTROL_BASE").rstrip("/")
        url = urlsplit(base)
        try:
            loopback = ipaddress.ip_address(url.hostname or "").is_loopback
            port = url.port
        except ValueError as error:
            raise ValueError("mock control requires an explicit loopback IP and port") from error
        if (
            url.scheme != "http"
            or not loopback
            or port is None
            or not 1 <= port <= 65535
            or port == 3005
            or url.path
            or url.query
            or url.fragment
            or url.username is not None
            or url.password is not None
        ):
            raise ValueError("mock control permits only an explicit HTTP loopback IP/port, never port 3005")
        self.client, self.base, self.rule = client, base, None

    async def stats(self):
        response = await self.client.get(self.base + "/__control/stats")
        assert response.status_code == 200
        result = response.json()
        assert isinstance(result["embedding"], list) and "pending_failure" in result
        return result

    async def arm(self, marker, model):
        assert model in {"f118-embed-8", "f118-embed-16"}
        assert (await self.stats())["pending_failure"] is None, "another failure rule is pending; leave it untouched"
        self.rule = {"kind": "embedding", "model": model, "marker": marker}
        response = await self.client.post(self.base + "/__control/fail-next", json=self.rule)
        assert response.status_code == 200 and response.json() == {"status": "ok"}

    async def release_own_rule(self):
        if self.rule is None:
            return
        pending = (await self.stats())["pending_failure"]
        if pending == self.rule:
            # The mock has no marker-scoped disarm. Consume only our rule with
            # a distinct cleanup input, without clearing anyone's counters.
            response = await self.client.post(
                self.base + "/v1/embeddings",
                json={"model": self.rule["model"], "input": [self.rule["marker"] + " cleanup-only"]},
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "f118_mock_error"
            assert (await self.stats())["pending_failure"] is None
        self.rule = None  # Any foreign pending rule is deliberately untouched.


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def recovery_target():
    async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
        control = MockControl(client)  # Validate before any business request.
        environment = RecoveryEnvironment.from_environment(client)
        try:
            await environment.prepare()
            yield environment, control
        finally:
            try:
                await control.release_own_rule()
            finally:
                await environment.cleanup()


def embedding_counts(stats, model):
    return {
        row["input_sha256"]: (row["attempts"], row["failed"]) for row in stats["embedding"] if row["model"] == model
    }


def incremented(before, after, model):
    old, new = embedding_counts(before, model), embedding_counts(after, model)
    return {key for key, counts in new.items() if counts[0] > old.get(key, (0, 0))[0]}


async def job_view(target, space_id, job_id, kind="file_resplit"):
    path = f"/knowledge/space/{space_id}/processing-jobs/{job_id}"
    job = await target.ok("GET", path, params={"kind": kind})
    assert job["space_id"] == space_id and job["kind"] == kind
    items = await target.ok("GET", path + "/items", params={"kind": kind, "page_size": 200})
    assert items["total"] == len(items["data"]) == job["total_count"]
    assert job["hidden_item_count"] == 0
    return job, {row["file_id"]: row for row in items["data"]}


async def wait_job(target, space_id, job_id, expected):
    deadline = time.monotonic() + target.timeout
    while time.monotonic() < deadline:
        job, items = await job_view(target, space_id, job_id)
        if job["state"] in {"succeeded", "partial_failed", "failed", "obsolete"}:
            assert job["state"] == expected, f"worker ended {job['state']} code={job['error_code']}"
            return job, items
        await asyncio.sleep(1)
    raise AssertionError("processing job did not reach its actual worker terminal state")


async def chunks(target, space_id, file_id):
    return await target.ok(
        "GET", "/knowledge/chunk", params={"knowledge_id": space_id, "file_ids": [file_id], "limit": 200}
    )


@dataclass
class PartialJob:
    space_id: int
    job: dict
    items: dict
    successful_file: int
    failed_file: int
    successful_inputs: set
    owned_inputs: set
    model: str
    counters: dict
    marker: str


async def partial_job(target, control, suffix):
    sid = (await target.space(suffix))["id"]
    model = target.model_fixture["embedding_model_names"][0]
    unique = target.prefix + uuid4().hex[:12]
    before_upload = await control.stats()
    first = await target.upload(sid, "success.txt", (unique + " success document").encode())
    first_stats = await control.stats()
    marker = unique + " failing document"
    second = await target.upload(sid, "failure.txt", marker.encode())
    uploaded = await control.stats()
    successful_inputs = incremented(before_upload, first_stats, model) - incremented(first_stats, uploaded, model)
    assert successful_inputs, "the real first upload must have reached this mock embedding model"
    anchors = [
        await target.ok("GET", f"/knowledge/space/{sid}/files/{file['id']}/processing-target")
        for file in (first, second)
    ]
    plan = await target.ok(
        "POST",
        f"/knowledge/space/{sid}/processing-jobs/precheck",
        json={
            "kind": "file_resplit",
            "targets": anchors,
            "parameters": {"overrides": {"document": {"chunk_size": 256, "chunk_overlap": 0}}},
        },
    )
    assert plan["check_complete"] is True and plan["can_execute"] is True
    await control.arm(marker, model)
    accepted = await target.ok("POST", f"/knowledge/space/{sid}/processing-jobs", json=target.confirmation(plan))
    assert accepted["accepted"] is True
    job, items = await wait_job(target, sid, accepted["job_id"], "partial_failed")
    assert job["total_count"] == 2 and job["succeeded_count"] == job["failed_count"] == 1
    assert job["pending_count"] == 0 and job["retryable"] is True
    assert set(items) == {first["id"], second["id"]}
    assert items[first["id"]]["state"] == "succeeded"
    assert items[second["id"]]["state"] == "failed" and items[second["id"]]["error_code"] == 10953
    assert items[second["id"]]["retryable"] is True
    after = await control.stats()
    assert after["pending_failure"] is None
    previous, current = embedding_counts(uploaded, model), embedding_counts(after, model)
    failed_inputs = {key for key, counts in current.items() if counts[1] > previous.get(key, (0, 0))[1]}
    assert failed_inputs and failed_inputs.isdisjoint(successful_inputs)
    assert sum(current[key][1] - previous.get(key, (0, 0))[1] for key in failed_inputs) == 1
    assert all(current[key][0] > previous[key][0] for key in successful_inputs)
    assert (await chunks(target, sid, first["id"]))["total"] > 0
    return PartialJob(
        sid,
        job,
        items,
        first["id"],
        second["id"],
        successful_inputs,
        successful_inputs | failed_inputs,
        model,
        current,
        marker,
    )
