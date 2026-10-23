"""Opt-in live provider regression for a dedicated single-tenant test environment.

Run with E2E_API_BASE, E2E_ADMIN_TOKEN (or E2E_ADMIN_PASSWORD),
DSH_E2E_MODEL_ID, DSH_E2E_ROOT_DEPARTMENT_ID and
DSH_E2E_ALLOW_SINGLE_TENANT=1. Never enable tenant mode to run this test.
Fixtures are disabled after each run; usage and audit evidence are retained.
"""

import asyncio
import json
import os
import secrets
import uuid

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, encrypt_password, get_admin_token, get_public_key, login
from test.e2e.helpers.dsh import native_desktop_session

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("DSH_E2E_ALLOW_SINGLE_TENANT") != "1"
        or not os.environ.get("DSH_E2E_MODEL_ID")
        or not os.environ.get("DSH_E2E_ROOT_DEPARTMENT_ID"),
        reason="Requires an explicitly selected non-production single-tenant environment and existing model",
    ),
]


class _Credentials(dict):
    def __repr__(self):
        return "Credentials(<redacted>)"


def _departments(nodes):
    for node in nodes:
        yield node
        yield from _departments(node.get("children", []))


async def _retire_fixture(client, admin, department, model_id, prefix):
    """Disable only members and policies owned by this suite, preserving audit."""
    assert department["name"].startswith(prefix) and len(prefix) >= 5
    members = assert_resp_200(
        await client.get(f"{API_BASE}/departments/{department['dept_id']}/members", headers=admin)
    )
    assert all(member["user_name"].startswith(prefix) for member in members["data"])
    assert members["total"] == len(members["data"])
    for member in members["data"]:
        uid = member["user_id"]
        path = f"{API_BASE}/dsh/admin/users/{uid}/models/{model_id}/policy"
        policy = assert_resp_200(await client.get(path, headers=admin))
        if policy["enabled"]:
            assert_resp_200(
                await client.put(
                    path,
                    headers=admin,
                    json={
                        "operation_id": str(uuid.uuid4()),
                        "expected_version": policy["version"],
                        "enabled": False,
                        "monthly_token_limit": 0,
                    },
                )
            )
        if member["enabled"]:
            response = await client.post(f"{API_BASE}/user/update", headers=admin, json={"user_id": uid, "delete": 1})
            assert response.status_code == 201 and response.json()["status_code"] == 200
    subjects = assert_resp_200(await client.get(f"{API_BASE}/dsh/admin/models/{model_id}/subjects", headers=admin))
    policy = next(item for item in subjects["departments"] if item["subject_id"] == department["id"])
    if policy["enabled"]:
        assert_resp_200(
            await client.put(
                f"{API_BASE}/dsh/admin/models/{model_id}/subjects/DEPARTMENT/{department['id']}/policy",
                headers=admin,
                json={"expected_version": policy["version"], "enabled": False, "monthly_token_limit": 0},
            )
        )
    members = assert_resp_200(
        await client.get(f"{API_BASE}/departments/{department['dept_id']}/members", headers=admin)
    )
    assert all(not member["enabled"] for member in members["data"])


@pytest_asyncio.fixture
async def scenario():
    model_id = int(os.environ["DSH_E2E_MODEL_ID"])
    prefix = f"e2e-dsh110-live-m{model_id}-"
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        admin = _Credentials(auth_headers(await get_admin_token(client)))
        old = assert_resp_200(
            await client.get(f"{API_BASE}/departments/search", params={"keyword": prefix, "limit": 200}, headers=admin)
        )
        assert not old["truncated"]
        for department in _departments(old["roots"]):
            if department["name"].startswith(prefix):
                await _retire_fixture(client, admin, department, model_id, prefix)
        department = assert_resp_200(
            await client.post(
                f"{API_BASE}/departments/",
                headers=admin,
                json={
                    "name": prefix + uuid.uuid4().hex[:8],
                    "parent_id": int(os.environ["DSH_E2E_ROOT_DEPARTMENT_ID"]),
                    "default_role_ids": [2],
                },
            )
        )
        users = []
        try:
            public_key = await get_public_key(client)
            for kind in ("personal", "inherit"):
                name = department["name"] + "-" + kind
                password = "Dsh110!" + secrets.token_hex(12)
                user = assert_resp_200(
                    await client.post(
                        f"{API_BASE}/departments/local-members",
                        headers=admin,
                        json={
                            "dept_id": department["dept_id"],
                            "user_name": name,
                            "person_id": name,
                            "password": encrypt_password(password, public_key),
                            "role_ids": [2],
                        },
                    )
                )
                token = await login(client, name, password)
                client.cookies.clear()
                users.append(_Credentials({"id": user["user_id"], "platform_token": token}))
            yield client, admin, department, model_id, users
        finally:
            await _retire_fixture(client, admin, department, model_id, prefix)


async def _personal_policy(client, admin, uid, model_id, enabled, limit):
    path = f"{API_BASE}/dsh/admin/users/{uid}/models/{model_id}/policy"
    before = assert_resp_200(await client.get(path, headers=admin))
    operation = assert_resp_200(
        await client.put(
            path,
            headers=admin,
            json={
                "operation_id": str(uuid.uuid4()),
                "expected_version": before["version"],
                "enabled": enabled,
                "monthly_token_limit": limit,
            },
        )
    )
    assert operation["status"] == "SUCCEEDED"
    after = assert_resp_200(await client.get(path, headers=admin))
    assert after["enabled"] == enabled and after["monthly_token_limit"] == limit


async def test_native_login_quota_and_content_audit(scenario):
    """AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08: native access, quota and audit."""
    client, admin, department, model_id, users = scenario
    model = f"bisheng:{model_id}"
    assert_resp_200(
        await client.put(
            f"{API_BASE}/dsh/admin/models/{model_id}/subjects/DEPARTMENT/{department['id']}/policy",
            headers=admin,
            json={"expected_version": 0, "enabled": True, "monthly_token_limit": 100000},
        )
    )
    await _personal_policy(client, admin, users[0]["id"], model_id, True, 10000)
    for user in users:
        tokens = await native_desktop_session(client, user["platform_token"], department["name"])
        user["desktop"] = {"Authorization": "Bearer " + tokens["access_token"]}
        response = await client.get(f"{API_BASE}/dsh/models", headers=user["desktop"])
        assert response.status_code == 200 and model in {item["id"] for item in response.json()["data"]}
    requests = []
    for index, user in enumerate(users):
        before = await client.get(f"{API_BASE}/dsh/usage", params={"model": model}, headers=user["desktop"])
        assert before.status_code == 200 and before.json()["used"] == 0
        assert before.json()["limit"] == (10000 if index == 0 else 100000)
        response = await client.post(
            f"{API_BASE}/dsh/chat/completions",
            headers=user["desktop"],
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Only reply DSH110_SUITE_OK. Do not call tools."}],
                "max_tokens": 256,
                "stream": bool(index),
                "audit_context": {"conversation_id": department["name"] + str(index), "request_kind": "chat"},
            },
        )
        assert response.status_code == 200
        if index:
            assert "data: [DONE]" in response.text
            chunks = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ") and line != "data: [DONE]"
            ]
            answer = "".join(
                choice.get("delta", {}).get("content", "") for chunk in chunks for choice in chunk.get("choices", [])
            )
        else:
            answer = response.json()["choices"][0]["message"]["content"]
        assert answer.strip() == "DSH110_SUITE_OK"
        requests.append(response.headers["x-request-id"])
    used = []
    for user in users:
        response = await client.get(f"{API_BASE}/dsh/usage", params={"model": model}, headers=user["desktop"])
        assert response.status_code == 200 and response.json()["used"] > 0
        used.append(response.json()["used"])
    await _personal_policy(client, admin, users[0]["id"], model_id, True, max(1, used[0] - 1))
    payload = {"model": model, "messages": [{"role": "user", "content": "Reply OK"}], "max_tokens": 32}
    blocked = await client.post(f"{API_BASE}/dsh/chat/completions", headers=users[0]["desktop"], json=payload)
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "monthly_token_limit_exceeded"
    await _personal_policy(client, admin, users[0]["id"], model_id, True, 0)
    blocked = await client.post(f"{API_BASE}/dsh/chat/completions", headers=users[0]["desktop"], json=payload)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "model_not_allowed"
    await _personal_policy(client, admin, users[0]["id"], model_id, False, 0)
    for index, user in enumerate(users):
        response = await client.get(f"{API_BASE}/dsh/usage", params={"model": model}, headers=user["desktop"])
        assert response.status_code == 200
        assert response.json()["limit"] == 100000 and response.json()["used"] == used[index]
    denied = await client.get(f"{API_BASE}/dsh/admin/settings", headers=auth_headers(users[0]["platform_token"]))
    assert denied.json()["status_code"] == 403
    for request_id in requests:
        path = f"{API_BASE}/dsh/admin/model-audit/requests/{request_id}"
        for _attempt in range(30):
            audit = assert_resp_200(await client.get(path, headers=admin))
            if (
                audit["content_status"] == "COMPLETE"
                and audit["usage_settlement"] == "SETTLED"
                and audit.get("usage")
                and audit["usage"].get("total_tokens") is not None
            ):
                break
            await asyncio.sleep(1)
        assert audit["audit_status"] == "NORMAL" and audit["content_status"] == "COMPLETE"
        assert audit["usage"]["total_tokens"] > 0
        body = await client.post(path + "/body-access", headers=admin)
        assert body.status_code == 200 and "DSH110_SUITE_OK" in body.text
        denied = await client.post(path + "/body-access", headers=auth_headers(users[0]["platform_token"]))
        assert denied.json()["status_code"] == 19801
    for user in users:
        response = await client.post(f"{API_BASE}/dsh/logout", headers=user["desktop"])
        assert response.status_code == 204
        response = await client.get(f"{API_BASE}/dsh/models", headers=user["desktop"])
        assert response.status_code == 401
