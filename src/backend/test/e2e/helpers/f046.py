"""Live E2E helpers for F046 knowledge-space file-change approval.

The helpers deliberately require an explicit opt-in before issuing writes.
Every created user and space uses one process-unique ``e2e-f046-<run-id>-``
prefix, and cleanup only touches objects carrying that exact run prefix.  They
complement (rather than duplicate) the shared auth and UnifiedResponseModel
helpers.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import (
    auth_headers,
    create_test_user,
    get_admin_token,
    get_user_token,
)

PREFIX_ROOT = "e2e-f046-"
RUN_PREFIX = f"{PREFIX_ROOT}{uuid.uuid4().hex[:8]}-"


@dataclass(frozen=True)
class F046Identity:
    user_id: int
    username: str
    token: str


@dataclass
class F046TenantEnvironment:
    admin_token: str
    tenant_id: int
    original_policy: dict
    editor: F046Identity
    manager: F046Identity
    replacement_manager: F046Identity
    viewer: F046Identity
    space_ids: set[int] = field(default_factory=set)


def require_f046_live_opt_in() -> None:
    """Skip before any live write unless the operator explicitly opted in."""
    if os.environ.get("E2E_F046_ENABLED") != "1":
        pytest.skip("set E2E_F046_ENABLED=1 to run live F046 write-path E2E tests")


def require_async_workers() -> None:
    if os.environ.get("E2E_F046_ASYNC_ENABLED") != "1":
        pytest.skip("set E2E_F046_ASYNC_ENABLED=1 when approval, knowledge and Beat workers are running")


def assert_success(response: httpx.Response):
    """Assert the complete UnifiedResponseModel shape and return ``data``."""
    data = assert_resp_200(response)
    body = response.json()
    assert {"status_code", "status_message", "data"}.issubset(body), body
    assert body["status_message"] == "SUCCESS", body
    return data


def assert_error(response: httpx.Response, expected_code: int) -> dict:
    """Assert an exact business error and the common response envelope."""
    body = assert_resp_error(response, expected_code)
    assert {"status_code", "status_message", "data"}.issubset(body), body
    return body


def _jwt_subject(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise AssertionError("JWT does not contain three segments")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(payload.encode()))
    subject = decoded.get("sub", {})
    return json.loads(subject) if isinstance(subject, str) else subject


def tenant_id_from_token(token: str) -> int:
    tenant_id = _jwt_subject(token).get("tenant_id")
    assert tenant_id is not None, "F046 E2E requires tenant_id in JWT"
    return int(tenant_id)


def rows(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        value = data.get("data") or data.get("items") or []
        return value if isinstance(value, list) else []
    return []


async def create_identity(
    client: httpx.AsyncClient,
    admin_token: str,
    label: str,
) -> F046Identity:
    username = f"{RUN_PREFIX}{label}"
    password = secrets.token_urlsafe(18)
    user = await create_test_user(
        client,
        admin_token,
        username=username,
        role_id=2,
        password=password,
    )
    user_id = user.get("user_id") or user.get("id")
    assert user_id is not None, user
    token = await get_user_token(client, username, password)
    return F046Identity(user_id=int(user_id), username=username, token=token)


async def get_policy(client: httpx.AsyncClient, token: str) -> dict:
    return assert_success(
        await client.get(
            f"{API_BASE}/knowledge/space/admin/file-change-policy",
            headers=auth_headers(token),
        )
    )


async def put_policy(
    client: httpx.AsyncClient,
    token: str,
    *,
    enabled: bool,
    scope: str,
) -> dict:
    return assert_success(
        await client.put(
            f"{API_BASE}/knowledge/space/admin/file-change-policy",
            json={"enabled": enabled, "scope": scope},
            headers=auth_headers(token),
        )
    )


async def create_space(
    client: httpx.AsyncClient,
    env: F046TenantEnvironment,
    label: str,
    *,
    auth_type: str = "approval",
    include_editor: bool = True,
    include_manager: bool = True,
    extra_grants: list[dict] | None = None,
) -> dict:
    grants: list[dict] = []
    if include_editor:
        grants.append(
            {
                "subject_type": "user",
                "subject_id": env.editor.user_id,
                "relation": "editor",
                "include_children": False,
            }
        )
    if include_manager:
        grants.append(
            {
                "subject_type": "user",
                "subject_id": env.manager.user_id,
                "relation": "manager",
                "include_children": False,
            }
        )
    grants.extend(extra_grants or [])
    data = assert_success(
        await client.post(
            f"{API_BASE}/knowledge/space",
            json={
                "name": f"{RUN_PREFIX}{label}",
                "auth_type": auth_type,
                "initial_permissions": {"grants": grants},
            },
            headers=auth_headers(env.admin_token),
        )
    )
    assert data.get("initial_permission_result", {}).get("status") == "success", data
    env.space_ids.add(int(data["id"]))
    return data


async def create_folder(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    name: str,
    *,
    parent_id: int | None = None,
) -> dict:
    return assert_success(
        await client.post(
            f"{API_BASE}/knowledge/space/{space_id}/folders",
            json={"name": name, "parent_id": parent_id},
            headers=auth_headers(token),
        )
    )


async def stage_upload(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    file_name: str,
    content: bytes,
) -> dict:
    data = assert_success(
        await client.post(
            f"{API_BASE}/knowledge/upload/{space_id}",
            files={"file": (file_name, content, "text/plain")},
            headers=auth_headers(token),
        )
    )
    assert data["space_id"] == space_id
    assert data["file_name"] == file_name
    assert data.get("upload_id")
    assert "object_name" not in data
    return data


async def register_upload(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    upload_id: str,
    *,
    parent_id: int | None = None,
) -> dict:
    data = assert_success(
        await client.post(
            f"{API_BASE}/knowledge/space/{space_id}/files",
            json={"upload_ids": [upload_id], "parent_id": parent_id},
            headers=auth_headers(token),
        )
    )
    assert len(data) == 1, data
    return data[0]


async def list_children(
    client: httpx.AsyncClient,
    token: str,
    space_id: int,
    *,
    parent_id: int | None = None,
) -> list[dict]:
    data = assert_success(
        await client.get(
            f"{API_BASE}/knowledge/space/{space_id}/children",
            params={"parent_id": parent_id, "page_size": 100},
            headers=auth_headers(token),
        )
    )
    assert {"data", "page_size", "has_more", "next_cursor"}.issubset(data), data
    return data["data"]


async def wait_for(
    probe: Callable[[], Awaitable[object]],
    predicate: Callable[[object], bool],
    *,
    description: str,
    timeout: float = 90.0,
) -> object:
    deadline = asyncio.get_running_loop().time() + timeout
    latest: object = None
    while asyncio.get_running_loop().time() < deadline:
        latest = await probe()
        if predicate(latest):
            return latest
        await asyncio.sleep(1)
    raise AssertionError(f"timed out waiting for {description}; latest={latest!r}")


async def authorize_space(
    client: httpx.AsyncClient,
    owner_token: str,
    space_id: int,
    *,
    grants: list[dict] | None = None,
    revokes: list[dict] | None = None,
) -> dict:
    return assert_success(
        await client.post(
            f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/authorize",
            json={"grants": grants or [], "revokes": revokes or []},
            headers=auth_headers(owner_token),
        )
    )


async def cleanup_prefix(
    client: httpx.AsyncClient,
    token: str,
) -> None:
    """Strict, prefix-scoped cleanup used both before and after each suite."""
    if len(RUN_PREFIX) < 5:
        raise AssertionError("unsafe F046 cleanup prefix")
    evidence: list[str] = []
    headers = auth_headers(token)

    try:
        mine = rows(assert_success(await client.get(f"{API_BASE}/knowledge/space/mine", headers=headers)))
    except (httpx.HTTPError, AssertionError, KeyError, ValueError) as error:
        raise AssertionError(f"unable to enumerate F046 cleanup spaces: {error}") from error

    for space in mine:
        if not str(space.get("name", "")).startswith(RUN_PREFIX):
            continue
        space_id = space.get("id")
        if space_id is None:
            evidence.append(f"prefixed space has no id: {space}")
            continue
        response = await client.delete(
            f"{API_BASE}/knowledge/space/{space_id}",
            headers=headers,
        )
        try:
            assert_success(response)
        except (AssertionError, KeyError, ValueError) as error:
            evidence.append(f"delete space {space_id}: {error}")

    try:
        users = rows(
            assert_success(
                await client.get(
                    f"{API_BASE}/user/list",
                    params={"page_num": 1, "page_size": 500, "name": RUN_PREFIX},
                    headers=headers,
                )
            )
        )
    except (httpx.HTTPError, AssertionError, KeyError, ValueError) as error:
        evidence.append(f"enumerate users: {error}")
        users = []
    for user in users:
        if not str(user.get("user_name", "")).startswith(RUN_PREFIX):
            continue
        user_id = user.get("user_id") or user.get("id")
        if user_id is None:
            evidence.append(f"prefixed user has no id: {user}")
            continue
        response = await client.post(
            f"{API_BASE}/user/update",
            json={"user_id": user_id, "delete": 1},
            headers=headers,
        )
        try:
            assert_success(response)
        except (AssertionError, KeyError, ValueError) as error:
            evidence.append(f"soft-delete user {user_id}: {error}")

    if evidence:
        raise AssertionError("F046 prefix cleanup failed:\n" + "\n".join(evidence))


async def provision_default_tenant(client: httpx.AsyncClient) -> F046TenantEnvironment:
    require_f046_live_opt_in()
    try:
        admin_token = await get_admin_token(client)
    except (httpx.HTTPError, AssertionError, KeyError, ValueError) as error:
        pytest.skip(f"F046 live backend/login unavailable: {error}")
    await cleanup_prefix(client, admin_token)
    original_policy = await get_policy(client, admin_token)
    editor = await create_identity(client, admin_token, "editor")
    manager = await create_identity(client, admin_token, "manager-old")
    replacement = await create_identity(client, admin_token, "manager-new")
    viewer = await create_identity(client, admin_token, "viewer")
    return F046TenantEnvironment(
        admin_token=admin_token,
        tenant_id=tenant_id_from_token(admin_token),
        original_policy=original_policy,
        editor=editor,
        manager=manager,
        replacement_manager=replacement,
        viewer=viewer,
    )


async def restore_and_cleanup(
    client: httpx.AsyncClient,
    env: F046TenantEnvironment,
) -> None:
    failures: list[str] = []
    try:
        await put_policy(
            client,
            env.admin_token,
            enabled=bool(env.original_policy["enabled"]),
            scope=str(env.original_policy["scope"]),
        )
    except (httpx.HTTPError, AssertionError, KeyError, ValueError) as error:
        failures.append(f"restore policy: {error}")
    try:
        await cleanup_prefix(client, env.admin_token)
    except (httpx.HTTPError, AssertionError, KeyError, ValueError) as error:
        failures.append(f"prefix cleanup: {error}")
    if failures:
        raise AssertionError("F046 teardown failed:\n" + "\n".join(failures))


async def optional_tenant_b_token(client: httpx.AsyncClient) -> str:
    username = os.environ.get("E2E_F046_TENANT_B_ADMIN_USERNAME")
    password = os.environ.get("E2E_F046_TENANT_B_ADMIN_PASSWORD")
    if not username or not password:
        pytest.skip(
            "set E2E_F046_TENANT_B_ADMIN_USERNAME and E2E_F046_TENANT_B_ADMIN_PASSWORD "
            "for dual-tenant isolation coverage"
        )
    token = await get_user_token(client, username, password)
    assert tenant_id_from_token(token) > 0
    return token
