"""API E2E coverage for F044 unified permission settings entry.

Prerequisites:
- A running BiSheng backend and real MySQL/Redis/OpenFGA middleware.
- ``E2E_API_BASE`` and ``E2E_ADMIN_PASSWORD`` configured for that environment.
- Optional ``E2E_F044_CROSS_TENANT_USER_ID``: an active user that belongs to a
  different tenant. The exact cross-tenant create rejection is skipped when it
  is not supplied because inventing an ID would only test a missing subject.

Every resource name is isolated by a per-run ``f044-e2e-<uuid>-`` prefix. The
autouse fixture performs prefix-scoped cleanup both before and in ``finally``
after the test. Cleanup failures are collected and fail teardown with request
and response evidence instead of being swallowed.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import (
    auth_headers,
    create_test_user,
    get_admin_token,
    get_user_token,
)

RUN_ID = uuid.uuid4().hex[:8]
PREFIX = f"f044-e2e-{RUN_ID}-"
TEST_USER_PASSWORD = "F044_e2e_user_123"
CLEANUP_LIST_SPECS = (
    ("space", f"{API_BASE}/knowledge/space/mine", {}, "name", "id"),
    (
        "channel",
        f"{API_BASE}/channel/manager/my_channels",
        {"query_type": "created", "sort_by": "latest_update"},
        "name",
        "id",
    ),
    (
        "user",
        f"{API_BASE}/user/list",
        {"page_num": 1, "page_size": 100, "name": PREFIX},
        "user_name",
        "user_id",
    ),
)


def _rows(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get("data") or data.get("items") or []
        return rows if isinstance(rows, list) else []
    return []


def _assert_envelope(response: httpx.Response) -> dict:
    """Assert the complete UnifiedResponseModel shape and return its body."""
    assert response.status_code == 200, f"HTTP {response.status_code}: {response.text[:300]}"
    body = response.json()
    assert {"status_code", "status_message", "data"}.issubset(body), body
    return body


def _assert_error(response: httpx.Response, expected_codes: set[int]) -> dict:
    body = _assert_envelope(response)
    assert body["status_code"] in expected_codes, (
        f"expected one of {sorted(expected_codes)}, got {body['status_code']}: {body}"
    )
    return body


def _assert_only_creator_owner(permissions: list[dict], creator_id: int) -> None:
    assert any(
        item.get("subject_type") == "user"
        and int(item["subject_id"]) == creator_id
        and item.get("relation") == "owner"
        and item.get("is_creator") is True
        for item in permissions
    ), permissions
    assert all(
        item.get("subject_type") == "user" and int(item["subject_id"]) == creator_id and item.get("relation") == "owner"
        for item in permissions
    ), permissions


async def _record_delete(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    headers: dict,
    evidence: list[str],
    json: dict | None = None,
) -> None:
    try:
        response = await client.request(method, url, headers=headers, json=json)
        body = response.json() if response.content else {}
        if response.status_code != 200 or body.get("status_code") != 200:
            evidence.append(
                f"{method} {url}: http={response.status_code} "
                f"business={body.get('status_code')} body={response.text[:300]}"
            )
    except Exception as error:  # pragma: no cover - only observable in a real E2E environment
        evidence.append(f"{method} {url}: {type(error).__name__}: {error}")


async def _list_prefixed_objects(
    client: httpx.AsyncClient,
    *,
    headers: dict,
    evidence: list[str],
) -> list[tuple[str, str, str]]:
    matches: list[tuple[str, str, str]] = []
    for resource_type, url, params, name_key, id_key in CLEANUP_LIST_SPECS:
        try:
            response = await client.get(url, params=params, headers=headers)
            body = _assert_envelope(response)
            if body["status_code"] != 200:
                evidence.append(f"GET {url}: business={body['status_code']} body={response.text[:300]}")
                continue
            items = _rows(body.get("data"))
        except Exception as error:  # pragma: no cover - real environment evidence path
            evidence.append(f"GET {url}: {type(error).__name__}: {error}")
            continue

        for item in items:
            name = str(item.get(name_key, ""))
            if not name.startswith(PREFIX):
                continue
            resource_id = item.get(id_key)
            if resource_id is None:
                evidence.append(f"{resource_type} cleanup missing id: {item}")
                continue
            matches.append((resource_type, str(resource_id), name))
    return matches


async def _cleanup_prefix(
    client: httpx.AsyncClient,
    token: str,
    evidence: list[str],
) -> None:
    """Delete/disable only objects whose names start with this run's prefix."""
    if len(PREFIX) < 5:
        raise AssertionError("unsafe cleanup prefix")
    headers = auth_headers(token)
    matches = await _list_prefixed_objects(client, headers=headers, evidence=evidence)
    for resource_type, resource_id, _name in matches:
        if resource_type == "space":
            await _record_delete(
                client,
                method="DELETE",
                url=f"{API_BASE}/knowledge/space/{resource_id}",
                headers=headers,
                evidence=evidence,
            )
        elif resource_type == "channel":
            await _record_delete(
                client,
                method="DELETE",
                url=f"{API_BASE}/channel/manager/{resource_id}",
                headers=headers,
                evidence=evidence,
            )
        else:
            # User deletion is soft-delete in this API. Disabling prevents
            # login/reuse while preserving the normal audit hook.
            await _record_delete(
                client,
                method="POST",
                url=f"{API_BASE}/user/update",
                headers=headers,
                json={"user_id": resource_id, "delete": 1},
                evidence=evidence,
            )

    remaining = await _list_prefixed_objects(client, headers=headers, evidence=evidence)
    for resource_type, resource_id, name in remaining:
        evidence.append(f"post-cleanup residual: type={resource_type} id={resource_id} name={name}")


@pytest.mark.asyncio
class TestE2EF044UnifiedPermissionEntry:
    """F044 API E2E: candidates, create+grants, failure recovery and privacy."""

    @pytest.fixture(autouse=True, scope="class")
    async def setup_and_teardown(self):
        cleanup_evidence: list[str] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                admin_token = await get_admin_token(client)
            except (httpx.HTTPError, AssertionError) as error:
                pytest.skip(f"F044 real E2E environment unavailable: {error}")

            await _cleanup_prefix(client, admin_token, cleanup_evidence)
            assert not cleanup_evidence, "pre-test cleanup failed:\n" + "\n".join(cleanup_evidence)
            try:
                yield
            finally:
                cleanup_evidence.clear()
                try:
                    admin_token = await get_admin_token(client)
                    await _cleanup_prefix(client, admin_token, cleanup_evidence)
                except Exception as error:  # pragma: no cover - real environment evidence path
                    cleanup_evidence.append(f"cleanup bootstrap: {type(error).__name__}: {error}")
                assert not cleanup_evidence, "post-test cleanup failed:\n" + "\n".join(cleanup_evidence)

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        return await get_admin_token(client)

    @pytest.fixture
    async def test_user(self, client, admin_token) -> tuple[dict, str]:
        return await self._ensure_test_user(client, admin_token)

    async def _ensure_test_user(self, client, admin_token) -> tuple[dict, str]:
        username = f"{PREFIX}member"
        response = await client.get(
            f"{API_BASE}/user/list",
            params={"page_num": 1, "page_size": 100, "name": username},
            headers=auth_headers(admin_token),
        )
        users = _rows(assert_resp_200(response))
        user = next((item for item in users if item.get("user_name") == username), None)
        if user is None:
            user = await create_test_user(
                client,
                admin_token,
                username=username,
                role_id=2,
                password=TEST_USER_PASSWORD,
            )
        token = await get_user_token(client, username, TEST_USER_PASSWORD)
        return user, token

    async def _creation_users(self, client, token, resource_type: str, keyword: str) -> list[dict]:
        response = await client.get(
            f"{API_BASE}/permissions/creation-grant-subjects",
            params={
                "resource_type": resource_type,
                "subject_type": "user",
                "operation": "list",
                "keyword": keyword,
                "page": 1,
                "page_size": 50,
            },
            headers=auth_headers(token),
        )
        return _rows(assert_resp_200(response))

    async def _permissions(self, client, token, resource_type: str, resource_id: str) -> list[dict]:
        if resource_type == "channel":
            url = f"{API_BASE}/channel/manager/{resource_id}/permissions"
        else:
            url = f"{API_BASE}/permissions/resources/{resource_type}/{resource_id}/permissions"
        return _rows(assert_resp_200(await client.get(url, headers=auth_headers(token))))

    async def _created_name_count(self, client, token, resource_type: str, name: str) -> int:
        if resource_type == "channel":
            url = f"{API_BASE}/channel/manager/my_channels"
            params = {"query_type": "created", "sort_by": "latest_update"}
        else:
            url = f"{API_BASE}/knowledge/space/mine"
            params = {}
        rows = _rows(assert_resp_200(await client.get(url, params=params, headers=auth_headers(token))))
        return sum(item.get("name") == name for item in rows)

    async def test_ac06_ac11_creation_candidates_and_grantable_models(
        self,
        client,
        admin_token,
        test_user,
    ):
        """AC-06/11/22/25: both create pages use tenant-scoped candidates and prospective-owner models."""
        user, _ = test_user
        user_id = int(user["user_id"])

        for resource_type in ("knowledge_space", "channel"):
            candidates = await self._creation_users(client, admin_token, resource_type, PREFIX)
            assert any(int(item["user_id"]) == user_id for item in candidates)

            response = await client.get(
                f"{API_BASE}/permissions/relation-models/grantable",
                params={"object_type": resource_type, "creation": "true"},
                headers=auth_headers(admin_token),
            )
            models = _rows(assert_resp_200(response))
            assert models
            assert all(model.get("relation") in {"owner", "manager", "editor", "viewer"} for model in models)

    async def test_ac12_ac13_ac20_ac21_create_failure_and_private_round_trip(
        self,
        client,
        admin_token,
        test_user,
    ):
        """AC-12/13/20/21/23/24: grants persist, failed grants retain resources, private never restores."""
        user, _ = test_user
        member_id = int(user["user_id"])
        admin_info = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=auth_headers(admin_token)))
        creator_id = int(admin_info["user_id"])
        member_grant = {
            "subject_type": "user",
            "subject_id": member_id,
            "relation": "editor",
            "include_children": False,
        }

        space_response = await client.post(
            f"{API_BASE}/knowledge/space",
            json={
                "name": f"{PREFIX}space-shared",
                "description": "F044 initial grant E2E",
                "auth_type": "approval",
                "initial_permissions": {"grants": [member_grant]},
            },
            headers=auth_headers(admin_token),
        )
        space = assert_resp_200(space_response)
        assert space["initial_permission_result"] == {"status": "success", "error_code": None}
        space_id = str(space["id"])
        assert any(
            int(item["subject_id"]) == member_id and item["relation"] == "editor"
            for item in await self._permissions(client, admin_token, "knowledge_space", space_id)
        )

        channel_response = await client.post(
            f"{API_BASE}/channel/manager/create",
            json={
                "name": f"{PREFIX}channel-shared",
                "description": "F044 initial grant E2E",
                "visibility": "review",
                "source_list": [],
                "initial_permissions": {"grants": [member_grant]},
            },
            headers=auth_headers(admin_token),
        )
        channel = assert_resp_200(channel_response)
        assert channel["initial_permission_result"] == {"status": "success", "error_code": None}
        channel_id = str(channel["id"])
        assert any(
            int(item["subject_id"]) == member_id and item["relation"] == "editor"
            for item in await self._permissions(client, admin_token, "channel", channel_id)
        )

        # A self-grant passes creation subject validation but is rejected by the
        # post-create creator-protection rule. This deterministically exercises
        # the "resource exists + initial permission failed" contract without a mock.
        self_grant = {**member_grant, "subject_id": creator_id, "relation": "viewer"}
        failed_space_name = f"{PREFIX}space-grant-failed"
        failed_space = assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space",
                json={
                    "name": failed_space_name,
                    "auth_type": "approval",
                    "initial_permissions": {"grants": [self_grant]},
                },
                headers=auth_headers(admin_token),
            )
        )
        assert failed_space["id"]
        assert failed_space["initial_permission_result"] == {
            "status": "failed",
            "error_code": 19000,
        }
        failed_space_id = str(failed_space["id"])
        assert (
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/knowledge/space/{failed_space_id}/info",
                    headers=auth_headers(admin_token),
                )
            )["id"]
            == failed_space["id"]
        )
        assert not any(
            int(item["subject_id"]) == creator_id and item["relation"] == "viewer"
            for item in await self._permissions(
                client,
                admin_token,
                "knowledge_space",
                failed_space_id,
            )
        )
        assert (
            await self._created_name_count(
                client,
                admin_token,
                "knowledge_space",
                failed_space_name,
            )
            == 1
        )
        _assert_error(
            await client.post(
                f"{API_BASE}/permissions/resources/knowledge_space/{failed_space_id}/authorize",
                json={"grants": [self_grant], "revokes": []},
                headers=auth_headers(admin_token),
            ),
            {19000},
        )
        assert (
            await self._created_name_count(
                client,
                admin_token,
                "knowledge_space",
                failed_space_name,
            )
            == 1
        )
        assert not any(
            int(item["subject_id"]) == creator_id and item["relation"] == "viewer"
            for item in await self._permissions(
                client,
                admin_token,
                "knowledge_space",
                failed_space_id,
            )
        )

        failed_channel_name = f"{PREFIX}channel-grant-failed"
        failed_channel = assert_resp_200(
            await client.post(
                f"{API_BASE}/channel/manager/create",
                json={
                    "name": failed_channel_name,
                    "visibility": "review",
                    "source_list": [],
                    "initial_permissions": {"grants": [self_grant]},
                },
                headers=auth_headers(admin_token),
            )
        )
        assert failed_channel["id"]
        assert failed_channel["initial_permission_result"] == {
            "status": "failed",
            "error_code": 19013,
        }
        failed_channel_id = str(failed_channel["id"])
        assert (
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/channel/manager/{failed_channel_id}",
                    headers=auth_headers(admin_token),
                )
            )["id"]
            == failed_channel["id"]
        )
        assert not any(
            int(item["subject_id"]) == creator_id and item["relation"] == "viewer"
            for item in await self._permissions(
                client,
                admin_token,
                "channel",
                failed_channel_id,
            )
        )
        assert (
            await self._created_name_count(
                client,
                admin_token,
                "channel",
                failed_channel_name,
            )
            == 1
        )
        _assert_error(
            await client.post(
                f"{API_BASE}/channel/manager/{failed_channel_id}/authorize",
                json={"grants": [self_grant], "revokes": []},
                headers=auth_headers(admin_token),
            ),
            {19013},
        )
        assert (
            await self._created_name_count(
                client,
                admin_token,
                "channel",
                failed_channel_name,
            )
            == 1
        )
        assert not any(
            int(item["subject_id"]) == creator_id and item["relation"] == "viewer"
            for item in await self._permissions(
                client,
                admin_token,
                "channel",
                failed_channel_id,
            )
        )

        assert_resp_200(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}",
                json={"auth_type": "private"},
                headers=auth_headers(admin_token),
            )
        )
        _assert_only_creator_owner(
            await self._permissions(client, admin_token, "knowledge_space", space_id),
            creator_id,
        )
        assert_resp_200(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}",
                json={"auth_type": "approval"},
                headers=auth_headers(admin_token),
            )
        )
        _assert_only_creator_owner(
            await self._permissions(client, admin_token, "knowledge_space", space_id),
            creator_id,
        )

        assert_resp_200(
            await client.put(
                f"{API_BASE}/channel/manager/{channel_id}",
                json={"visibility": "private"},
                headers=auth_headers(admin_token),
            )
        )
        _assert_only_creator_owner(
            await self._permissions(client, admin_token, "channel", channel_id),
            creator_id,
        )
        assert_resp_200(
            await client.put(
                f"{API_BASE}/channel/manager/{channel_id}",
                json={"visibility": "review"},
                headers=auth_headers(admin_token),
            )
        )
        _assert_only_creator_owner(
            await self._permissions(client, admin_token, "channel", channel_id),
            creator_id,
        )

    async def test_ac09_ac10_submit_after_permission_loss_is_denied(
        self,
        client,
        admin_token,
        test_user,
    ):
        """AC-09/10/16: a page opened while editable cannot submit after its grant is revoked."""
        user, member_token = test_user
        member_id = int(user["user_id"])
        grant = {
            "subject_type": "user",
            "subject_id": member_id,
            "relation": "editor",
            "include_children": False,
        }
        space = assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space",
                json={
                    "name": f"{PREFIX}space-permission-loss",
                    "auth_type": "approval",
                    "initial_permissions": {"grants": [grant]},
                },
                headers=auth_headers(admin_token),
            )
        )
        space_id = str(space["id"])
        assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/info",
                headers=auth_headers(member_token),
            )
        )

        assert_resp_200(
            await client.post(
                f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/authorize",
                json={"grants": [], "revokes": [grant]},
                headers=auth_headers(admin_token),
            )
        )
        _assert_error(
            await client.put(
                f"{API_BASE}/knowledge/space/{space_id}",
                json={"description": "must not be saved after permission loss"},
                headers=auth_headers(member_token),
            ),
            {18040},
        )
        reloaded = assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/info",
                headers=auth_headers(admin_token),
            )
        )
        assert reloaded.get("description") != "must not be saved after permission loss"

    async def test_ac09_ac22_cross_tenant_subject_rejected_before_create(self, client, admin_token):
        """AC-09/22/25: a subject outside the active tenant is rejected before resource creation."""
        raw_subject_id = os.environ.get("E2E_F044_CROSS_TENANT_USER_ID")
        if not raw_subject_id:
            pytest.skip("set E2E_F044_CROSS_TENANT_USER_ID for exact cross-tenant coverage")
        cross_tenant_user_id = int(raw_subject_id)
        name = f"{PREFIX}cross-tenant-rejected"
        response = await client.post(
            f"{API_BASE}/knowledge/space",
            json={
                "name": name,
                "auth_type": "approval",
                "initial_permissions": {
                    "grants": [
                        {
                            "subject_type": "user",
                            "subject_id": cross_tenant_user_id,
                            "relation": "viewer",
                            "include_children": False,
                        }
                    ]
                },
            },
            headers=auth_headers(admin_token),
        )
        _assert_error(response, {19000})

        spaces = _rows(
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/knowledge/space/mine",
                    headers=auth_headers(admin_token),
                )
            )
        )
        assert not any(item.get("name") == name for item in spaces)
