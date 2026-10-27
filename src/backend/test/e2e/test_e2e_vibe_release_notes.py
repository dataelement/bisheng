"""Opt-in F112 publication/approval journey on a dedicated existing application.

F112_E2E=1, E2E_API_BASE, F112_E2E_APP_ID, F112_E2E_TENANT_ID,
F112_E2E_PACKAGE and F112_E2E_API_KEY are required. Four RAM-only session tokens
are supplied as F112_E2E_{OWNER,APPROVER,NONOWNER,FOREIGN}_TOKEN. The owner and
nonowner must be ordinary users, the foreign token belongs to another tenant,
and the approver must be an assigned approver. The package must retain the
dedicated e2e-f112- app name/slug. One new version is submitted then rejected;
it remains as immutable test history. No existing app or version is deleted.
"""

import asyncio
import os
import tarfile
import time
from pathlib import Path

import httpx
import pytest
import yaml

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.skipif(os.environ.get("F112_E2E") != "1", reason="requires a deployed F112 test environment")

NOTES = "e2e-f112 新增功能\n  Fix <script>plain text</script>"


@pytest.fixture
async def publication_target():
    app_id = os.environ["F112_E2E_APP_ID"]
    tenant = int(os.environ["F112_E2E_TENANT_ID"])
    tokens = {
        role: auth_headers(os.environ[f"F112_E2E_{role}_TOKEN"])
        for role in ("OWNER", "APPROVER", "NONOWNER", "FOREIGN")
    }
    rpc = API_BASE.removesuffix("/api/v1") + "/api/v2/apps"
    key = {"Authorization": "Bearer " + os.environ["F112_E2E_API_KEY"]}
    async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as client:
        app = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=tokens["OWNER"]))
        assert app["name"].startswith("e2e-f112-") and app["slug"].startswith("e2e-f112-")
        assert int(app["tenant_id"]) == tenant
        package = Path(os.environ["F112_E2E_PACKAGE"])
        with tarfile.open(package, "r:gz") as archive:
            candidates = [m for m in archive if m.name in {"bisheng-app.yaml", "./bisheng-app.yaml"}]
            assert len(candidates) == 1 and candidates[0].isfile() and candidates[0].size <= 65536
            manifest = yaml.safe_load(archive.extractfile(candidates[0]).read())
        assert manifest["name"] == app["name"]
        assert manifest.get("slug", app["slug"]) == app["slug"]
        capabilities = assert_resp_200(await client.get(f"{rpc}/deploy-limits", headers=key))
        assert capabilities["features"]["release_notes"]["version"] == 1
        attempt = {}
        try:
            yield client, app_id, tokens, rpc, key, package, attempt
        finally:
            # Only this test's in-flight request can be withdrawn; immutable
            # approved/rejected/withdrawn version records are deliberately kept.
            instance_id = attempt.get("instance_id")
            if instance_id:
                detail = assert_resp_200(
                    await client.get(f"{API_BASE}/approval/instances/{instance_id}", headers=tokens["OWNER"])
                )
                if detail["status"] == "pending":
                    assert_resp_200(
                        await client.post(
                            f"{API_BASE}/approval/instances/{instance_id}/withdraw",
                            headers=tokens["OWNER"],
                            json={"reason": "e2e-f112 cleanup"},
                        )
                    )


async def test_publication_notes_reach_approval_and_immutable_version(publication_target):
    """AC-08, AC-09, AC-10, AC-12, AC-13, AC-16: one real publish with paired denials."""
    client, app_id, tokens, rpc, key, package, attempt = publication_target
    with package.open("rb") as source:
        accepted = assert_resp_200(
            await client.post(
                f"{rpc}/deploy",
                headers=key,
                files={"package": (package.name, source, "application/gzip")},
                data={"app_id": app_id, "release_notes": "  " + NOTES.replace("\n", "\r\n") + "  "},
            )
        )
    deadline = time.monotonic() + 600
    while True:
        progress = assert_resp_200(await client.get(f"{rpc}/deployments/{accepted['deployment_id']}", headers=key))
        assert progress.get("status") != "failed", progress.get("failure")
        approval = progress.get("approval") or {}
        if approval.get("instance_id"):
            attempt["instance_id"] = approval["instance_id"]
            break
        assert time.monotonic() < deadline, "F112 publish did not reach approval within 600s"
        await asyncio.sleep(1)
    instance_url = f"{API_BASE}/approval/instances/{attempt['instance_id']}"
    detail = assert_resp_200(await client.get(instance_url, headers=tokens["OWNER"]))
    assert detail["detail_snapshot"]["release_notes"] == NOTES
    task_id = next(task["task_id"] for task in detail["tasks"] if task["status"] == "pending")
    task = assert_resp_200(await client.get(f"{API_BASE}/approval/my-tasks/{task_id}", headers=tokens["APPROVER"]))
    assert task["detail_snapshot"]["release_notes"] == NOTES
    for role, code in (("NONOWNER", 16106), ("FOREIGN", 16101)):
        assert_resp_error(await client.get(f"{API_BASE}/apps/{app_id}/versions", headers=tokens[role]), code)
        assert_resp_error(await client.get(instance_url, headers=tokens[role]), 18101)
    assert_resp_200(
        await client.post(
            f"{API_BASE}/approval/tasks/{task_id}/decision",
            headers=tokens["APPROVER"],
            json={"action": "reject", "comment": "e2e-f112 release notes verification"},
        )
    )
    versions = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}/versions", headers=tokens["OWNER"]))
    version = next(row for row in versions["data"] if row["version_id"] == accepted["version_id"])
    assert version["terminal_state"] == "rejected"
    assert version["release_notes"] == NOTES
