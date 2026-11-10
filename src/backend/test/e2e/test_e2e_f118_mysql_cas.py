"""T202 / TC-KSU-113,120: actual MySQL 8 CAS through normal WF HTTP writers.

Explicit F118_E2E=1 and the existing isolated environment/private fixtures are
required, plus F118_E2E_MYSQL_FIXTURE_FILE. No live I/O during collection. Unlike
an unavailable environment skip, missing lock observation fails with evidence.
Run serially; this leaf owns an independent mysql-cas Child/prefix. No FGA fault
injection, source SQL mutation, product pause hooks or worker-I/O race platform.
"""

import json
import os

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.f118_mysql_cas import CasEnvironment, MysqlFixture, assert_snapshot, graph, race

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def target():
    if os.environ.get("F118_E2E") != "1":
        raise RuntimeError("explicit F118_E2E=1 is required; no API/database requests were sent")
    async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as client:
        environment = CasEnvironment.from_environment(client)
        mysql = MysqlFixture.from_environment()
        version = await mysql.preflight()
        try:
            await environment.prepare_cas()
            yield environment, mysql, version
        finally:
            await environment.cleanup()


async def read_versions(target, flow_id, expected):
    for version, data in expected.items():
        current = await target.ok("GET", f"/workflow/versions/{version}", actor=target.writer)
        assert current["flow_id"] == flow_id and current["data"] == data
    root = await target.ok("GET", f"/workflow/get_one_flow/{flow_id}", actor=target.writer)
    assert root["tenant_id"] == target.tenant_id and root["user_id"] == target.reader_id
    versions = [await target.ok("GET", f"/workflow/versions/{version}", actor=target.writer) for version in expected]
    current = [version for version in versions if version["is_current"]]
    assert len(current) == 1 and root["data"] == expected[current[0]["id"]]


class TestF118MysqlCas:
    async def test_same_version_has_one_winner_and_no_partial_binding(self, target, record_property):
        """AC-83/89: one server CAS winner, ordinary nonowner denied, business/R2 atomically agree."""
        env, mysql, mysql_version = target
        t, a, b = [row["id"] for row in env.spaces]
        workflow = await env.create_workflow("wf-same")
        flow_id, version = workflow["id"], workflow["version_id"]
        await env.ok("PUT", f"/workflow/versions/{version}", actor=env.writer, json={"data": graph(t)})
        before = await mysql.snapshot(env.tenant_id, flow_id, (version,))
        assert_snapshot(before, {version: graph(t)}, tenant=env.tenant_id, owner=env.reader_id)
        denied = {**env.outsider, "X-Management-Tenant": str(env.tenant_id)}
        await env.error("PUT", f"/workflow/versions/{version}", 19000, actor=denied, json={"data": graph(t, b)})
        assert await mysql.snapshot(env.tenant_id, flow_id, (version,)) == before

        candidates = (graph(t, a), graph(t, b))
        responses, waits = await race(env, mysql, flow_id, (version, version), candidates)
        bodies = [response.json() for response in responses]
        after = await mysql.snapshot(env.tenant_id, flow_id, (version,))
        record_property(
            "mysql_cas_observed",
            json.dumps(
                {
                    "case": "same_version",
                    "flow_id": flow_id,
                    "tenant": env.tenant_id,
                    "responses": bodies,
                    "waiters": waits,
                    "before": before,
                    "after": after,
                },
                default=str,
            ),
        )
        assert all(response.status_code == 200 for response in responses)
        assert sorted(body["status_code"] for body in bodies) == [200, 10998]
        winner = next(index for index, body in enumerate(bodies) if body["status_code"] == 200)
        loser = bodies[1 - winner]
        assert loser["data"]["reason"] == "workflow_version_changed"
        assert_snapshot(after, {version: candidates[winner]}, tenant=env.tenant_id, owner=env.reader_id)
        assert after["sets"][str(version)]["source_revision"] == before["sets"][str(version)]["source_revision"] + 1
        assert after["sets"]["__root__"]["source_revision"] == before["sets"]["__root__"]["source_revision"] + 1
        await read_versions(env, flow_id, {version: candidates[winner]})
        record_property(
            "mysql_cas_evidence",
            json.dumps(
                {
                    "case": "same_version",
                    "mysql": mysql_version,
                    "flow_id": flow_id,
                    "versions": [version],
                    "tenant": env.tenant_id,
                    "waiters": waits,
                    "winner": winner,
                    "before": before,
                    "after": after,
                },
                default=str,
            ),
        )

    async def test_different_versions_share_root_cas_then_retry_independently(self, target, record_property):
        """AC-83/89: shared root CAS prevents stale parallel versions; fresh retry retains both complete sources."""
        env, mysql, mysql_version = target
        t, a, b = [row["id"] for row in env.spaces]
        workflow = await env.create_workflow("wf-versions")
        flow_id, v0 = workflow["id"], workflow["version_id"]
        await env.ok("PUT", f"/workflow/versions/{v0}", actor=env.writer, json={"data": graph(t)})
        created = await env.ok(
            "POST",
            "/workflow/versions",
            actor=env.writer,
            params={"flow_id": flow_id},
            json={"name": env.prefix + "retained-v1", "data": graph(t)},
        )
        v1 = created["id"]
        assert created["flow_id"] == flow_id and created["user_id"] == env.reader_id and not created["is_current"]
        versions, candidates = (v0, v1), (graph(t, a), graph(t, b))
        before = await mysql.snapshot(env.tenant_id, flow_id, versions)
        assert_snapshot(before, {v0: graph(t), v1: graph(t)}, tenant=env.tenant_id, owner=env.reader_id)
        denied = {**env.outsider, "X-Management-Tenant": str(env.tenant_id)}
        await env.error("PUT", f"/workflow/versions/{v1}", 19000, actor=denied, json={"data": graph(t, b)})
        assert await mysql.snapshot(env.tenant_id, flow_id, versions) == before
        responses, waits = await race(env, mysql, flow_id, versions, candidates)
        bodies = [response.json() for response in responses]
        partial = await mysql.snapshot(env.tenant_id, flow_id, versions)
        record_property(
            "mysql_cas_observed",
            json.dumps(
                {
                    "case": "different_versions",
                    "flow_id": flow_id,
                    "tenant": env.tenant_id,
                    "responses": bodies,
                    "waiters": waits,
                    "before": before,
                    "after": partial,
                },
                default=str,
            ),
        )
        assert all(response.status_code == 200 for response in responses)
        assert sorted(body["status_code"] for body in bodies) == [200, 10998]
        winner = next(index for index, body in enumerate(bodies) if body["status_code"] == 200)
        loser = 1 - winner
        assert bodies[loser]["data"]["reason"] == "reference_lock_plan_changed"
        expected = {
            version: candidates[index] if index == winner else graph(t) for index, version in enumerate(versions)
        }
        assert_snapshot(partial, expected, tenant=env.tenant_id, owner=env.reader_id)
        assert partial["sets"]["__root__"]["source_revision"] == before["sets"]["__root__"]["source_revision"] + 1
        for index, version in enumerate(versions):
            assert partial["sets"][str(version)]["source_revision"] == before["sets"][str(version)][
                "source_revision"
            ] + (index == winner)
        await read_versions(env, flow_id, expected)
        await env.ok("PUT", f"/workflow/versions/{versions[loser]}", actor=env.writer, json={"data": candidates[loser]})
        final = await mysql.snapshot(env.tenant_id, flow_id, versions)
        expected = dict(zip(versions, candidates, strict=True))
        assert_snapshot(final, expected, tenant=env.tenant_id, owner=env.reader_id)
        assert final["sets"]["__root__"]["source_revision"] == before["sets"]["__root__"]["source_revision"] + 2
        assert all(
            final["sets"][str(version)]["source_revision"] == before["sets"][str(version)]["source_revision"] + 1
            for version in versions
        )
        await read_versions(env, flow_id, expected)
        record_property(
            "mysql_cas_evidence",
            json.dumps(
                {
                    "case": "different_versions",
                    "mysql": mysql_version,
                    "flow_id": flow_id,
                    "versions": versions,
                    "tenant": env.tenant_id,
                    "waiters": waits,
                    "winner": winner,
                    "before": before,
                    "partial": partial,
                    "after": final,
                },
                default=str,
            ),
        )
