"""Opt-in deployed F115 checks, using dedicated tenant fixtures and ephemeral tokens.

F115_E2E=1 requires E2E_API_BASE, F115_TENANT_ID, F115_FOREIGN_TEMPLATE_ID,
F115_WORKFLOW_ID, F115_ASSISTANT_ID, F115_ADMIN_TOKEN, F115_USER_TOKEN,
F115_FOREIGN_TOKEN. The administrator must already be viewing F115_TENANT_ID.
Only uniquely named e2e-f115 templates created here are mutated and cleaned.
"""

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.skipif(
    os.environ.get("F115_E2E") != "1", reason="requires deployed F115 and dedicated tenant accounts"
)


@pytest.fixture
async def templates():
    tid = int(os.environ["F115_TENANT_ID"])
    headers = {role: auth_headers(os.environ[f"F115_{role.upper()}_TOKEN"]) for role in ["admin", "user", "foreign"]}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{API_BASE}/skill/template", headers=headers["admin"])
        assert_resp_200(response)
        assert int(response.headers["X-Management-Tenant"]) == tid
        headers["admin"]["X-Management-Tenant"] = str(tid)
        created = []
        try:
            for kind, source in [(10, "WORKFLOW"), (5, "ASSISTANT")]:
                row = assert_resp_200(
                    await client.post(
                        f"{API_BASE}/skill/template/create",
                        headers=headers["admin"],
                        json={
                            "name": f"e2e-f115-{uuid4().hex[:12]}",
                            "description": "F115 isolated test",
                            "flow_type": kind,
                            "flow_id": os.environ[f"F115_{source}_ID"],
                        },
                    )
                )
                created.append(row)
                assert row["tenant_id"] == tid
            yield client, headers, created
        finally:
            for row in created:
                assert row["name"].startswith("e2e-f115-")
                assert_resp_200(await client.delete(f"{API_BASE}/skill/template/{row['id']}", headers=headers["admin"]))


async def test_ac01_ac04_same_tenant_user_can_read_both_template_types(templates):
    client, headers, rows = templates
    for row in rows:
        listed = assert_resp_200(
            await client.get(
                f"{API_BASE}/skill/template", headers=headers["user"], params={"flow_type": row["flow_type"]}
            )
        )
        assert row["id"] in {item["id"] for item in listed}
        detail = assert_resp_200(
            await client.get(f"{API_BASE}/skill/template", headers=headers["user"], params={"id": row["id"]})
        )
        assert detail[0]["data"] == row["data"]


async def test_ac05_regular_user_cannot_mutate_templates(templates):
    client, headers, rows = templates
    for row in rows:
        for method, path, payload in [
            ("POST", "create", {"name": "e2e-f115-denied", "flow_type": row["flow_type"], "flow_id": row["flow_id"]}),
            ("POST", str(row["id"]), {"order_num": 42}),
            ("DELETE", str(row["id"]), None),
        ]:
            assert_resp_error(
                await client.request(
                    method, f"{API_BASE}/skill/template/{path}", headers=headers["user"], json=payload
                ),
                19000,
            )


async def test_ac06_foreign_templates_are_not_visible(templates):
    client, headers, rows = templates
    for row in rows:
        assert_resp_error(
            await client.get(f"{API_BASE}/skill/template", headers=headers["foreign"], params={"id": row["id"]}), 404
        )
    assert_resp_error(
        await client.get(
            f"{API_BASE}/skill/template",
            headers=headers["admin"],
            params={"id": os.environ["F115_FOREIGN_TEMPLATE_ID"]},
        ),
        404,
    )


async def test_ac03_ac07_admin_updates_own_template_without_reassigning_it(templates):
    client, headers, rows = templates
    for row in rows:
        changed = assert_resp_200(
            await client.post(
                f"{API_BASE}/skill/template/{row['id']}",
                headers=headers["admin"],
                json={
                    "order_num": 42,
                    "tenant_id": int(row["tenant_id"]) + 1,
                },
            )
        )
        assert changed["tenant_id"] == row["tenant_id"] and changed["order_num"] == 42


async def test_ac02_stale_management_view_cannot_write(templates):
    client, headers, rows = templates
    stale = {**headers["admin"], "X-Management-Tenant": str(int(rows[0]["tenant_id"]) + 1)}
    assert_resp_error(
        await client.post(f"{API_BASE}/skill/template/{rows[0]['id']}", headers=stale, json={"order_num": 1}), 26073
    )
