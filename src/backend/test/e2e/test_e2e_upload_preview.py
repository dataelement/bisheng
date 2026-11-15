"""AC-21..26: opt-in real parser/worker acceptance for owned upload previews.

Uses the existing isolated F118 tenant/auth/model fixtures and exact-name,
owner/tenant checked setup+teardown. Without F118_E2E=1 collection is offline.
"""

import asyncio
import json
import os
import time
from copy import deepcopy

import pytest

from test.e2e.helpers.f118_processing_recovery import chunks
from test.e2e.test_e2e_f118_unification import target as target

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(os.environ.get("F118_E2E") != "1", reason="requires upgraded isolated F118 and explicit opt-in"),
]


async def test_ac23_ac24_preview_edits_reach_final_worker_chunks_and_other_actor_is_denied(target):
    """AC-23/24/25: preview/edit/freeze uses the same rule and no legacy root edit endpoint."""
    space = await target.space("rules")
    sid = space["id"]
    defaults = await target.ok("GET", f"/knowledge/space/{sid}/files/upload-settings")
    overrides = deepcopy(defaults["effective_defaults"])
    overrides.pop("schema_version")
    overrides["document"].update(chunk_size=640, chunk_overlap=0)
    staged = await target.ok(
        "POST",
        f"/knowledge/space/{sid}/uploads",
        files={
            "file": (
                target.prefix + "upload-preview.md",
                b"# Upload preview\nA distinct temporary document.",
                "text/markdown",
            ),
        },
    )
    base = f"/knowledge/space/{sid}/uploads/{staged['upload_id']}"
    await target.error("GET", base, 18083, actor=target.reader)
    pid = (await target.ok("POST", f"{base}/previews", json={"overrides": overrides}))["preview_id"]
    deadline = time.monotonic() + target.timeout
    while True:
        preview = await target.ok("GET", f"{base}/previews/{pid}")
        if preview["status"] != "processing":
            assert preview["status"] == "completed"
            break
        assert time.monotonic() < deadline, "preview timed out"
        await asyncio.sleep(1)
    index = preview["data"]["chunks"][0]["metadata"]["chunk_index"]
    marker = target.prefix + "confirmed-preview-edit"
    preview = await target.ok(
        "PUT",
        f"{base}/previews/{pid}/chunks/{index}",
        json={
            "text": marker,
            "bbox": "",
            "expected_revision": preview["revision"],
        },
    )
    body = {
        "file_path": [staged["file_path"]],
        "overrides": overrides,
        "upload_context": {
            "mode": "previewed",
            "items": [
                {
                    "upload_id": staged["upload_id"],
                    "file_path": staged["file_path"],
                    "overrides": overrides,
                    "preview_id": pid,
                    "expected_revision": preview["revision"],
                }
            ],
        },
    }
    accepted = await target.ok("POST", f"/knowledge/space/{sid}/files", json=body)
    assert len(accepted) == 1
    await target.wait_file(sid, accepted[0]["id"])
    actual = await chunks(target, sid, accepted[0]["id"])
    assert actual["total"] > 0 and marker in json.dumps(actual["data"], ensure_ascii=False)
    status = await target.ok("GET", base)
    assert status["state"] == "COMMITTED" and status["rows"][0]["id"] == accepted[0]["id"]
    replay = await target.ok("POST", f"/knowledge/space/{sid}/files", json=body)
    assert replay[0]["id"] == accepted[0]["id"]


async def test_ac22_ac26_direct_upload_preserves_effective_defaults_without_preview(target):
    """AC-22/26: the old direct shortcut carries explicit effective defaults to the real worker."""
    sid = (await target.space("versions"))["id"]
    value = await target.ok("GET", f"/knowledge/space/{sid}/files/upload-settings")
    defaults = value["effective_defaults"]
    overrides = {"document": defaults["document"], "table": defaults["table"]}
    staged = await target.ok(
        "POST",
        f"/knowledge/space/{sid}/uploads",
        files={
            "file": (target.prefix + "direct.txt", b"Distinct direct upload content.", "text/plain"),
        },
    )
    accepted = await target.ok(
        "POST",
        f"/knowledge/space/{sid}/files",
        json={
            "file_path": [staged["file_path"]],
            "overrides": overrides,
            "upload_context": {
                "mode": "direct",
                "items": [
                    {
                        "upload_id": staged["upload_id"],
                        "file_path": staged["file_path"],
                        "overrides": overrides,
                    }
                ],
            },
        },
    )
    final = await target.wait_file(sid, accepted[0]["id"])
    rule = json.loads(final["split_rule"])
    assert rule["chunk_size"] == defaults["document"]["chunk_size"]
    assert rule["chunk_overlap"] == defaults["document"]["chunk_overlap"]
    assert (await chunks(target, sid, final["id"]))["total"] > 0
