"""Opt-in loopback HTTP acceptance against owned MySQL/Redis/MinIO fixture stores.

DSH_AUDIT_LOCAL_FIXTURE=1, DSH_AUDIT_BASE, DSH_AUDIT_ADMIN_TOKEN,
DSH_AUDIT_TENANT_ADMIN_TOKEN and DSH_AUDIT_USER_TOKEN are required.
Synthetic bearer identities replace production JWT/FGA in this fixture only;
this is not production authentication acceptance. Container setup/teardown is
owned by audit_local_server, which creates fresh stores and removes only those
stores. This feature has no deletion API and never deletes business records.
"""

import asyncio
import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import assert_resp_200

pytestmark = pytest.mark.e2e
BASE = "/api/v1/dsh/admin/model-audit"


class TestModelAuditLocalE2E:
    async def test_request_persistence_scope_and_explicit_original(self):
        """AC-18/AC-19/AC-21/AC-24/AC-28/AC-32/AC-33/AC-35: HTTP + owned stores."""
        if os.environ.get("DSH_AUDIT_LOCAL_FIXTURE") != "1":
            pytest.skip("Explicit isolated fixture opt-in is required")
        base = os.environ["DSH_AUDIT_BASE"]
        assert urlsplit(base).hostname in {"127.0.0.1", "localhost", "::1"}
        assert urlsplit(base).scheme == "http"
        headers = {
            role: {"Authorization": "Bearer " + os.environ[variable]}
            for role, variable in (
                ("global", "DSH_AUDIT_ADMIN_TOKEN"),
                ("tenant", "DSH_AUDIT_TENANT_ADMIN_TOKEN"),
                ("user", "DSH_AUDIT_USER_TOKEN"),
            )
        }
        conversation = "e2e-dsh-audit-" + str(uuid4())
        async with httpx.AsyncClient(base_url=base, timeout=10, trust_env=False) as client:
            assert (await client.get("/health")).json()["fixture"] is True
            mode = assert_resp_200(await client.get(BASE + "/settings", headers=headers["global"]))
            assert mode["mode"] == "CONTENT", "Enable CONTENT only in the disposable fixture first"
            request_ids = []
            for stream in (False, True):
                response = await client.post(
                    "/api/v1/dsh/chat/completions",
                    headers=headers["user"],
                    json={
                        "model": "bisheng:42",
                        "messages": [{"role": "user", "content": conversation}],
                        "stream": stream,
                        "audit_context": {"conversation_id": conversation, "request_kind": "chat"},
                    },
                )
                assert response.status_code == 200
                request_ids.append(response.headers["x-request-id"])
            for _ in range(200):
                page = assert_resp_200(
                    await client.get(
                        BASE + "/conversations",
                        headers=headers["global"],
                        params={"user_id": 20, "conversation_id": conversation},
                    )
                )
                if len(page["items"]) == 2 and all(row["content_status"] == "COMPLETE" for row in page["items"]):
                    break
                await asyncio.sleep(0.025)
            assert [row["request_id"] for row in page["items"]] == request_ids
            assert conversation not in json.dumps(
                [{key: value for key, value in row.items() if key != "conversation_id"} for row in page["items"]]
            )
            for request_id in request_ids:
                for role in ("global", "tenant"):
                    detail = assert_resp_200(await client.get(BASE + "/requests/" + request_id, headers=headers[role]))
                    assert detail["content_status"] == "COMPLETE" and detail["usage"]["total_tokens"] == 12
                    original = await client.post(
                        BASE + "/requests/" + request_id + "/body-access", headers=headers[role]
                    )
                    assert original.headers["cache-control"] == "no-store"
                    frames = [json.loads(line) for line in original.text.splitlines()]
                    assert frames[-1]["type"] == "end" and frames[-1]["transfer_status"] == "COMPLETED"
                    assert conversation in original.text and "audit_context" not in original.text
                denied = await client.post(BASE + "/requests/" + request_id + "/body-access", headers=headers["user"])
                assert denied.status_code == 403
                denied = await client.get(
                    BASE + "/requests/" + request_id, headers=headers["tenant"], params={"tenant_id": 3}
                )
                assert denied.status_code == 403
