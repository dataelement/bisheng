"""Opt-in F054/F056 API handoff against a dedicated, already seeded application.

F056_E2E=1, E2E_API_BASE, F056_E2E_APP_ID, F056_E2E_TENANT_ID,
F056_E2E_TENANT_ADMIN_TOKEN, F056_E2E_USER_TOKEN, F056_E2E_FOREIGN_TENANT_ID.
The tenant admin must not be a global super. The app slug must start e2e-f056-;
seed one model, capability and access record through its real SDK/entry first.
No source records or applications are deleted. Export cleanup cancels only this
suite's jobs; snapshot/expired artifact retention uses the delivered GC.
"""

import asyncio
import csv
import io
import os
import time
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.skipif(
    os.getenv("F056_E2E") != "1", reason="requires deployed closeout and dedicated seeded e2e-f056 application"
)


@pytest.fixture
async def runtime_records():
    app_id = os.environ["F056_E2E_APP_ID"]
    tenant_id = int(os.environ["F056_E2E_TENANT_ID"])
    admin = auth_headers(os.environ["F056_E2E_TENANT_ADMIN_TOKEN"])
    ordinary = auth_headers(os.environ["F056_E2E_USER_TOKEN"])
    jobs = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        app = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=admin))
        assert app["slug"].startswith("e2e-f056-") and app["tenant_id"] == tenant_id
        yield client, admin, ordinary, app_id, tenant_id, jobs
        for job in jobs:
            assert_resp_200(await client.post(f"{API_BASE}/app-runtime-audit/exports/{job}/cancel", headers=admin))


@pytest.mark.parametrize("kind", ["model", "capability", "access"])
async def test_ac46_53_three_real_sources_and_paired_denial(runtime_records, kind):
    """AC-46, AC-48, AC-49, AC-50, AC-52, AC-53, AC-58: real records with session-only admin reads."""
    client, admin, ordinary, app_id, tenant_id, _ = runtime_records
    url = f"{API_BASE}/app-runtime-audit/records/{kind}"
    page = assert_resp_200(await client.get(url, headers=admin, params={"time_range": "all", "app_id": app_id}))
    assert page["items"], "Seed this record type through the application before running acceptance"
    assert all(row["app_id"] == app_id for row in page["items"])
    assert all(
        not {"prompt", "completion", "targets", "sealed_env", "token_hash", "obo_token"} & set(row)
        for row in page["items"]
    )
    assert_resp_error(await client.get(url, headers=ordinary), 16301)
    foreign = int(os.environ["F056_E2E_FOREIGN_TENANT_ID"])
    assert foreign != tenant_id
    assert_resp_error(await client.get(url, headers=admin, params={"tenant_id": foreign}), 16301)
    assert_resp_error(
        await client.get(f"{API_BASE}/app-runtime-audit/candidates/app", headers=ordinary, params={"kind": kind}), 16301
    )


async def test_ac51_56_complete_authenticated_export(runtime_records):
    """AC-51, AC-56, AC-57, AC-58, AC-60: all selected records, private delivery, non-admin denied."""
    client, admin, ordinary, app_id, _, jobs = runtime_records
    base = f"{API_BASE}/app-runtime-audit"
    params = {"time_range": "all", "app_id": app_id, "limit": 1}
    page = assert_resp_200(await client.get(f"{base}/records/model", headers=admin, params=params))
    assert page["items"]
    expected = {str(row["id"]) for row in page["items"]}
    cursor = page["next_cursor"]
    while cursor:
        more = assert_resp_200(
            await client.get(f"{base}/records/model", headers=admin, params={**params, "cursor": cursor})
        )
        expected.update(str(row["id"]) for row in more["items"])
        cursor = more["next_cursor"]
    body = {"snapshot_id": page["snapshot_id"], "request_id": "e2e-f056-" + uuid4().hex}
    assert_resp_error(await client.post(f"{base}/exports", headers=ordinary, json=body), 16301)
    job = assert_resp_200(await client.post(f"{base}/exports", headers=admin, json=body))["export_id"]
    jobs.append(job)
    deadline = time.monotonic() + 120
    while True:
        status = assert_resp_200(await client.get(f"{base}/exports/{job}", headers=admin))
        if status["status"] not in {"pending", "running"}:
            break
        assert time.monotonic() < deadline, "Export worker did not finish the dedicated fixture in time"
        await asyncio.sleep(1)
    assert status["status"] == "ready", status["safe_reason"]
    assert_resp_error(await client.get(f"{base}/exports/{job}/download", headers=ordinary), 16301)
    response = await client.get(f"{base}/exports/{job}/download", headers=admin)
    assert response.status_code == 200 and "text/csv" in response.headers["content-type"]
    assert response.headers.get("cache-control") == "no-store"
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert {row["id"] for row in rows} == expected
    assert status["final_count"] == len(rows)
